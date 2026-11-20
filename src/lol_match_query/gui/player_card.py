"""玩家卡片相关 UI 逻辑（Mixin）。

包括玩家卡片创建、悬停高亮、选中详情展示与违规明细后台查询。
"""
import threading

import customtkinter as ctk

from .utils import format_violation_detail


class PlayerCardMixin:
    """为 MatchQueryGUI 提供玩家卡片相关方法的混入类"""

    # ===== 卡片悬停高亮 =====

    def _on_card_enter(self, card):
        """鼠标进入卡片：高亮（选中状态除外）"""
        if card is not self._selected_card:
            card.configure(fg_color=self.COLORS['card_hover_active'])

    def _on_card_leave(self, card):
        """鼠标离开卡片：恢复（选中状态除外）"""
        if card is not self._selected_card:
            # 检查鼠标是否仍在卡片范围内（移动到子控件时会触发 Leave）
            x, y = self.root.winfo_pointerxy()
            cx1 = card.winfo_rootx()
            cy1 = card.winfo_rooty()
            cx2 = cx1 + card.winfo_width()
            cy2 = cy1 + card.winfo_height()
            if not (cx1 <= x <= cx2 and cy1 <= y <= cy2):
                card.configure(fg_color=self.COLORS['card_hover'])

    def _create_player_card(self, parent, player, idx, before=None):
        """在队伍滚动区内创建一张玩家卡片（含英雄头像），before 指定 pack 插入位置"""
        puuid = player.get('puuid', '')
        is_self = player.get('role') == '自己' or (
            puuid and self.account_info and puuid == self.account_info.get('puuid', '')
        )
        is_hidden = player.get('is_hidden', False)
        role = player.get('role', '')
        violation_count = self.violation_counts.get(puuid, 0) if puuid else 0
        position = player.get('position', '')
        champion_id = player.get('champion_id', 0)

        # 边框色：自己=金，违规=红，其他=普通
        if is_self:
            border_color = self.COLORS['gold']
            border_w = 2
        elif violation_count > 0:
            border_color = self.COLORS['red']
            border_w = 2
        else:
            border_color = self.COLORS['card_hover']
            border_w = 1

        card = ctk.CTkFrame(
            parent, fg_color=self.COLORS['card_hover'], corner_radius=8,
            border_width=border_w, border_color=border_color
        )
        card.pack(fill='x', pady=3, before=before)
        card._champion_id = champion_id
        card._icon_label = None
        card._placeholder_label = None
        # 记录基础边框（自己=金/违规=红/普通），取消选中时还原
        card._base_border_color = border_color
        card._base_border_width = border_w

        content = ctk.CTkFrame(card, fg_color='transparent')
        content.pack(fill='x', padx=8, pady=6)

        # 英雄头像（已下载则显示，否则占位）
        icon = self.champion_data.get_champion_icon(champion_id, size=36)
        if icon:
            icon_label = ctk.CTkLabel(content, image=icon, text='', width=40)
            icon_label.pack(side='left', padx=(0, 6))
            card._icon_label = icon_label
        else:
            placeholder = ctk.CTkLabel(
                content, text='?', width=40,
                font=('Microsoft YaHei', 16, 'bold'),
                text_color=self.COLORS['text_secondary']
            )
            placeholder.pack(side='left', padx=(0, 6))
            card._placeholder_label = placeholder

        # 右侧信息区（两行）
        info_frame = ctk.CTkFrame(content, fg_color='transparent')
        info_frame.pack(side='left', fill='x', expand=True)

        # 第一行：序号 + 位置 + 角色标签 + 名字 + 违规标记
        row1 = ctk.CTkFrame(info_frame, fg_color='transparent')
        row1.pack(fill='x')

        ctk.CTkLabel(
            row1, text=str(idx), width=14,
            font=('Microsoft YaHei', 11), text_color=self.COLORS['text_secondary']
        ).pack(side='left')

        if position:
            pos_color = self.COLORS['blue'] if role != '敌方' else self.COLORS['red']
            ctk.CTkLabel(
                row1, text=position, width=42,
                font=('Microsoft YaHei', 10, 'bold'), text_color=pos_color
            ).pack(side='left', padx=(2, 0))

        role_tag = '【自己】' if is_self else ('【队友】' if role == '队友' else '【敌方】')
        role_color = self.COLORS['gold'] if is_self else self.COLORS['text_secondary']
        ctk.CTkLabel(
            row1, text=role_tag, width=46,
            font=('Microsoft YaHei', 10), text_color=role_color
        ).pack(side='left', padx=(2, 0))

        # 名字 + 英雄名
        display_name = '隐藏玩家' if is_hidden else player.get('riot_id', '未知')
        if is_hidden:
            name_color = self.COLORS['text_secondary']
        elif violation_count > 0:
            name_color = self.COLORS['red']
        else:
            name_color = self.COLORS['text_primary']

        champion_cn = self.champion_data.get_champion_name(champion_id)
        if champion_cn and not is_hidden:
            display_text = f'{champion_cn} · {display_name}'
        else:
            display_text = display_name

        ctk.CTkLabel(
            row1, text=display_text,
            font=('Microsoft YaHei', 12, 'bold' if is_self else 'normal'),
            text_color=name_color
        ).pack(side='left', padx=(2, 0))

        if violation_count > 0:
            ctk.CTkLabel(
                row1, text=f'违规{violation_count}次',
                font=('Microsoft YaHei', 10, 'bold'),
                text_color=self.COLORS['red']
            ).pack(side='right')

        # 第二行：召唤师技能
        spell1 = player.get('spell1', '')
        spell2 = player.get('spell2', '')
        spell_parts = [s for s in [spell1, spell2] if s]
        if spell_parts:
            ctk.CTkLabel(
                info_frame, text=' / '.join(spell_parts),
                font=('Microsoft YaHei', 9),
                text_color=self.COLORS['text_secondary']
            ).pack(fill='x', pady=(1, 0))

        # 点击选择 + 悬停高亮（递归绑定到所有子控件）
        def on_click(e=None):
            self._on_card_selected(player, card)

        def _bind_recursive(w):
            w.bind('<Button-1>', on_click)
            w.bind('<Enter>', lambda e: self._on_card_enter(card))
            w.bind('<Leave>', lambda e: self._on_card_leave(card))
            for child in w.winfo_children():
                _bind_recursive(child)
        _bind_recursive(content)

        return card

    def _get_champion_display(self, champion_id):
        """生成英雄显示文本；champion_id为0表示选人阶段未展示英雄"""
        champion_cn = self.champion_data.get_champion_name(champion_id)
        if champion_cn:
            return f'{champion_cn} (ID:{champion_id})'
        if champion_id:
            return f'ID:{champion_id}'
        return '未选定（选人阶段不显示英雄）'

    def _build_detail_lines(self, player, puuid):
        """构建玩家详情文本行（点击卡片与违规明细刷新共用）"""
        champion_display = self._get_champion_display(player.get('champion_id', 0))
        team = player.get('team', '')
        team_part = f'  |  队伍: {team}' if team else ''
        return [
            f'召唤师: {player.get("riot_id", "未知")}',
            f'英雄: {champion_display}',
            f'位置: {player.get("position", "未知")}',
            f'技能: {player.get("spell1", "")} / {player.get("spell2", "")}',
            f'身份: {player.get("role", "")}{team_part}',
            f'状态: {"隐藏" if player.get("is_hidden") else "可见"}  |  PUUID: {puuid or "无"}',
        ]

    def _on_card_selected(self, player, card):
        """玩家卡片被点击：高亮选中并更新详情"""
        if self._selected_card and self._selected_card.winfo_exists():
            # 还原上一张卡片的背景与基础边框（自己=金/违规=红/普通）
            self._selected_card.configure(
                fg_color=self.COLORS['card_hover'],
                border_color=getattr(
                    self._selected_card, '_base_border_color', self.COLORS['card_hover']),
                border_width=getattr(self._selected_card, '_base_border_width', 1),
            )
        # 选中态：蓝调背景 + 蓝色加粗边框，与悬停态明显区分
        card.configure(
            fg_color=self.COLORS['selected'],
            border_color=self.COLORS['blue'],
            border_width=2,
        )
        self._selected_card = card
        self.selected_player = player

        # 自动展开详情面板，点击后立即可见选中反馈
        self._expand_detail()

        puuid = player.get('puuid', '')
        violation_count = self.violation_counts.get(puuid, 0) if puuid else 0

        detail_lines = self._build_detail_lines(player, puuid)

        # 若已有缓存的违规详情，直接显示；否则先显示总数，后台查询明细
        cached = self.violation_details.get(puuid) if puuid else None
        if cached:
            detail_lines.append(format_violation_detail(cached))
        else:
            detail_lines.append(f'违规次数: {violation_count}')
            if puuid:
                detail_lines.append('违规明细: 查询中...')

        self._set_detail_text('\n'.join(detail_lines))

        # 后台查询违规明细（仅当未缓存时）
        if puuid and not cached:
            self._query_violation_detail(puuid, player)

    def _query_violation_detail(self, puuid, player):
        """后台查询单个玩家违规明细 GET /lol/violation/count"""
        platform_id = self.account_info.get('platform_id', '')
        if not platform_id:
            return

        # 避免重复查询（按 puuid 去重，支持同时查询多个不同玩家）
        if puuid in self._violation_detail_querying:
            return
        self._violation_detail_querying.add(puuid)

        def _query():
            result = self.violation_client.query_count(puuid, platform_id)

            def _update():
                self._violation_detail_querying.discard(puuid)
                if result.get('code') == 200 and result.get('data') is not None:
                    data = result['data']
                    self.violation_details[puuid] = data

                    # 仅当选中的玩家仍是同一人时才更新详情面板
                    current = self.selected_player
                    if current and current.get('puuid') == puuid:
                        detail_lines = self._build_detail_lines(current, puuid)
                        detail_lines.append(format_violation_detail(data))
                        self._set_detail_text('\n'.join(detail_lines))
                else:
                    # 查询失败，更新提示
                    current = self.selected_player
                    if current and current.get('puuid') == puuid:
                        msg = result.get('message', '查询失败')
                        self._set_detail_text(
                            f'违规明细查询失败: {msg}')

            self.root.after(0, _update)

        threading.Thread(target=_query, daemon=True).start()
