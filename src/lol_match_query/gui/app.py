"""主窗口界面：英雄联盟违规标记查询工具。

MatchQueryGUI 是组装根节点，持有 MatchMonitorService / ViolationClient /
ChampionDataProvider 三个服务实例；玩家卡片与对话框逻辑分别由
PlayerCardMixin、DialogMixin 提供。
"""
import logging
import sys
from datetime import datetime
from tkinter import messagebox

import customtkinter as ctk

from ..services.champions import ChampionDataProvider
from ..services.match_monitor import MatchMonitorService
from ..services.violation import ViolationClient
from .agent_ui import AgentUIMixin
from .dialogs import DialogMixin
from .player_card import PlayerCardMixin


class MatchQueryGUI(PlayerCardMixin, DialogMixin, AgentUIMixin):
    PHASE_DESCRIPTIONS = {
        'None': '空闲 / 客户端主界面',
        'Lobby': '组队房间',
        'Matchmaking': '寻找对局',
        'ReadyCheck': '接受对局',
        'ChampSelect': '英雄选择',
        'GameStart': '进入游戏',
        'InProgress': '游戏中',
        'Reconnecting': '重连中',
        'GameEnd': '游戏结束',
    }

    COLORS = {
        'bg': '#1e2329',
        'card': '#2a2f37',
        'card_hover': '#323842',
        'card_hover_active': '#3a4150',
        'gold': '#C89B3C',
        'blue': '#4FC3F7',
        'red': '#EF5350',
        'green': '#43A047',
        'orange': '#FB8C00',
        'text_primary': '#E8E8E8',
        'text_secondary': '#9AA0A6',
        'selected': '#31506E',
    }

    def __init__(self, root):
        self.root = root

        self.match_service = MatchMonitorService()
        # GUI 只通过事件订阅服务，不读取服务内部状态
        self.match_service.subscribe('log', self._on_log)
        self.match_service.subscribe('match_updated', self._on_match_data)
        self.match_service.subscribe('display_cleared', self._on_clear)
        self.match_service.subscribe('phase_changed', self._on_phase)
        self.match_service.subscribe('account_updated', self._on_account)

        self.violation_client = ViolationClient(log_callback=self._on_log)
        self.champion_data = ChampionDataProvider(log_callback=self._on_log)
        self.is_running = False
        self.current_phase = 'None'
        self.account_info = {}
        self.violation_counts = {}
        self.violation_details = {}
        self._violation_detail_querying = set()  # 正在查询违规详情的 puuid 集合
        self.selected_player = None
        self._selected_card = None
        self._match_data_cache = None
        self._detail_expanded = False
        self._blink_job = None
        self._teams_stacked = False
        self._icon_preload_job = None
        self._icon_preload_pending = []

        self._build_ui()
        # 后台初始化英雄数据，完成后若有缓存对局则刷新卡片以显示头像
        self.champion_data.initialize_async(
            done_callback=lambda: self.root.after(0, self._refresh_cards_if_needed)
        )
        # 启动 AgentQuay 接入（后台连接 + 队列轮询），Agent 即可通过 MCP 调用本应用工具
        self.start_agent_service()

    def _build_ui(self):
        self.root.configure(fg_color=self.COLORS['bg'])

        main_frame = ctk.CTkFrame(self.root, fg_color='transparent')
        main_frame.pack(fill='both', expand=True, padx=20, pady=15)

        # ===== 标题栏 =====
        header_frame = ctk.CTkFrame(main_frame, fg_color='transparent')
        header_frame.pack(fill='x', pady=(0, 15))

        ctk.CTkLabel(
            header_frame, text='英雄联盟违规标记查询',
            font=('Microsoft YaHei', 20, 'bold'),
            text_color=self.COLORS['gold']
        ).pack(side='left')

        self.time_label = ctk.CTkLabel(
            header_frame, text='', font=('Microsoft YaHei', 11),
            text_color=self.COLORS['text_secondary']
        )
        self.time_label.pack(side='right', padx=5)
        self._update_time()

        # 搜索框（右上角）
        search_frame = ctk.CTkFrame(header_frame, fg_color='transparent')
        search_frame.pack(side='right', padx=(0, 10))

        self.search_entry = ctk.CTkEntry(
            search_frame, placeholder_text='Riot ID（如 仿佛明月#123456）',
            width=170, height=32, font=('Microsoft YaHei', 11),
            fg_color=self.COLORS['card'], border_width=1,
            border_color=self.COLORS['card_hover_active']
        )
        self.search_entry.pack(side='left', padx=(0, 5))
        self.search_entry.bind('<Return>', lambda e: self._on_search_summoner())

        self.search_btn = ctk.CTkButton(
            search_frame, text='搜索', width=56, height=32,
            font=('Microsoft YaHei', 12), corner_radius=8,
            fg_color=self.COLORS['blue'], hover_color='#0288D1',
            command=self._on_search_summoner
        )
        self.search_btn.pack(side='left')

        # ===== 状态卡片 =====
        status_card = ctk.CTkFrame(main_frame, fg_color=self.COLORS['card'], corner_radius=10)
        status_card.pack(fill='x', pady=(0, 10))

        status_inner = ctk.CTkFrame(status_card, fg_color='transparent')
        status_inner.pack(fill='x', padx=15, pady=10)

        self.status_label = ctk.CTkLabel(
            status_inner, text='● 未启动', font=('Microsoft YaHei', 13, 'bold'),
            text_color=self.COLORS['text_secondary']
        )
        self.status_label.pack(side='left')

        self.account_label = ctk.CTkLabel(
            status_inner, text='账号: --', font=('Microsoft YaHei', 11),
            text_color=self.COLORS['text_secondary']
        )
        self.account_label.pack(side='right')

        self.phase_label = ctk.CTkLabel(
            status_inner, text='阶段: 未启动', font=('Microsoft YaHei', 11),
            text_color=self.COLORS['text_secondary']
        )
        self.phase_label.pack(side='right', padx=25)

        self.agent_label = ctk.CTkLabel(
            status_inner, text='Agent: 未接入', font=('Microsoft YaHei', 11),
            text_color=self.COLORS['text_secondary']
        )
        self.agent_label.pack(side='right', padx=25)

        # ===== 按钮栏 =====
        btn_frame = ctk.CTkFrame(main_frame, fg_color='transparent')
        btn_frame.pack(fill='x', pady=(0, 10))

        self.start_btn = ctk.CTkButton(
            btn_frame, text='启动工具', font=('Microsoft YaHei', 13, 'bold'),
            width=120, height=38, corner_radius=8,
            fg_color=self.COLORS['green'], hover_color='#388E3C',
            command=self.toggle_monitor
        )
        self.start_btn.pack(side='left', padx=(0, 10))

        self.refresh_btn = ctk.CTkButton(
            btn_frame, text='刷新信息', font=('Microsoft YaHei', 13),
            width=120, height=38, corner_radius=8,
            fg_color=self.COLORS['blue'], hover_color='#0288D1',
            command=self.refresh_manual
        )
        self.refresh_btn.pack(side='left')

        # ===== 队伍区域 =====
        self.teams_frame = ctk.CTkFrame(main_frame, fg_color='transparent')
        self.teams_frame.pack(fill='both', expand=True, pady=(0, 10))

        # 我方队伍
        self.my_team_card = ctk.CTkFrame(self.teams_frame, fg_color=self.COLORS['card'], corner_radius=10)
        self.my_team_card.pack(side='left', fill='both', expand=True, padx=(0, 5))

        my_team_header = ctk.CTkFrame(self.my_team_card, fg_color='transparent')
        my_team_header.pack(fill='x', padx=15, pady=(10, 2))
        self.my_team_label = ctk.CTkLabel(
            my_team_header, text='我方队伍', font=('Microsoft YaHei', 14, 'bold'),
            text_color=self.COLORS['blue']
        )
        self.my_team_label.pack(side='left')

        self.my_team_list = ctk.CTkScrollableFrame(
            self.my_team_card, fg_color='transparent', label_text=''
        )
        self.my_team_list.pack(fill='both', expand=True, padx=10, pady=(0, 10))

        # 敌方队伍
        self.enemy_team_card = ctk.CTkFrame(self.teams_frame, fg_color=self.COLORS['card'], corner_radius=10)
        self.enemy_team_card.pack(side='right', fill='both', expand=True, padx=(5, 0))

        enemy_team_header = ctk.CTkFrame(self.enemy_team_card, fg_color='transparent')
        enemy_team_header.pack(fill='x', padx=15, pady=(10, 2))
        self.enemy_team_label = ctk.CTkLabel(
            enemy_team_header, text='敌方队伍', font=('Microsoft YaHei', 14, 'bold'),
            text_color=self.COLORS['red']
        )
        self.enemy_team_label.pack(side='left')

        self.enemy_team_list = ctk.CTkScrollableFrame(
            self.enemy_team_card, fg_color='transparent', label_text=''
        )
        self.enemy_team_list.pack(fill='both', expand=True, padx=10, pady=(0, 10))

        # ===== 违规操作区 =====
        violation_card = ctk.CTkFrame(main_frame, fg_color=self.COLORS['card'], corner_radius=10)
        violation_card.pack(fill='x', pady=(0, 10))

        violation_inner = ctk.CTkFrame(violation_card, fg_color='transparent')
        violation_inner.pack(fill='x', padx=15, pady=10)

        self.query_violation_btn = ctk.CTkButton(
            violation_inner, text='查询全员违规', font=('Microsoft YaHei', 12),
            width=140, height=32, corner_radius=8,
            fg_color=self.COLORS['orange'], hover_color='#E65100',
            command=self._query_all_violations
        )
        self.query_violation_btn.pack(side='left', padx=(0, 10))

        self.report_violation_btn = ctk.CTkButton(
            violation_inner, text='发起违规标记', font=('Microsoft YaHei', 12),
            width=140, height=32, corner_radius=8,
            fg_color=self.COLORS['red'], hover_color='#C62828',
            command=self._on_report_violation_click
        )
        self.report_violation_btn.pack(side='left')

        self.violation_status_label = ctk.CTkLabel(
            violation_inner, text='', font=('Microsoft YaHei', 10),
            text_color=self.COLORS['text_secondary']
        )
        self.violation_status_label.pack(side='left', padx=15)

        # ===== 详情面板（可折叠） =====
        self.detail_card = ctk.CTkFrame(main_frame, fg_color=self.COLORS['card'], corner_radius=10)
        self.detail_card.pack(fill='x', pady=(0, 5))

        detail_header = ctk.CTkFrame(self.detail_card, fg_color='transparent')
        detail_header.pack(fill='x', padx=15, pady=(10, 2))

        self.detail_toggle_label = ctk.CTkLabel(
            detail_header, text='▶ 详细信息', font=('Microsoft YaHei', 14, 'bold'),
            text_color=self.COLORS['gold'], cursor='hand2'
        )
        self.detail_toggle_label.pack(side='left')
        self.detail_toggle_label.bind('<Button-1>', lambda e: self._toggle_detail())

        self.detail_text = ctk.CTkTextbox(
            self.detail_card, height=130, font=('Microsoft YaHei', 11),
            fg_color='transparent', text_color=self.COLORS['text_primary'],
            wrap='word'
        )
        # 默认收起：不 pack detail_text
        self.detail_text.configure(state='disabled')

        # ===== 安全提示 =====
        ctk.CTkLabel(
            main_frame, text='仅读取LCU本地接口数据，不操作游戏，无封号风险',
            font=('Microsoft YaHei', 9), text_color=self.COLORS['orange']
        ).pack(pady=(0, 0))

        # ===== 响应式布局：窗口缩放时切换队伍面板排列 =====
        self.root.bind('<Configure>', self._on_window_resize)

        self._clear_display()

    def _update_time(self):
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        self.time_label.configure(text=now)
        self.root.after(1000, self._update_time)

    # ===== 详情面板折叠/展开 =====

    def _toggle_detail(self):
        if self._detail_expanded:
            self.detail_text.pack_forget()
            self.detail_toggle_label.configure(text='▶ 详细信息')
            self._detail_expanded = False
        else:
            self.detail_text.pack(fill='x', padx=15, pady=(0, 10))
            self.detail_toggle_label.configure(text='▼ 详细信息')
            self._detail_expanded = True

    def _expand_detail(self):
        """选中玩家时自动展开详情"""
        if not self._detail_expanded:
            self.detail_text.pack(fill='x', padx=15, pady=(0, 10))
            self.detail_toggle_label.configure(text='▼ 详细信息')
            self._detail_expanded = True

    # ===== 状态指示器闪烁动画 =====

    def _start_blinking(self, color, text):
        # 先取消已有动画，避免 Matchmaking -> ReadyCheck 连续切换时叠加多条 after 链
        self._stop_blinking()
        self._blink_color = color
        self._blink_text = text
        self._blink_state = False
        self._blink_step()

    def _blink_step(self):
        if self._blink_state:
            self.status_label.configure(
                text=f'● {self._blink_text}', text_color=self._blink_color)
        else:
            self.status_label.configure(
                text=f'○ {self._blink_text}', text_color=self.COLORS['text_secondary'])
        self._blink_state = not self._blink_state
        self._blink_job = self.root.after(600, self._blink_step)

    def _stop_blinking(self):
        if self._blink_job:
            self.root.after_cancel(self._blink_job)
            self._blink_job = None

    # ===== 响应式布局 =====

    def _on_window_resize(self, event):
        """窗口缩放时根据宽度切换队伍面板排列方式（并排/堆叠）"""
        if event.widget is not self.root:
            return
        width = event.width
        # 窄窗口（<680px）时上下堆叠，宽窗口时左右并排
        if width < 680 and not self._teams_stacked:
            self._teams_stacked = True
            self.enemy_team_card.pack_forget()
            self.my_team_card.pack_forget()
            self.my_team_card.pack(side='top', fill='both', expand=True,
                                   padx=(0, 0), pady=(0, 5))
            self.enemy_team_card.pack(side='top', fill='both', expand=True,
                                      padx=(0, 0), pady=(5, 0))
        elif width >= 680 and self._teams_stacked:
            self._teams_stacked = False
            self.enemy_team_card.pack_forget()
            self.my_team_card.pack_forget()
            self.my_team_card.pack(side='left', fill='both', expand=True,
                                   padx=(0, 5))
            self.enemy_team_card.pack(side='right', fill='both', expand=True,
                                      padx=(5, 0))

    def _on_log(self, msg):
        """日志回调：写入滚动日志文件，开发模式下同时输出到控制台"""
        logging.getLogger('lol_match_query').info(msg)
        if sys.stdout is not None:
            print(f'[LOG] {msg}', flush=True)

    def _on_phase(self, phase):
        self.current_phase = phase
        description = self.PHASE_DESCRIPTIONS.get(phase, phase)
        def _update():
            self.phase_label.configure(text=f'阶段: {phase} - {description}')
            if phase == 'Matchmaking':
                self._start_blinking(self.COLORS['blue'], '寻找对局中...')
            elif phase == 'ReadyCheck':
                self._start_blinking(self.COLORS['green'], '请接受对局!')
            else:
                self._stop_blinking()
        self.root.after(0, _update)

    def _on_account(self, account_info):
        self.account_info = account_info
        parts = [f'大区: {account_info.get("region_name", "--")}']
        game_name = account_info.get('game_name', '')
        game_tag = account_info.get('game_tag', '')
        if game_name and game_tag:
            parts.append(f'{game_name}#{game_tag}')
        elif game_name:
            parts.append(game_name)
        puuid = account_info.get('puuid', '')
        if puuid:
            parts.append(f'PUUID: {puuid}')
        self.root.after(0, lambda: self.account_label.configure(text=' | '.join(parts)))

    def toggle_monitor(self):
        if self.is_running:
            self.stop_monitor()
        else:
            self.start_monitor()

    def start_monitor(self):
        self.is_running = True
        self.start_btn.configure(text='关闭工具', fg_color=self.COLORS['red'])
        self._start_blinking(self.COLORS['blue'], '正在连接...')

        if not self.match_service.start():
            self.is_running = False
            self._stop_blinking()
            self.start_btn.configure(text='启动工具', fg_color=self.COLORS['green'])
            self.status_label.configure(text='● 连接失败', text_color=self.COLORS['red'])
            messagebox.showwarning('提示', '未找到LeagueClient.exe进程\n请先启动英雄联盟客户端')

    def stop_monitor(self):
        self.is_running = False
        self._stop_blinking()
        self.match_service.stop()
        self.start_btn.configure(text='启动工具', fg_color=self.COLORS['green'])
        self.status_label.configure(text='● 已停止', text_color=self.COLORS['text_secondary'])

    def refresh_manual(self):
        if not self.is_running:
            messagebox.showwarning('提示', '请先点击"启动工具"')
            return

        self.refresh_btn.configure(state='disabled', text='刷新中')

        def _done():
            def _update():
                self.refresh_btn.configure(state='normal', text='刷新信息')
                self.violation_status_label.configure(text='刷新完成')
            try:
                self.root.after(0, _update)
            except Exception:
                pass

        # 刷新在后台线程执行，避免阻塞 UI；重复点击会被 MatchMonitorService 拒绝
        if not self.match_service.refresh(done_callback=_done):
            self.refresh_btn.configure(state='normal', text='刷新信息')
            self.violation_status_label.configure(text='刷新正在进行中，请稍候')

    def _on_match_data(self, data):
        self.root.after(0, lambda: self._update_match_data(data))

    def _on_clear(self):
        self.root.after(0, self._clear_display)

    def _clear_display(self):
        for widget in self.my_team_list.winfo_children():
            widget.destroy()
        for widget in self.enemy_team_list.winfo_children():
            widget.destroy()

        ctk.CTkLabel(
            self.my_team_list, text='等待对局...',
            font=('Microsoft YaHei', 12), text_color=self.COLORS['text_secondary']
        ).pack(pady=30)
        ctk.CTkLabel(
            self.enemy_team_list, text='等待对局...',
            font=('Microsoft YaHei', 12), text_color=self.COLORS['text_secondary']
        ).pack(pady=30)

        self._set_detail_text('')
        # 闪烁状态下不覆盖状态文字（由 _blink_step 控制）
        if not self._blink_job:
            self.status_label.configure(text='● 等待对局', text_color=self.COLORS['text_secondary'])
        self.violation_counts = {}
        self.violation_details = {}
        self.selected_player = None
        self._selected_card = None
        # 清空渲染缓存，避免进入下一阶段时增量更新错位（如BP只显示1张卡片）
        self._match_data_cache = None
        self.violation_status_label.configure(text='')
        # 收起详情面板
        if self._detail_expanded:
            self.detail_text.pack_forget()
            self.detail_toggle_label.configure(text='▶ 详细信息')
            self._detail_expanded = False

    def _update_match_data(self, match_data):
        stage = match_data.get('stage', '')
        if stage == 'champ_select':
            self._update_champ_select_partial(match_data)
        else:
            self._render_full(match_data)

    def _update_champ_select_partial(self, match_data):
        """BP阶段增量更新：英雄变化时就地更新卡片，避免整队闪烁"""
        # 首次进入BP，完整渲染
        if not self._match_data_cache:
            self._render_full(match_data)
            return

        # 查找自己
        cache = self._match_data_cache
        cached_self = cache.get('myself')
        new_self = match_data.get('myself')
        if not cached_self or not new_self:
            self._render_full(match_data)
            return

        new_my_team = match_data.get('my_team', [])
        old_my_team = cache.get('my_team', [])
        new_enemy_team = match_data.get('enemy_team', [])
        old_enemy_team = cache.get('enemy_team', [])

        old_my_order = [p.get('cell_id') for p in old_my_team]
        new_my_order = [p.get('cell_id') for p in new_my_team]
        old_enemy_order = [p.get('cell_id') for p in old_enemy_team]
        new_enemy_order = [p.get('cell_id') for p in new_enemy_team]

        # 成员数量或顺序变化：位置会错位，整队重建
        if (len(old_my_team) != len(new_my_team)
                or len(old_enemy_team) != len(new_enemy_team)
                or old_my_order != new_my_order
                or old_enemy_order != new_enemy_order):
            self._render_full(match_data)
            return

        # 防护：UI上已有卡片数量与数据不匹配（如缓存残留未完整渲染），整队重建
        if (len(self.my_team_list.pack_slaves()) != len(new_my_team)
                or len(self.enemy_team_list.pack_slaves()) != len(new_enemy_team)):
            self._render_full(match_data)
            return

        my_changed, my_selected = self._update_changed_cards(
            self.my_team_list, old_my_team, new_my_team)
        enemy_changed, enemy_selected = self._update_changed_cards(
            self.enemy_team_list, old_enemy_team, new_enemy_team)

        if not my_changed and not enemy_changed:
            # 数据无变化：就地刷新头像/英雄名（例如头像刚下载完成）
            self._refresh_team_cards(self.my_team_list)
            self._refresh_team_cards(self.enemy_team_list)
            self._preload_missing_icons(new_my_team + new_enemy_team)
            return

        self._match_data_cache = match_data

        # 选中卡片的数据也可能变化，刷新详情
        updated_selected = my_selected or enemy_selected
        if updated_selected:
            self._on_card_selected(*updated_selected)

        # 预下载新出现但尚未缓存的英雄头像（下载完成后就地更新，不闪烁）
        self._preload_missing_icons(new_my_team + new_enemy_team)

    def _preload_missing_icons(self, players):
        """预下载当前卡片上尚未缓存的英雄头像，完成后就地刷新"""
        missing = []
        seen = set()
        for player in players:
            cid = player.get('champion_id', 0)
            if cid and cid not in seen and not self.champion_data.get_champion_icon(cid, size=36):
                missing.append(cid)
                seen.add(cid)
        if not missing:
            return

        # 同一批缺失头像已经排过队：不要因为频繁的 session Update 反复重置定时器
        if missing == self._icon_preload_pending:
            return

        # 合并短时间内的多次英雄悬停/切换，避免频繁起下载线程
        if self._icon_preload_job:
            try:
                self.root.after_cancel(self._icon_preload_job)
            except Exception:
                pass
        self._icon_preload_pending = list(missing)
        self._icon_preload_job = self.root.after(
            200, lambda: self._start_icon_preload(missing))

    def _start_icon_preload(self, champion_ids):
        self._icon_preload_job = None
        if not self.champion_data.initialized:
            # 英雄数据尚未就绪，清空 pending，等初始化完成后再触发一次
            self._icon_preload_pending = []
            return
        self.champion_data.preload_icons_async(
            champion_ids,
            lambda: self.root.after(0, self._refresh_cards_if_needed))

    def _render_full(self, match_data):
        """完整渲染对局数据（不区分阶段，用于首次初始化或数据源切换时）"""
        for widget in self.my_team_list.winfo_children():
            widget.destroy()
        for widget in self.enemy_team_list.winfo_children():
            widget.destroy()

        if not match_data:
            ctk.CTkLabel(
                self.my_team_list, text='暂无对局数据',
                font=('Microsoft YaHei', 12), text_color=self.COLORS['text_secondary']
            ).pack(pady=30)
            ctk.CTkLabel(
                self.enemy_team_list, text='暂无对局数据',
                font=('Microsoft YaHei', 12), text_color=self.COLORS['text_secondary']
            ).pack(pady=30)
            return

        stage = match_data.get('stage', '')
        if stage == 'champ_select':
            self.status_label.configure(text='● 英雄选择中', text_color=self.COLORS['orange'])
        elif stage == 'in_game':
            self.status_label.configure(text='● 游戏中', text_color=self.COLORS['green'])

        my_team = match_data.get('my_team', [])
        enemy_team = match_data.get('enemy_team', [])

        if not my_team:
            ctk.CTkLabel(
                self.my_team_list, text='暂无队伍数据',
                font=('Microsoft YaHei', 12), text_color=self.COLORS['text_secondary']
            ).pack(pady=30)
        else:
            for idx, player in enumerate(my_team, 1):
                self._create_player_card(self.my_team_list, player, idx)

        if not enemy_team:
            ctk.CTkLabel(
                self.enemy_team_list, text='暂无敌方数据',
                font=('Microsoft YaHei', 12), text_color=self.COLORS['text_secondary']
            ).pack(pady=30)
        else:
            for idx, player in enumerate(enemy_team, 1):
                self._create_player_card(self.enemy_team_list, player, idx)

        self._match_data_cache = match_data

        # 后台预下载英雄头像，完成后刷新卡片显示头像
        self._preload_missing_icons(my_team + enemy_team)

    def _refresh_cards_if_needed(self):
        """英雄数据/头像就绪后刷新当前对局卡片"""
        if self._match_data_cache:
            if self._match_data_cache.get('stage') == 'champ_select':
                self._update_champ_select_partial(self._match_data_cache)
            else:
                self._update_match_data(self._match_data_cache)

    def _set_detail_text(self, text):
        self.detail_text.configure(state='normal')
        self.detail_text.delete('1.0', 'end')
        self.detail_text.insert('end', text)
        self.detail_text.configure(state='disabled')
