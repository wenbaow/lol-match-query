"""桌面悬浮层：跟随英雄联盟客户端 / 游戏窗口显示对局玩家违规次数。

设计要点：
- 不注入、不修改客户端：只消费 LCU 事件 + Win32 窗口位置
- 悬浮层贴在客户端窗口右侧（空间不足自动换边），加载/对局时贴游戏窗口
- 仅当目标窗口在前台时显示，避免遮挡其它程序
- 进入选人 / 加载 / 对局时自动批量查询违规次数（可在主窗口关闭）
- 粗体数字来自后端 batch 接口的 violationCount（当前只显示总次数）
"""
import logging
import threading
import time

import customtkinter as ctk

from ..config import save_config
from . import win32
from .overlay_model import (
    MODE_IDLE,
    MODE_IN_GAME,
    MODE_LOADING,
    build_overlay_model,
    collect_puuids,
    compute_overlay_position,
    geometry_position,
    is_active_mode,
    match_signature,
    phase_mode,
    truncate_name,
)
from .utils import safe_int

LOGGER = logging.getLogger('lol_match_query')

OVERLAY_WIDTH = 272
TICK_MS = 250
QUERY_DEBOUNCE_MS = 700
QUERY_RETRY_SECONDS = 30
DRAG_SAVE_DELAY_MS = 800
OFFSET_LIMIT = 4000

BADGE_COLORS = {
    'champ_select': '#FB8C00',
    'loading': '#4FC3F7',
    'in_game': '#43A047',
}


class OverlayWindow:
    """无边框置顶悬浮窗（可拖拽，不进入任务栏/Alt-Tab）"""

    def __init__(self, master, colors, champion_data, alpha=0.95, on_close=None,
                 on_drag=None, on_drag_end=None):
        self.master = master
        self.colors = colors
        self.champion_data = champion_data
        self.alpha = alpha
        self.on_close = on_close
        self.on_drag = on_drag
        self.on_drag_end = on_drag_end

        self._signature = None
        self._pos = None
        self._width = OVERLAY_WIDTH
        self._height = 120
        self._hwnd = 0
        self._drag_origin = None
        self._build()

    # ===== 构建 =====

    def _build(self):
        self.top = ctk.CTkToplevel(self.master)
        self.top.withdraw()
        self.top.overrideredirect(True)
        self.top.attributes('-topmost', True)
        self.top.attributes('-alpha', self.alpha)
        self.top.configure(fg_color=self.colors['bg'])
        # 不抢焦点、不进入 Alt-Tab：避免悬浮层出现时打断客户端里的输入
        self.top.update_idletasks()
        win32.make_overlay_window(self.hwnd)

        self._container = ctk.CTkFrame(
            self.top, fg_color=self.colors['card'], corner_radius=10,
            border_width=1, border_color='#3a4150')
        self._container.pack(fill='both', expand=True)

        header = ctk.CTkFrame(self._container, fg_color='transparent')
        header.pack(fill='x', padx=10, pady=(7, 2))

        self._dot = ctk.CTkLabel(
            header, text='●', width=10, font=('Microsoft YaHei', 9),
            text_color=self.colors['text_secondary'])
        self._dot.pack(side='left')

        self._title = ctk.CTkLabel(
            header, text='对局标记', font=('Microsoft YaHei', 11, 'bold'),
            text_color=self.colors['gold'])
        self._title.pack(side='left', padx=(2, 6))

        self._badge = ctk.CTkLabel(
            header, text='—', width=42, height=18, corner_radius=6,
            fg_color='#2f3640', font=('Microsoft YaHei', 9),
            text_color=self.colors['text_primary'])
        self._badge.pack(side='left')

        self._close_btn = ctk.CTkButton(
            header, text='×', width=20, height=20, corner_radius=4,
            fg_color='transparent', hover_color='#3a4150',
            font=('Microsoft YaHei', 12),
            text_color=self.colors['text_secondary'], command=self._close)
        self._close_btn.pack(side='right')

        self._body = ctk.CTkFrame(self._container, fg_color='transparent')
        self._body.pack(fill='x', padx=8, pady=(0, 2))

        self._footer = ctk.CTkLabel(
            self._container, text='', anchor='w',
            font=('Microsoft YaHei', 9),
            text_color=self.colors['text_secondary'])
        self._footer.pack(fill='x', padx=10, pady=(0, 6))

        # 头部与空白处可拖拽，关闭按钮不参与
        for widget in (self._container, header, self._dot, self._title, self._badge):
            self._bind_drag(widget)

    def _bind_drag(self, widget):
        widget.bind('<ButtonPress-1>', self._drag_start)
        widget.bind('<B1-Motion>', self._drag_move)
        widget.bind('<ButtonRelease-1>', self._drag_end)

    # ===== 拖拽 =====

    def _drag_start(self, event):
        # 优先用最近一次 set_position 的记录，避免几何更新滞后导致拖拽加速
        if self._pos is not None:
            win_x, win_y = self._pos
        else:
            win_x, win_y = self.top.winfo_x(), self.top.winfo_y()
        self._drag_origin = (event.x_root, event.y_root, win_x, win_y)

    def _drag_move(self, event):
        if not self._drag_origin:
            return
        origin_x, origin_y, win_x, win_y = self._drag_origin
        x = win_x + (event.x_root - origin_x)
        y = win_y + (event.y_root - origin_y)
        self.set_position(x, y)
        if self.on_drag:
            self.on_drag(x, y)

    def _drag_end(self, _event):
        self._drag_origin = None
        if self.on_drag_end:
            self.on_drag_end()

    def _close(self):
        if self.on_close:
            self.on_close()

    # ===== 渲染 =====

    def render(self, model, status_text=''):
        """按模型更新内容；行数据无变化时只刷新状态栏，避免闪烁"""
        badge = model.get('badge') or '—'
        if str(self._badge.cget('text')) != badge:
            self._badge.configure(text=badge)
        mode = model.get('mode')
        color = BADGE_COLORS.get(mode, self.colors['text_secondary'])
        self._dot.configure(text_color=color)

        signature = self._make_signature(model)
        if signature != self._signature:
            self._rebuild(model)
            self._signature = signature
        self._footer.configure(text=status_text)
        self._resize()

    @staticmethod
    def _make_signature(model):
        rows = tuple(
            (row['puuid'], row['name'], row['champion_id'],
             row['champion'], row['count'])
            for group in model.get('groups', [])
            for row in group['rows']
        )
        return (model.get('mode'), model.get('hint'), rows)

    def _rebuild(self, model):
        for child in self._body.winfo_children():
            child.destroy()

        hint = model.get('hint')
        if hint:
            ctk.CTkLabel(
                self._body, text=hint, font=('Microsoft YaHei', 10),
                text_color=self.colors['text_secondary']).pack(pady=(10, 12))
            return

        for group in model.get('groups', []):
            ctk.CTkLabel(
                self._body, text=group['title'], anchor='w',
                font=('Microsoft YaHei', 9, 'bold'),
                text_color=self.colors['text_secondary']).pack(
                    fill='x', padx=2, pady=(4, 1))
            for row in group['rows']:
                self._build_row(row)

    def _build_row(self, row):
        flagged = row['flagged']
        background = '#2c2429' if flagged else '#232830'
        frame = ctk.CTkFrame(
            self._body, fg_color=background, corner_radius=5, height=24)
        frame.pack(fill='x', pady=1)
        frame.pack_propagate(False)

        icon = None
        if row['champion_id']:
            icon = self.champion_data.get_champion_icon(row['champion_id'], size=18)
        placeholder = '?' if row['champion_id'] else '·'
        ctk.CTkLabel(
            frame, text='' if icon else placeholder, image=icon, width=20,
            font=('Microsoft YaHei', 9),
            text_color=self.colors['text_secondary']).pack(side='left', padx=(4, 2))

        if row['hidden']:
            name_color = self.colors['text_secondary']
        elif flagged:
            name_color = self.colors['red']
        elif row['self']:
            name_color = self.colors['gold']
        else:
            name_color = self.colors['text_primary']

        ctk.CTkLabel(
            frame, text=truncate_name(row['name'], 13), anchor='w',
            font=('Microsoft YaHei', 10), text_color=name_color).pack(side='left')

        if row['count_text']:
            ctk.CTkLabel(
                frame, text=row['count_text'], width=44, anchor='e',
                font=('Microsoft YaHei', 10, 'bold'),
                text_color=self.colors['red']).pack(side='right', padx=(2, 6))
        else:
            ctk.CTkLabel(
                frame, text='—', width=44, anchor='e',
                font=('Microsoft YaHei', 9),
                text_color=self.colors['text_secondary']).pack(side='right', padx=(2, 6))

    def _resize(self):
        self.top.update_idletasks()
        height = int(self._container.winfo_reqheight() or 0)
        if height < 10:
            return
        width = self._scaled_width()
        if (height == self._height and width == self._width
                and self.top.winfo_width() == width):
            return
        self._height = height
        self._width = width
        self.top.geometry(f'{width}x{height}')

    def _scaled_width(self):
        """按 customtkinter 的 DPI 缩放换算窗口宽度，避免高 DPI 下内容被裁切"""
        scale = 1.0
        try:
            scale = float(ctk.ScalingTracker.get_window_scaling(self.top) or 1.0)
        except Exception:
            scale = 1.0
        return max(180, int(OVERLAY_WIDTH * scale))

    # ===== 显示控制 =====

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

    def set_position(self, x, y):
        position = (int(x), int(y))
        if position == self._pos:
            return
        self._pos = position
        self.top.geometry(geometry_position(*position))

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


class OverlayController:
    """把对局事件接到悬浮层，并负责跟随、自动查询与配置持久化"""

    def __init__(self, app):
        self.app = app
        self.root = app.root
        self.config = app.config
        self.enabled = False
        self.window = None

        self._tick_job = None
        self._phase = 'None'
        self._match_data = None
        self._counts = {}
        self._self_puuid = ''
        self._offset = self._normalize_offset(self.config.get('overlay_offset'))
        self._target_hwnd = 0
        self._target_rect = None
        self._status = '等待对局'

        self._query_job = None
        self._querying = False
        self._query_key = ''
        self._queried_key = ''
        self._query_ok = False
        self._query_ts = 0.0
        self._save_job = None

    # ===== 生命周期 =====

    def enable(self):
        if self.enabled:
            return True
        if self.window is None:
            try:
                self.window = OverlayWindow(
                    self.root, self.app.COLORS, self.app.champion_data,
                    alpha=self.config.get('overlay_alpha', 0.95),
                    on_close=self._on_window_close,
                    on_drag=self._on_drag,
                    on_drag_end=self._on_drag_end)
            except Exception:
                LOGGER.exception('创建悬浮层失败')
                self.window = None
                return False
        self.enabled = True
        if self._match_data is None:
            self._status = '等待对局'
        self._apply()
        self._schedule_tick()
        return True

    def disable(self):
        self.enabled = False
        self._cancel(self._tick_job)
        self._tick_job = None
        if self.window is not None:
            self.window.hide()

    def shutdown(self):
        self.disable()
        self._cancel(self._query_job)
        self._cancel(self._save_job)
        if self.window is not None:
            self.window.destroy()
            self.window = None

    # ===== 事件入口（均在 UI 线程调用）=====

    def on_phase(self, phase):
        self._phase = phase or 'None'
        self._apply()

    def on_match_data(self, match_data):
        self._match_data = match_data
        self._apply()

    def on_clear(self):
        self._cancel(self._query_job)
        self._query_job = None
        self._match_data = None
        self._counts = {}
        self._query_key = ''
        self._queried_key = ''
        self._query_ok = False
        self._status = '等待对局'
        self._apply()

    def on_account(self, account_info):
        self._self_puuid = (account_info or {}).get('puuid', '')

    def on_counts_updated(self, counts):
        self._counts = dict(counts or {})
        self._query_key = match_signature(self._match_data)
        self._query_ok = True
        if self._counts:
            flagged = sum(1 for value in self._counts.values() if value > 0)
            self._status = f'已标记 {flagged}/{len(self._counts)} · {time.strftime("%H:%M")}'
        else:
            self._status = '暂无标记数据'
        self._apply()

    def on_stop(self):
        self._cancel(self._query_job)
        self._query_job = None
        self._querying = False
        self._phase = 'None'
        self._match_data = None
        self._counts = {}
        self._query_key = ''
        self._queried_key = ''
        self._query_ok = False
        self._status = '等待对局'
        if self.window is not None:
            self.window.hide()

    def refresh(self):
        """外部数据（如英雄头像下载完成）更新后重绘"""
        self._apply()

    # ===== 渲染 =====

    def _apply(self):
        if not self.enabled or self.window is None:
            return
        model = build_overlay_model(
            self._match_data, self._counts, self._phase,
            self._self_puuid, self._champion_names())
        self.window.render(model, self._status)
        if phase_mode(self._phase) == MODE_IDLE:
            self.window.hide()
        self._maybe_auto_query()

    def _champion_names(self):
        names = {}
        match_data = self._match_data or {}
        for key in ('my_team', 'enemy_team'):
            for player in match_data.get(key) or []:
                if not isinstance(player, dict):
                    continue
                champion_id = safe_int(player.get('champion_id'))
                if champion_id and champion_id not in names:
                    name = self.app.champion_data.get_champion_name(champion_id)
                    if name:
                        names[champion_id] = name
        return names

    # ===== 自动查询 =====

    def _maybe_auto_query(self):
        if not self.config.get('overlay_auto_query', True):
            return
        if not is_active_mode(phase_mode(self._phase)):
            return
        key = match_signature(self._match_data)
        if not key:
            return
        if self._querying or self._query_job is not None:
            return
        if key == self._query_key and (
                self._query_ok or time.time() - self._query_ts < QUERY_RETRY_SECONDS):
            return
        self._query_key = key
        self._query_job = self.root.after(QUERY_DEBOUNCE_MS, self._run_query)

    def _run_query(self):
        self._query_job = None
        if not self.enabled:
            return
        puuids = collect_puuids(self._match_data)
        platform_id = (self.app.account_info or {}).get('platform_id', '')
        if not puuids or not platform_id:
            return
        players = [{'platformId': platform_id, 'puuid': puuid} for puuid in puuids]
        self._querying = True
        self._queried_key = match_signature(self._match_data)
        self._query_ts = time.time()
        self._status = '查询中…'
        self._apply()
        threading.Thread(
            target=self._query_worker, args=(players,), daemon=True).start()

    def _query_worker(self, players):
        try:
            result = self.app.violation_client.batch_query_status(players)
        except Exception as exc:
            LOGGER.exception('悬浮层自动查询异常')
            result = {'code': 500, 'message': str(exc), 'data': None}
        try:
            self.root.after(0, lambda: self._on_query_done(result))
        except Exception:
            # 窗口已销毁（退出程序），丢弃结果
            pass

    def _on_query_done(self, result):
        self._querying = False
        if not self.enabled:
            return
        data = result.get('data') if result.get('code') == 200 else None
        if not isinstance(data, list):
            self._query_ok = False
            self._query_ts = time.time()
            self._status = '查询失败，稍后重试'
            self._apply()
            return

        counts = {}
        for item in data:
            if not isinstance(item, dict):
                continue
            puuid = item.get('puuid') or ''
            if puuid:
                counts[puuid] = safe_int(item.get('violationCount'))
        flagged = sum(1 for value in counts.values() if value > 0)
        self.app._apply_violation_counts(
            counts, status_text=f'自动查询: {flagged}/{len(counts)} 人有违规记录')

        # 查询结果只覆盖发起时的玩家；若对局数据已变化（如进游戏后补齐敌方），
        # 允许对新增玩家再查一次，而不是把新签名直接当成"已查询"
        self._query_key = self._queried_key
        self._query_ok = self._queried_key == match_signature(self._match_data)
        self._apply()

    # ===== 跟随 =====

    def _schedule_tick(self):
        self._cancel(self._tick_job)
        self._tick_job = self.root.after(TICK_MS, self._tick)

    def _tick(self):
        self._tick_job = None
        if not self.enabled:
            return
        try:
            self._follow_target()
        except Exception:
            LOGGER.exception('悬浮层跟随失败')
        if self.enabled:
            self._tick_job = self.root.after(TICK_MS, self._tick)

    def _follow_target(self):
        if self.window is None:
            return
        mode = phase_mode(self._phase)
        if mode == MODE_IDLE:
            self.window.hide()
            return
        target = self._pick_target(mode)
        if target is None:
            self.window.hide()
            return
        hwnd, rect = target
        if not self._should_show(hwnd):
            self.window.hide()
            return

        self._target_hwnd = hwnd
        self._target_rect = rect
        # 先定位再显示，避免首次出现时在屏幕角落闪一下
        work_area = win32.work_area(hwnd) or (
            0, 0, self.root.winfo_screenwidth(), self.root.winfo_screenheight())
        x, y = compute_overlay_position(
            rect, self.window.size(), self._offset, work_area)
        self.window.set_position(x, y)
        if not self.window.is_visible():
            self.window.show()

    @staticmethod
    def _pick_target(mode):
        if mode in (MODE_LOADING, MODE_IN_GAME):
            game = win32.find_game_window()
            if game:
                return game
        return win32.find_client_window()

    def _should_show(self, hwnd):
        if not win32.is_window(hwnd) or win32.is_minimized(hwnd):
            return False
        if not win32.is_visible(hwnd):
            return False
        foreground = win32.foreground_window()
        if not foreground:
            return True
        if foreground == hwnd:
            return True
        return bool(self.window is not None and self.window.hwnd == foreground)

    # ===== 拖拽与配置 =====

    def _on_drag(self, x, y):
        if not self._target_rect:
            return
        target_x, target_y, target_w, _target_h = self._target_rect
        dx = int(x - (target_x + target_w))
        dy = int(y - target_y)
        self._offset = (
            max(-OFFSET_LIMIT, min(OFFSET_LIMIT, dx)),
            max(-OFFSET_LIMIT, min(OFFSET_LIMIT, dy)),
        )

    def _on_drag_end(self):
        self.config['overlay_offset'] = [self._offset[0], self._offset[1]]
        self._cancel(self._save_job)
        self._save_job = self.root.after(DRAG_SAVE_DELAY_MS, self._save_offset)

    def _save_offset(self):
        self._save_job = None
        save_config(self.config)

    def _on_window_close(self):
        self.app._set_overlay_enabled(False)

    # ===== 工具 =====

    @staticmethod
    def _normalize_offset(value):
        if not isinstance(value, (list, tuple)) or len(value) != 2:
            return (12, 56)
        try:
            dx, dy = int(value[0]), int(value[1])
        except (TypeError, ValueError):
            return (12, 56)
        clamp = lambda v: max(-OFFSET_LIMIT, min(OFFSET_LIMIT, v))  # noqa: E731
        return (clamp(dx), clamp(dy))

    def _cancel(self, job):
        if not job:
            return
        try:
            self.root.after_cancel(job)
        except Exception:
            pass
