"""全局热键速查：复制 Riot ID 后按热键，在鼠标旁弹出违规次数卡片。

用于补上「客户端搜索框无法内嵌」的缺口：复制客户端里的 Riot ID，按一下热键
就能看到总违规次数与分类型明细，不用切回主窗口。
"""
import logging
import threading
import time

import customtkinter as ctk

from . import win32
from .hotkey import HotkeyManager, format_hotkey
from .overlay_model import geometry_position
from .quick_lookup_model import compute_card_position, parse_riot_id, summarize_lookup

LOGGER = logging.getLogger('lol_match_query')

CARD_WIDTH = 300
ERROR_HIDE_MS = 2800
DEFAULT_HOTKEY = 'ctrl+alt+q'


class QuickLookupWindow:
    """鼠标旁的结果卡片：无边框、置顶、不抢焦点，点 × 关闭"""

    def __init__(self, master, colors, alpha=0.97):
        self.master = master
        self.colors = colors
        self.alpha = alpha
        self._width = CARD_WIDTH
        self._height = 110
        self._pos = None
        self._hwnd = 0
        self._build()

    # ===== 构建 =====

    def _build(self):
        self.top = ctk.CTkToplevel(self.master)
        self.top.withdraw()
        self.top.overrideredirect(True)
        self.top.attributes('-topmost', True)
        self.top.attributes('-alpha', self.alpha)
        self.top.configure(fg_color=self.colors['bg'])
        self.top.update_idletasks()
        win32.make_overlay_window(self.hwnd)

        self._container = ctk.CTkFrame(
            self.top, fg_color=self.colors['card'], corner_radius=10,
            border_width=1, border_color='#3a4150')
        self._container.pack(fill='both', expand=True)

        header = ctk.CTkFrame(self._container, fg_color='transparent')
        header.pack(fill='x', padx=10, pady=(7, 1))

        ctk.CTkLabel(
            header, text='●', width=10, font=('Microsoft YaHei', 9),
            text_color=self.colors['blue']).pack(side='left')
        ctk.CTkLabel(
            header, text='召唤师速查', font=('Microsoft YaHei', 11, 'bold'),
            text_color=self.colors['gold']).pack(side='left', padx=(2, 6))

        self._close_btn = ctk.CTkButton(
            header, text='×', width=20, height=20, corner_radius=4,
            fg_color='transparent', hover_color='#3a4150',
            font=('Microsoft YaHei', 12),
            text_color=self.colors['text_secondary'], command=self.hide)
        self._close_btn.pack(side='right')

        self._name_label = ctk.CTkLabel(
            self._container, text='', anchor='w',
            font=('Microsoft YaHei', 12, 'bold'),
            text_color=self.colors['text_primary'])
        self._name_label.pack(fill='x', padx=12)

        self._region_label = ctk.CTkLabel(
            self._container, text='', anchor='w',
            font=('Microsoft YaHei', 9),
            text_color=self.colors['text_secondary'])
        self._region_label.pack(fill='x', padx=12, pady=(0, 2))

        self._body = ctk.CTkFrame(self._container, fg_color='transparent')
        self._body.pack(fill='x', padx=10, pady=(2, 2))

        self._footer = ctk.CTkLabel(
            self._container, text='', anchor='w',
            font=('Microsoft YaHei', 9),
            text_color=self.colors['text_secondary'])
        self._footer.pack(fill='x', padx=12, pady=(0, 6))

    # ===== 状态渲染 =====

    def render_loading(self, riot_id):
        self._name_label.configure(text=riot_id or '召唤师速查',
                                   text_color=self.colors['text_primary'])
        self._region_label.configure(text='正在解析召唤师信息…')
        self._set_body([('查询中…', self.colors['text_secondary'], 10, False)])
        self._footer.configure(text='')
        self._resize()

    def render_result(self, riot_id, region, summary):
        self._name_label.configure(text=riot_id or '未知召唤师',
                                   text_color=self.colors['gold'])
        self._region_label.configure(text=region or '未知大区')

        total = summary.get('total', 0)
        items = [(
            f'违规 {total} 次',
            self.colors['red'] if total > 0 else self.colors['green'],
            14, True,
        )]
        for type_name, count in summary.get('types', [])[:6]:
            items.append((f'{type_name}  {count}次',
                          self.colors['text_secondary'], 9, False))
        if not summary.get('types'):
            items.append(('暂无分类型记录', self.colors['text_secondary'], 9, False))

        self._set_body(items)
        self._footer.configure(text=time.strftime('查询于 %H:%M'))
        self._resize()

    def render_error(self, message, riot_id=''):
        self._name_label.configure(text=riot_id or '召唤师速查',
                                   text_color=self.colors['text_primary'])
        self._region_label.configure(text='')
        self._set_body([(message, self.colors['red'], 10, False)])
        self._footer.configure(text='复制完整 Riot ID（含 #TAG）后重试')
        self._resize()

    def _set_body(self, items):
        for child in self._body.winfo_children():
            child.destroy()
        for text, color, size, bold in items:
            ctk.CTkLabel(
                self._body, text=text, anchor='w', justify='left',
                wraplength=max(160, self._width - 40),
                font=('Microsoft YaHei', size, 'bold' if bold else 'normal'),
                text_color=color).pack(fill='x', pady=1)

    # ===== 尺寸 / 位置 / 显示 =====

    def _resize(self):
        self.top.update_idletasks()
        height = int(self._container.winfo_reqheight() or 0)
        if height < 10:
            return
        width = self._scaled_width()
        self._height = height
        self._width = width
        self.top.geometry(f'{width}x{height}')

    def _scaled_width(self):
        scale = 1.0
        try:
            scale = float(ctk.ScalingTracker.get_window_scaling(self.top) or 1.0)
        except Exception:
            scale = 1.0
        return max(200, int(CARD_WIDTH * scale))

    def move_to(self, x, y):
        position = (int(x), int(y))
        if position == self._pos:
            return
        self._pos = position
        self.top.geometry(geometry_position(*position))

    def show(self):
        if not self.top.winfo_ismapped():
            self.top.deiconify()
        self.top.lift()
        self.top.attributes('-topmost', True)

    def hide(self):
        if self.top.winfo_ismapped():
            self.top.withdraw()

    def is_visible(self):
        return bool(self.top.winfo_ismapped())

    def size(self):
        return self._width, self._height

    @property
    def hwnd(self):
        if not self._hwnd:
            self._hwnd = win32.toplevel_hwnd(self.top)
        return self._hwnd

    def destroy(self):
        try:
            self.top.destroy()
        except Exception:
            pass


class QuickLookupController:
    """注册全局热键，读取剪贴板 Riot ID，后台查询后弹出结果卡片"""

    def __init__(self, app):
        self.app = app
        self.root = app.root
        self.config = app.config
        self.window = None
        self.manager = None

        self._seq = 0
        self._anchor = (0, 0)
        self._hide_job = None

    @property
    def enabled(self):
        return bool(self.manager and self.manager.available)

    @property
    def error(self):
        return self.manager.error if self.manager else ''

    @property
    def hotkey_text(self):
        return format_hotkey(self.config.get('hotkey', DEFAULT_HOTKEY))

    # ===== 生命周期 =====

    def start(self):
        if not self.config.get('hotkey_enabled', True):
            return False
        self.manager = HotkeyManager(
            self.config.get('hotkey', DEFAULT_HOTKEY), self._on_hotkey)
        return self.manager.start()

    def stop(self):
        self._cancel_hide()
        if self.manager is not None:
            self.manager.stop()
            self.manager = None
        if self.window is not None:
            self.window.destroy()
            self.window = None

    # ===== 触发 =====

    def _on_hotkey(self):
        """热键线程回调：转回 Tk 主线程读剪贴板"""
        try:
            self.root.after(0, self.trigger_from_clipboard)
        except Exception:
            # 程序正在退出
            pass

    def trigger_from_clipboard(self):
        """读取剪贴板 → 解析 Riot ID → 查询（UI 线程调用）"""
        # 有模态对话框（举报确认等）时不打断
        if self.root.grab_current() is not None:
            return
        self._anchor = win32.cursor_pos() or self._anchor
        parsed = parse_riot_id(self._read_clipboard())
        if not parsed:
            self._hide_job = self._present(
                lambda window: window.render_error('剪贴板里没有有效的 Riot ID'),
                auto_hide=ERROR_HIDE_MS)
            return

        game_name, tag = parsed
        riot_id = f'{game_name}#{tag}'
        self._seq += 1
        seq = self._seq
        self._hide_job = self._present(
            lambda window: window.render_loading(riot_id))
        threading.Thread(
            target=self._lookup, args=(seq, riot_id), daemon=True).start()

    def _lookup(self, seq, riot_id):
        def _done(state):
            try:
                self.root.after(0, lambda: self._apply_result(seq, state))
            except Exception:
                pass

        if not self.app.is_running:
            _done({'kind': 'error', 'message': '请先在主窗口点击「启动工具」'})
            return

        account = self.app.account_info or {}
        platform_id = account.get('platform_id', '')
        region = account.get('region_name') or platform_id
        if not platform_id:
            _done({'kind': 'error', 'message': '未获取大区信息，请确保客户端已连接'})
            return

        try:
            data = self.app.match_service.search_summoner(riot_id)
        except Exception as exc:
            LOGGER.exception('速查召唤师失败')
            _done({'kind': 'error', 'message': f'召唤师查询异常: {exc}'})
            return
        if not data:
            _done({'kind': 'error', 'message': '未找到该召唤师（检查 Riot ID 或客户端连接）'})
            return

        puuid = data.get('puuid') or ''
        if not puuid:
            _done({'kind': 'error', 'message': '该召唤师信息不完整（缺少 PUUID）'})
            return

        alias = data.get('alias') or {}
        game_name = alias.get('gameName') or data.get('gameName') or ''
        tag_line = alias.get('tagLine') or data.get('tagLine') or ''
        display_id = f'{game_name}#{tag_line}' if game_name and tag_line else riot_id

        try:
            result = self.app.violation_client.query_count(puuid, platform_id)
        except Exception as exc:
            LOGGER.exception('速查违规记录失败')
            _done({'kind': 'error', 'message': f'违规查询异常: {exc}'})
            return
        if result.get('code') != 200:
            _done({'kind': 'error',
                   'message': result.get('message') or '违规查询失败'})
            return

        payload = result.get('data')
        summary = summarize_lookup(payload) if payload is not None else {
            'total': 0, 'types': []}
        _done({
            'kind': 'result',
            'riot_id': display_id,
            'region': region,
            'summary': summary,
        })

    def _apply_result(self, seq, state):
        if seq != self._seq:
            return
        if state['kind'] == 'error':
            self._hide_job = self._present(
                lambda window: window.render_error(state['message'],
                                                   state.get('riot_id', '')),
                auto_hide=ERROR_HIDE_MS)
            return
        self._hide_job = self._present(
            lambda window: window.render_result(
                state['riot_id'], state['region'], state['summary']))

    # ===== 卡片展示 =====

    def _ensure_window(self):
        if self.window is None:
            self.window = QuickLookupWindow(self.root, self.app.COLORS)
        return self.window

    def _present(self, render, auto_hide=0):
        window = self._ensure_window()
        self._cancel_hide()
        render(window)
        size = window.size()
        work_area = win32.work_area_at_point(*self._anchor) or (
            0, 0, self.root.winfo_screenwidth(), self.root.winfo_screenheight())
        x, y = compute_card_position(self._anchor, size, work_area)
        window.move_to(x, y)
        window.show()
        if auto_hide:
            return self.root.after(auto_hide, self._hide)
        return None

    def _hide(self):
        self._hide_job = None
        if self.window is not None:
            self.window.hide()

    def _cancel_hide(self):
        if self._hide_job:
            try:
                self.root.after_cancel(self._hide_job)
            except Exception:
                pass
            self._hide_job = None

    def _read_clipboard(self):
        try:
            return self.root.clipboard_get()
        except Exception:
            return ''
