"""对话框相关 UI 逻辑（Mixin）。

包括召唤师搜索、违规查询结果、违规类型选择与举报提交、全员违规批量查询。
"""
import threading
from tkinter import messagebox

import customtkinter as ctk

from ..services.violation import ViolationClient


class DialogMixin:
    """为 MatchQueryGUI 提供对话框相关方法的混入类"""

    # ===== 召唤师搜索功能 =====

    def _on_search_summoner(self):
        """点击搜索按钮或回车：通过完整 Riot ID 搜索召唤师"""
        query = self.search_entry.get().strip()
        if not query:
            messagebox.showwarning('提示', '请输入完整的 Riot ID\n格式：游戏名#TAG（如 仿佛明月#123456）')
            return

        # 校验 Riot ID 格式：必须包含 # 且两部分都不为空
        if '#' not in query:
            messagebox.showwarning('提示', '请输入完整的 Riot ID\n格式：游戏名#TAG（如 仿佛明月#123456）')
            return
        game_name, tag_line = query.split('#', 1)
        if not game_name.strip() or not tag_line.strip():
            messagebox.showwarning('提示', 'Riot ID 格式不正确\n游戏名和 TAG 都不能为空')
            return

        if not self.is_running:
            messagebox.showwarning('提示', '请先点击"启动工具"')
            return

        # 禁用搜索按钮，显示查询中状态
        self.search_btn.configure(state='disabled', text='搜索中')
        self.search_entry.configure(state='disabled')

        def _do_search():
            result = self.lcu.search_summoner(query)

            def _update():
                self.search_btn.configure(state='normal', text='搜索')
                self.search_entry.configure(state='normal')
                if result:
                    self._show_search_result_dialog(result, query)
                else:
                    messagebox.showwarning('搜索失败', f'未找到召唤师: {query}')

            self.root.after(0, _update)

        threading.Thread(target=_do_search, daemon=True).start()

    def _show_search_result_dialog(self, data, query):
        """显示召唤师搜索结果对话框"""
        dialog = ctk.CTkToplevel(self.root)
        dialog.title('召唤师搜索结果')
        dialog.geometry('460x420')
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.configure(fg_color=self.COLORS['bg'])

        # 标题
        ctk.CTkLabel(
            dialog, text='召唤师搜索结果',
            font=('Microsoft YaHei', 16, 'bold'),
            text_color=self.COLORS['gold']
        ).pack(pady=(15, 5))

        # 信息卡片
        info_card = ctk.CTkFrame(dialog, fg_color=self.COLORS['card'], corner_radius=10)
        info_card.pack(fill='x', padx=20, pady=(5, 10))

        # 提取字段 - 适配 /lol-summoner/v1/alias/lookup 接口返回格式
        alias = data.get('alias', {})
        game_name = alias.get('gameName', '') or ''
        tag_line = alias.get('tagLine', '') or ''
        puuid = data.get('puuid', '') or ''

        # 兼容旧格式（/lol-summoner/v1/summoners/by-name 等）
        if not game_name:
            game_name = data.get('displayName', '') or data.get('internalName', '') or '未知'
        if not tag_line:
            tag_line = data.get('tagLine', '') or ''

        # Riot ID 格式：游戏名#标签
        riot_id = f'{game_name}#{tag_line}' if game_name and tag_line else game_name or '未知'

        # 大区信息
        platform_id = self.account_info.get('platform_id', '')
        platform_name = self.account_info.get('platform_name', '') or platform_id or '未知'

        rows = [
            ('Riot ID', riot_id),
            ('游戏名', game_name) if game_name else None,
            ('标签', tag_line) if tag_line else None,
            ('PUUID', puuid[:32] + '...' if len(puuid) > 32 else puuid) if puuid else None,
            ('所在大区', platform_name),
        ]

        for row in rows:
            if row is None:
                continue
            label_text, value_text = row
            row_frame = ctk.CTkFrame(info_card, fg_color='transparent')
            row_frame.pack(fill='x', padx=15, pady=3)
            ctk.CTkLabel(
                row_frame, text=label_text, width=90, anchor='w',
                font=('Microsoft YaHei', 11),
                text_color=self.COLORS['text_secondary']
            ).pack(side='left')
            ctk.CTkLabel(
                row_frame, text=value_text, anchor='w',
                font=('Microsoft YaHei', 11, 'bold'),
                text_color=self.COLORS['text_primary']
            ).pack(side='left', fill='x', expand=True)

        # 操作按钮区
        btn_frame = ctk.CTkFrame(dialog, fg_color='transparent')
        btn_frame.pack(pady=15)

        def on_query_violation():
            """查询该召唤师违规明细"""
            if not puuid:
                messagebox.showwarning('提示', '该召唤师无 PUUID，无法查询违规')
                return
            dialog.destroy()
            self._search_and_show_violation(puuid, riot_id)

        def on_close():
            dialog.destroy()

        ctk.CTkButton(
            btn_frame, text='查询违规明细', font=('Microsoft YaHei', 12),
            width=120, height=34, corner_radius=8,
            fg_color=self.COLORS['orange'], hover_color='#E65100',
            command=on_query_violation
        ).pack(side='left', padx=5)

        ctk.CTkButton(
            btn_frame, text='关闭', font=('Microsoft YaHei', 12),
            width=80, height=34, corner_radius=8,
            fg_color=self.COLORS['card_hover'], hover_color=self.COLORS['selected'],
            command=on_close
        ).pack(side='left', padx=5)

    def _search_and_show_violation(self, puuid, summoner_name):
        """从搜索结果查询违规明细并显示"""
        platform_id = self.account_info.get('platform_id', '')
        if not platform_id:
            messagebox.showwarning('提示', '未能获取大区信息')
            return

        # 创建结果对话框
        dialog = ctk.CTkToplevel(self.root)
        dialog.title('违规查询结果')
        dialog.geometry('460x400')
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.configure(fg_color=self.COLORS['bg'])

        ctk.CTkLabel(
            dialog, text=f'{summoner_name} 的违规信息',
            font=('Microsoft YaHei', 16, 'bold'),
            text_color=self.COLORS['gold']
        ).pack(pady=(15, 5))

        loading_label = ctk.CTkLabel(
            dialog, text='查询中...',
            font=('Microsoft YaHei', 12),
            text_color=self.COLORS['text_secondary']
        )
        loading_label.pack(pady=20)

        def _query():
            result = self.violation_client.query_count(puuid, platform_id)

            def _update():
                loading_label.destroy()
                if result.get('code') == 200 and result.get('data'):
                    data = result['data']
                    # 调试：打印返回的数据结构
                    self._on_log(f'违规查询返回数据: {data}')

                    # 兼容不同格式：data 可能是 dict 或 int
                    if isinstance(data, dict):
                        total = data.get('totalCount', 0)
                        type_counts = data.get('typeCounts', [])
                    elif isinstance(data, int):
                        # data 直接是总次数
                        total = data
                        type_counts = []
                    else:
                        total = 0
                        type_counts = []

                    # 总次数
                    total_color = self.COLORS['red'] if total > 0 else self.COLORS['green']
                    ctk.CTkLabel(
                        dialog, text=f'总违规次数: {total}',
                        font=('Microsoft YaHei', 14, 'bold'),
                        text_color=total_color
                    ).pack(pady=(5, 10))

                    # 明细列表
                    detail_card = ctk.CTkFrame(dialog, fg_color=self.COLORS['card'], corner_radius=10)
                    detail_card.pack(fill='both', expand=True, padx=20, pady=(0, 10))

                    scroll = ctk.CTkScrollableFrame(detail_card, fg_color='transparent')
                    scroll.pack(fill='both', expand=True, padx=10, pady=10)

                    for i, tc in enumerate(type_counts):
                        tc_type = tc.get('typeName', '未知')
                        tc_count = tc.get('count', 0)
                        row = i // 2
                        col = i % 2
                        count_color = self.COLORS['red'] if tc_count > 0 else self.COLORS['text_secondary']
                        ctk.CTkLabel(
                            scroll, text=f'{tc_type}: {tc_count}次',
                            font=('Microsoft YaHei', 11),
                            text_color=count_color
                        ).grid(row=row, column=col, padx=8, pady=3, sticky='w')
                    scroll.grid_columnconfigure(0, weight=1)
                    scroll.grid_columnconfigure(1, weight=1)
                else:
                    msg = result.get('message', '查询失败')
                    ctk.CTkLabel(
                        dialog, text=f'查询失败: {msg}',
                        font=('Microsoft YaHei', 12),
                        text_color=self.COLORS['red']
                    ).pack(pady=20)

                ctk.CTkButton(
                    dialog, text='关闭', font=('Microsoft YaHei', 12),
                    width=80, height=34, corner_radius=8,
                    fg_color=self.COLORS['card_hover'], hover_color=self.COLORS['selected'],
                    command=dialog.destroy
                ).pack(pady=10)

            self.root.after(0, _update)

        threading.Thread(target=_query, daemon=True).start()

    # ===== 违规标记功能 =====

    def _on_report_violation_click(self):
        """点击发起违规标记按钮"""
        if not self.selected_player:
            messagebox.showwarning('提示', '请先在队伍列表中选择一名玩家')
            return
        # 不能标记自己：通过角色和puuid双重判断
        if self.selected_player['role'] == '自己':
            messagebox.showwarning('提示', '不能对自己发起违规标记')
            return
        my_puuid = self.account_info.get('puuid', '')
        selected_puuid = self.selected_player.get('puuid', '')
        if my_puuid and selected_puuid and my_puuid == selected_puuid:
            messagebox.showwarning('提示', '不能对自己发起违规标记')
            return
        if not selected_puuid:
            messagebox.showwarning('提示', '该玩家信息不完整（缺少puuid），无法标记')
            return
        self._show_violation_dialog(self.selected_player)

    def _show_violation_dialog(self, player):
        """显示违规类型选择对话框"""
        dialog = ctk.CTkToplevel(self.root)
        dialog.title('选择违规类型')
        dialog.geometry('420x560')
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.configure(fg_color=self.COLORS['bg'])

        ctk.CTkLabel(
            dialog,
            text=f'请选择对玩家 [{player["riot_id"]}] 的违规类型：',
            font=('Microsoft YaHei', 13), text_color=self.COLORS['text_primary'],
            wraplength=380, justify='left'
        ).pack(pady=(15, 10), padx=15)

        scroll_frame = ctk.CTkScrollableFrame(dialog, fg_color='transparent')
        scroll_frame.pack(fill='both', expand=True, padx=20, pady=5)

        state = {'selected': None, 'buttons': []}

        def make_select(code, name, btn):
            def select():
                state['selected'] = (code, name)
                for b in state['buttons']:
                    b.configure(fg_color=self.COLORS['card_hover'],
                                text_color=self.COLORS['text_primary'])
                btn.configure(fg_color=self.COLORS['red'], text_color='white')
            return select

        for i, (code, name) in enumerate(ViolationClient.VIOLATION_TYPES.items()):
            row = i // 2
            col = i % 2
            btn = ctk.CTkButton(
                scroll_frame, text=f'{code}. {name}',
                font=('Microsoft YaHei', 12), height=36,
                fg_color=self.COLORS['card_hover'],
                text_color=self.COLORS['text_primary'],
                hover_color=self.COLORS['selected'], corner_radius=8,
            )
            btn.configure(command=make_select(code, name, btn))
            btn.grid(row=row, column=col, padx=5, pady=3, sticky='ew')
            state['buttons'].append(btn)
            scroll_frame.grid_columnconfigure(col, weight=1)

        # 默认选中第一个
        first_code = list(ViolationClient.VIOLATION_TYPES.keys())[0]
        state['selected'] = (first_code, ViolationClient.VIOLATION_TYPES[first_code])
        state['buttons'][0].configure(fg_color=self.COLORS['red'], text_color='white')

        btn_frame = ctk.CTkFrame(dialog, fg_color='transparent')
        btn_frame.pack(pady=15)

        def on_confirm():
            if state['selected']:
                dialog.destroy()
                self._do_report_violation(player, state['selected'][0])

        ctk.CTkButton(
            btn_frame, text='确认标记', font=('Microsoft YaHei', 12, 'bold'),
            width=110, height=36, corner_radius=8,
            fg_color=self.COLORS['red'], hover_color='#C62828',
            command=on_confirm
        ).pack(side='left', padx=10)

        ctk.CTkButton(
            btn_frame, text='取消', font=('Microsoft YaHei', 12),
            width=110, height=36, corner_radius=8,
            fg_color=self.COLORS['card_hover'], hover_color=self.COLORS['selected'],
            command=dialog.destroy
        ).pack(side='left', padx=10)

    def _do_report_violation(self, player, violation_type):
        """在后台线程中执行违规举报"""
        def _report():
            game_id = self.lcu.get_current_game_id()
            reporter_puuid = self.account_info.get('puuid', '')
            platform_id = self.account_info.get('platform_id', '')
            platform_name = self.account_info.get('region_name', '')
            reported_puuid = player.get('puuid', '')

            if not reporter_puuid:
                self.root.after(0, lambda: messagebox.showerror(
                    '错误', '未能获取当前账号puuid，请确保客户端已连接'))
                return
            if not platform_id:
                self.root.after(0, lambda: messagebox.showerror(
                    '错误', '未能获取大区信息，请确保客户端已连接'))
                return
            if not reported_puuid:
                self.root.after(0, lambda: messagebox.showerror(
                    '错误', '该玩家信息不完整（缺少puuid），无法标记'))
                return

            # 安全兜底：不能标记自己
            if reporter_puuid == reported_puuid:
                self.root.after(0, lambda: messagebox.showwarning(
                    '提示', '不能对自己发起违规标记'))
                return
            if not game_id:
                self.root.after(0, lambda: messagebox.showerror(
                    '错误', '未能获取对局ID，请确保正在对局中'))
                return

            violation_name = ViolationClient.VIOLATION_TYPES.get(violation_type, '未知')
            self.root.after(0, lambda: self.violation_status_label.configure(
                text=f'正在提交违规标记({violation_name})...'))
            self._on_log(f'正在举报 {player["riot_id"]} 违规类型: {violation_name}')

            result = self.violation_client.report_violation(
                reporter_puuid, platform_id, platform_name,
                game_id, reported_puuid, violation_type
            )

            def _show_result():
                code = result.get('code')
                msg = result.get('message', '')
                if code == 200:
                    self.violation_status_label.configure(
                        text=f'已标记 {player["riot_id"]} - {violation_name}')
                    messagebox.showinfo(
                        '成功',
                        f'已成功标记 {player["riot_id"]} 的违规行为：{violation_name}')
                else:
                    self.violation_status_label.configure(text=f'标记失败: {msg}')
                    messagebox.showerror('标记失败', msg)

            self.root.after(0, _show_result)

        threading.Thread(target=_report, daemon=True).start()

    def _query_all_violations(self):
        """批量查询当前对局全体玩家违规状态"""
        if not self._match_data_cache:
            messagebox.showwarning('提示', '当前无对局数据，请等待对局开始')
            return

        platform_id = self.account_info.get('platform_id', '')
        if not platform_id:
            messagebox.showwarning('提示', '未能获取大区信息，请确保客户端已连接')
            return

        match_data = self._match_data_cache
        my_team = match_data.get('my_team', [])
        enemy_team = match_data.get('enemy_team', [])

        players = []
        for player in my_team + enemy_team:
            puuid = player.get('puuid', '')
            if puuid:
                players.append({'platformId': platform_id, 'puuid': puuid})

        if not players:
            messagebox.showwarning('提示', '当前对局无可查询的玩家信息')
            return

        def _query():
            self.root.after(0, lambda: self.violation_status_label.configure(
                text='正在查询全员违规状态...'))
            self._on_log(f'批量查询 {len(players)} 名玩家的违规状态...')

            result = self.violation_client.batch_query_status(players)

            def _update():
                code = result.get('code')
                if code == 200:
                    data = result.get('data', [])
                    self.violation_counts = {}
                    flagged_count = 0
                    for item in data:
                        puuid = item.get('puuid', '')
                        count = item.get('violationCount', 0)
                        self.violation_counts[puuid] = count
                        if count > 0:
                            flagged_count += 1

                    # 刷新队伍列表显示违规标注（强制完整渲染，避免BP增量更新遗漏违规标记）
                    if self._match_data_cache:
                        self._render_full(self._match_data_cache)

                    self.violation_status_label.configure(
                        text=f'查询完成: {flagged_count}/{len(data)} 人有违规记录')
                    self._on_log(
                        f'违规查询完成: {flagged_count}/{len(data)} 人有违规记录')
                else:
                    msg = result.get('message', '查询失败')
                    self.violation_status_label.configure(text=f'查询失败: {msg}')
                    messagebox.showerror('查询失败', msg)

            self.root.after(0, _update)

        threading.Thread(target=_query, daemon=True).start()
