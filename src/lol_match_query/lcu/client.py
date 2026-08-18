"""LCU（League Client Update）本地接口客户端。

通过扫描英雄联盟客户端进程命令行参数获取端口与 token，
使用 HTTPS + WebSocket(WAMP) 订阅客户端 JSON API 事件，
监控选人/对局/结算阶段并解析对局玩家信息。
"""
import re
import time
import json
import ssl
import base64
import threading

import requests
import psutil
import urllib3
import websocket

urllib3.disable_warnings()


class LCUClient:
    # Riot region -> 友好名称
    REGION_MAP = {
        'CN': '国服', 'TENCENT': '国服', 'NA': '北美', 'EUW': '西欧', 'EUNE': '北欧及东欧',
        'KR': '韩国', 'BR': '巴西', 'LA': '拉丁美洲', 'OCE': '大洋洲',
        'RU': '俄罗斯', 'TR': '土耳其', 'JP': '日本', 'SG': '新加坡',
        'TH': '泰国', 'TW': '台湾', 'VN': '越南', 'ID': '印尼',
        'PBE': 'PBE测试服',
    }
    # platformId -> 国际服大区名称
    PLATFORM_ID_MAP = {
        'NA1': '北美', 'EUW1': '西欧', 'EUN1': '北欧及东欧', 'KR': '韩国',
        'BR1': '巴西', 'OC1': '大洋洲', 'RU': '俄罗斯', 'TR1': '土耳其',
        'JP1': '日本', 'PBE1': 'PBE测试服',
    }
    # 国服 platformId -> 大区名称（注意键名大小写：HN/WT/GX/CQ/EDU 为约定前缀）
    LOL_CN_PLATFORM_MAP = {
        # 电信区
        "HN1": "艾欧尼亚", "HN2": "祖安", "HN3": "诺克萨斯", "HN4": "班德尔城",
        "HN5": "皮尔特沃夫", "HN6": "战争学院", "HN7": "巨神峰", "HN8": "雷瑟守备",
        "HN9": "裁决之地", "HN10": "黑色玫瑰", "HN11": "暗影岛", "HN12": "钢铁烈阳",
        "HN13": "水晶之痕", "HN14": "均衡教派", "HN15": "影流", "HN16": "守望之海",
        "HN17": "征服之海", "HN18": "卡拉曼达", "HN19": "皮城警备",
        # 网通区
        "WT1": "比尔吉沃特", "WT2": "德玛西亚", "WT3": "弗雷尔卓德",
        "WT4": "无畏先锋", "WT5": "恕瑞玛", "WT6": "扭曲丛林", "WT7": "巨龙之巢",
        # 特殊大区
        "GX1": "男爵领域", "CQ100": "峡谷之巅", "EDU1": "教育网专区",
    }

    def __init__(self, log_callback=None, match_data_callback=None, clear_callback=None, phase_callback=None, region_callback=None):
        self.lcu_port = None
        self.lcu_token = None
        self.lcu_base_url = None
        self.running = False
        self.lock = threading.Lock()
        # 选人阶段会话未就绪时是否持续重试拉取（确保进入BP后召唤师立即显示）
        self._champ_select_retry = False
        self.current_summoner_puuid = None
        self.current_summoner_name = None
        self.log_callback = log_callback
        self.match_data_callback = match_data_callback
        self.clear_callback = clear_callback
        self.phase_callback = phase_callback
        self.region_callback = region_callback
        self.game_phase = None  # 哨兵值None表示未初始化，与游戏空闲阶段字符串'None'区分
        self.http_session = requests.Session()
        self.http_session.verify = False
        self.http_session.proxies = {}  # 禁用代理
        self.http_session.timeout = 15  # 增加超时时间
        # BP阶段缓存的玩家puuid（summoner_name/riot_id -> puuid），供进入游戏后补齐
        self.puuid_cache = {}
        # 对局中通过puuid反查到的Riot ID缓存（puuid -> riot_id），避免重复请求
        self.puuid_riot_cache = {}
        # BP阶段缓存的gameId，供进入游戏后使用
        self.cached_game_id = ''
        # 标记当前对局是否已通过战绩接口拉取过puuid
        self.match_history_fetched = False
        # BP阶段对局数据缓存，供战绩接口失败时兜底展示
        self.cached_bp_match_data = None
        # 标记对局结束阶段是否已重新拉取过完整战绩（含隐藏玩家）
        self.game_end_fetched = False
        # WebSocket相关
        self.ws = None
        self.ws_thread = None
        # gameflow-phase兜底轮询线程
        self.phase_poll_thread = None

        # 召唤师技能ID -> 中文名（ID 以 Data Dragon summoner.json 为准，勿凭印象填写）
        self.spell_cache = {
            1: '净化', 3: '虚弱', 4: '闪现', 6: '幽灵疾步', 7: '治疗术',
            11: '惩戒', 12: '传送', 13: '清晰术', 14: '引燃', 21: '屏障',
            30: '护驾！', 31: '魄罗投掷', 32: '标记', 39: '标记',
        }

    def _log(self, msg):
        if self.log_callback:
            self.log_callback(msg)

    def _send_match(self, data):
        if self.match_data_callback:
            self.match_data_callback(data)

    def _send_clear(self):
        if self.clear_callback:
            self.clear_callback()

    def _send_account(self, account_info):
        if self.region_callback:
            self.region_callback(account_info)

    def find_client(self, force_refresh=False):
        """查找LCU客户端进程"""
        if self.lcu_port and not force_refresh:
            return True

        target_names = ['leagueclientux.exe']

        for proc in psutil.process_iter(['name', 'cmdline']):
            try:
                proc_name = proc.name().lower()
                if proc_name in target_names:
                    cmdline = ' '.join(proc.cmdline())
                    # 只匹配 --app-port，不匹配 riotclient-app-port
                    port_match = re.search(r'--app-port=(\d+)', cmdline)
                    token_match = re.search(r'--remoting-auth-token=([^\s]+)', cmdline)

                    if port_match and token_match:
                        new_port = port_match.group(1)
                        new_token = token_match.group(1)
                        self.lcu_port = new_port
                        self.lcu_token = new_token
                        self.lcu_base_url = f'https://127.0.0.1:{self.lcu_port}'
                        self._get_current_summoner()
                        return True
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                continue
        return False

    def _fetch_gameflow_phase(self, silent=False):
        """通过HTTP获取当前游戏阶段（WS连接建立时补齐初始状态，静默模式供后台兜底轮询）"""
        try:
            url = f'{self.lcu_base_url}/lol-gameflow/v1/gameflow-phase'
            resp = self.http_session.get(
                url,
                auth=('riot', self.lcu_token),
                timeout=3
            )
            if resp.status_code == 200:
                phase = resp.text.strip().strip('"')
                if not silent:
                    self._log(f'初始游戏阶段: {phase}')
                self._handle_game_phase(phase)
            elif resp.status_code == 401:
                self._log('❌ 认证失败，token可能已过期')
        except Exception as e:
            if not silent:
                self._log(f'获取初始游戏阶段失败: {e}')

    def _handle_game_phase(self, phase):
        """处理游戏阶段变化"""
        if phase == self.game_phase:
            return
        self.game_phase = phase
        # 离开选人阶段时停止会话轮询，避免残留的重试线程
        if phase != 'ChampSelect':
            self._champ_select_retry = False
        if self.phase_callback:
            self.phase_callback(phase)

        if phase in ['None', 'Lobby', 'Matchmaking', 'ReadyCheck']:
            self.puuid_cache = {}
            self.puuid_riot_cache = {}
            self.cached_game_id = ''
            self.match_history_fetched = False
            self.cached_bp_match_data = None
            self.game_end_fetched = False
            self._send_clear()
        elif phase == 'ChampSelect':
            self._champ_select_retry = True
            self._send_clear()
            # 阶段刚切换时session可能尚未就绪，未成功则自动重试，确保召唤师立即显示
            self._check_champ_select(retry=True)
        elif phase in ['GameStart', 'InProgress', 'Reconnecting']:
            # 选人结束后不立即清空队伍栏：优先沿用BP缓存数据展示，避免读条/进图期间信息消失
            if self.cached_bp_match_data:
                self._send_fallback_match_data()
            else:
                self._send_clear()
            # 进入游戏后通过gameflow session获取全员信息并展示（战绩接口仅在对局结束阶段使用）
            if not self.match_history_fetched:
                self.match_history_fetched = True
                threading.Thread(
                    target=self._fetch_match_history_puuids,
                    daemon=True
                ).start()
        elif phase in ['PreEndOfGame', 'EndOfGame']:
            # 对局结束：战绩接口此时可获取完整信息（含隐藏玩家），重新拉取并更新展示
            if self.game_end_fetched:
                return
            self.game_end_fetched = True
            game_id = self.get_current_game_id() or self.cached_game_id
            if not game_id:
                self._log('对局结束，无gameId，跳过完整战绩拉取')
                return
            threading.Thread(
                target=self._fetch_match_history_at_game_end,
                args=(game_id,),
                daemon=True
            ).start()

    # ===== WebSocket 事件驱动 =====
    def _on_ws_open(self, ws):
        """WebSocket连接建立：订阅JSON API事件并补齐初始状态"""
        self._ws_reconnect_fail_count = 0  # 重置重连失败计数
        self._log('WebSocket已连接，订阅 OnJsonApiEvent ...')
        # 订阅所有 JSON API 事件，按 uri 在本地过滤
        ws.send(json.dumps([5, "OnJsonApiEvent"]))
        # 订阅后主动拉一次当前阶段，避免错过已存在的状态
        self._fetch_gameflow_phase()
        # 拉取当前登录大区
        self._get_region_info()

    def _on_ws_message(self, ws, message):
        """处理WS推送消息，格式: [type, "OnJsonApiEvent", {"data":..., "uri":..., "eventType":...}]"""
        try:
            msg = json.loads(message)
            if not isinstance(msg, list) or len(msg) < 3:
                return
            if msg[1] != "OnJsonApiEvent":
                return
            payload = msg[2]
            if not isinstance(payload, dict):
                return
            uri = payload.get("uri", "")
            data = payload.get("data")
            event_type = payload.get("eventType", "")
            self._dispatch_event(uri, data, event_type)
        except Exception as e:
            self._log(f'解析WS消息失败: {e}')

    def _on_ws_error(self, ws, error):
        self._log(f'WebSocket错误: {error}')

    def _on_ws_close(self, ws, close_status_code, close_msg):
        self._log(f'WebSocket关闭: code={close_status_code} msg={close_msg}')

    def _dispatch_event(self, uri, data, event_type):
        """根据 uri 分发WS推送事件"""
        if data is None:
            return
        if uri == "/lol-gameflow/v1/gameflow-phase":
            # data 直接是阶段字符串
            phase = data if isinstance(data, str) else str(data).strip().strip('"')
            self._log(f'WS推送游戏阶段: {phase} ({event_type})')
            self._handle_game_phase(phase)
        elif uri == "/lol-champ-select/v1/session":
            if event_type == "Delete":
                self._log('英雄选择会话已结束')
            elif event_type in ("Create", "Update") and isinstance(data, dict):
                self._handle_champ_select_data(data)
        elif uri == "/riotclient/region-locale":
            if isinstance(data, dict):
                self._handle_region_locale(data)
        # 其他事件忽略，避免日志噪声

    def _handle_champ_select_data(self, data):
        """直接使用WS推送的英雄选择会话数据进行解析"""
        try:
            my_team_data = data.get('myTeam', [])
            enemy_team_data = data.get('theirTeam', [])
            local_player_cell_id = data.get('localPlayerCellId', 0)
            result = self._parse_champ_select_data(my_team_data, enemy_team_data, local_player_cell_id)
            match_data = {
                'my_team': result['my_team'],
                'enemy_team': result['enemy_team'],
                'myself': result['myself'],
                'stage': 'champ_select'
            }
            # 缓存完整BP对局数据（含英雄），供进入游戏后立即展示
            self.cached_bp_match_data = match_data
            # 发给UI的数据剥离英雄信息：选人阶段英雄频繁更换，避免UI卡片反复重建闪烁
            self._send_match(self._strip_champion_info(match_data))
            # BP阶段缓存gameId，供进入游戏后违规举报使用
            game_id = self.get_current_game_id()
            if game_id and game_id != self.cached_game_id:
                self.cached_game_id = game_id
                self._log(f'BP阶段缓存对局ID: {game_id}')
        except Exception as e:
            self._log(f'解析英雄选择数据失败: {type(e).__name__}: {e}')

    def _strip_champion_info(self, match_data):
        """复制对局数据并清空英雄信息（选人阶段专用）

        选人阶段玩家频繁更换英雄，若把 champion_id 发给UI，
        卡片比较会被触发重建导致界面闪烁；进入游戏后由
        cached_bp_match_data（完整数据）或 gameflow 数据补齐英雄。
        """
        stripped = {
            'my_team': [],
            'enemy_team': [],
            'myself': None,
            'stage': match_data.get('stage', 'champ_select'),
        }
        for player in match_data.get('my_team', []):
            item = dict(player)
            item['champion_id'] = 0
            stripped['my_team'].append(item)
        for player in match_data.get('enemy_team', []):
            item = dict(player)
            item['champion_id'] = 0
            stripped['enemy_team'].append(item)
        myself = match_data.get('myself')
        if myself:
            item = dict(myself)
            item['champion_id'] = 0
            stripped['myself'] = item
        return stripped

    def _get_current_summoner(self):
        """获取当前召唤师信息"""
        try:
            resp = self.http_session.get(
                f'{self.lcu_base_url}/chat/v1/session',
                auth=('riot', self.lcu_token),
                timeout=3
            )
            if resp.status_code == 200:
                data = resp.json()
                self.current_summoner_puuid = data.get('puuid')
                game_name = data.get('game_name', '')
                game_tag = data.get('game_tag', '')
                self.current_summoner_name = f'{game_name}#{game_tag}' if game_name and game_tag else data.get('name', '未知')
        except Exception as e:
            self._log(f'获取召唤师信息失败: {e}')

    def _get_region_info(self):
        """获取当前登录大区信息（HTTP拉取，用于WS连接后补齐初始状态）"""
        try:
            resp = self.http_session.get(
                f'{self.lcu_base_url}/riotclient/region-locale',
                auth=('riot', self.lcu_token),
                timeout=3
            )
            if resp.status_code == 200:
                self._handle_region_locale(resp.json())
        except Exception as e:
            self._log(f'获取大区信息失败: {e}')

    def _handle_region_locale(self, data):
        """处理 region-locale 数据，获取大区和账号信息"""
        region_code = data.get('region', '')
        is_cn = region_code in ('CN', 'TENCENT')
        account_info = self._fetch_account_info()
        # 回填puuid到current_summoner_puuid，供对局中识别自己所在队伍
        if not self.current_summoner_puuid and account_info['puuid']:
            self.current_summoner_puuid = account_info['puuid']
        platform_id = account_info['platform_id']
        if platform_id:
            pid_upper = platform_id.upper()
            if is_cn:
                region_name = self.LOL_CN_PLATFORM_MAP.get(pid_upper, platform_id)
            else:
                region_name = self.PLATFORM_ID_MAP.get(pid_upper, platform_id)
        else:
            if is_cn:
                region_name = '国服'
            else:
                region_name = self.REGION_MAP.get(region_code, region_code or '未知')
            self._log(f'大区: {region_name} (region={region_code}, 未能获取具体大区的 platformId)')

        account_info['region_name'] = region_name
        account_info['region_code'] = region_code

        # 日志输出
        parts = [f'大区: {region_name}']
        if account_info['game_name'] and account_info['game_tag']:
            parts.append(f'RiotID: {account_info["game_name"]}#{account_info["game_tag"]}')
        elif account_info['game_name']:
            parts.append(f'游戏名: {account_info["game_name"]}')
        if account_info['puuid']:
            parts.append(f'PUUID: {account_info["puuid"]}')
        self._log(' | '.join(parts))

        self._send_account(account_info)

    def _fetch_account_info(self):
        """从 /lol-chat/v1/me 获取账号信息（platformId, gameName, gameTag, puuid）"""
        info = {'platform_id': '', 'game_name': '', 'game_tag': '', 'puuid': ''}
        try:
            resp = self.http_session.get(
                f'{self.lcu_base_url}/lol-chat/v1/me',
                auth=('riot', self.lcu_token),
                timeout=3
            )
            if resp.status_code == 200:
                data = resp.json()
                info['platform_id'] = data.get('platformId', '') or data.get('lol', {}).get('platformId', '')
                info['game_name'] = data.get('gameName', '')
                info['game_tag'] = data.get('gameTag', '')
                info['puuid'] = data.get('puuid', '')
        except Exception:
            pass
        return info

    def get_current_game_id(self):
        """获取当前对局的游戏ID（用于违规举报），从LCU gameflow session或缓存获取"""
        # 先从LCU gameflow session获取
        try:
            resp = self.http_session.get(
                f'{self.lcu_base_url}/lol-gameflow/v1/session',
                auth=('riot', self.lcu_token),
                timeout=3
            )
            if resp.status_code == 200:
                data = resp.json()
                # BP阶段: data["gameId"]（顶层），InProgress: data["gameData"]["gameId"]
                game_id = data.get('gameId') or data.get('gameData', {}).get('gameId', '')
                if game_id and str(game_id) != '0':
                    self.cached_game_id = str(game_id)
                    return str(game_id)
        except Exception as e:
            self._log(f'从LCU获取对局ID失败: {e}')
        # 使用BP阶段缓存的gameId
        if self.cached_game_id:
            return self.cached_game_id
        return ''

    def _get_spell_name(self, spell_id):
        """根据技能ID获取技能名称；0/空表示尚未选定，返回空字符串"""
        if not spell_id:
            return ''
        return self.spell_cache.get(spell_id, f'技能{spell_id}')

    def _get_position_name(self, position):
        """将位置缩写转换为中文名称"""
        position_map = {
            'top': '上单', 'jungle': '打野', 'mid': '中单',
            'bottom': 'ADC', 'support': '辅助', '': '未知'
        }
        return position_map.get(position, position)

    def _check_champ_select(self, retry=False):
        """检查英雄选择阶段；retry=True时会话未就绪会持续重试，直到成功或离开选人阶段"""
        # 重试调用仅允许在选人阶段内执行，避免离开BP后残留数据覆盖展示
        if retry and not (self._champ_select_retry and self.game_phase == 'ChampSelect'):
            return False
        try:
            url = f'{self.lcu_base_url}/lol-champ-select/v1/session'

            resp = self.http_session.get(
                url,
                auth=('riot', self.lcu_token),
                timeout=3
            )
            if resp.status_code == 200:
                data = resp.json()
                my_team_data = data.get('myTeam', [])
                enemy_team_data = data.get('theirTeam', [])
                local_player_cell_id = data.get('localPlayerCellId', 0)

                result = self._parse_champ_select_data(my_team_data, enemy_team_data, local_player_cell_id)
                match_data = {
                    'my_team': result['my_team'],
                    'enemy_team': result['enemy_team'],
                    'myself': result['myself'],
                    'stage': 'champ_select'
                }
                # 缓存完整BP对局数据（含英雄），供进入游戏后立即展示
                self.cached_bp_match_data = match_data
                # 发给UI的数据剥离英雄信息：选人阶段英雄频繁更换，避免UI卡片反复重建闪烁
                self._send_match(self._strip_champion_info(match_data))
                # BP阶段缓存gameId，供进入游戏后违规举报使用
                game_id = self.get_current_game_id()
                if game_id and game_id != self.cached_game_id:
                    self.cached_game_id = game_id
                    self._log(f'BP阶段缓存对局ID: {game_id}')
                return True
            elif not retry:
                self._log(f'英雄选择会话尚未就绪 (HTTP {resp.status_code})')
        except Exception as e:
            if not retry:
                self._log(f'获取英雄选择数据失败: {type(e).__name__}: {str(e)}')

        # 会话未就绪：延迟重试，直到拉取成功或离开选人阶段
        if retry and self._champ_select_retry and self.game_phase == 'ChampSelect':
            timer = threading.Timer(0.5, self._check_champ_select, args=(True,))
            timer.daemon = True
            timer.start()
        return False

    def _parse_champ_select_data(self, my_team_data, enemy_team_data, local_player_cell_id=0):
        """解析英雄选择阶段的完整队伍数据"""
        my_team = []
        enemy_team = []
        myself = None

        for player in my_team_data:
            player_info = self._build_player_info(player, local_player_cell_id, '队友', 'ORDER')
            if player_info['role'] == '自己':
                myself = player_info
            my_team.append(player_info)

        for player in enemy_team_data:
            player_info = self._build_player_info(player, local_player_cell_id, '敌方', 'CHAOS')
            enemy_team.append(player_info)

        # 缓存BP阶段全部玩家的puuid，供进入游戏后战绩接口补齐使用
        self.puuid_cache = {}
        for p in my_team + enemy_team:
            puuid = p.get('puuid', '')
            if not puuid:
                continue
            name = p.get('summoner_name', '')
            if name and name != '未知':
                self.puuid_cache[name] = puuid
            riot_id = p.get('riot_id', '')
            if riot_id and riot_id != '未知':
                self.puuid_cache[riot_id] = puuid

        return {'my_team': my_team, 'enemy_team': enemy_team, 'myself': myself}

    def _build_player_info(self, player, local_player_cell_id=0, default_role='队友', team='ORDER'):
        """构建单个玩家信息"""
        game_name = player.get('gameName', '')
        tag_line = player.get('tagLine', '')
        champion_id = player.get('championId', 0)
        puuid = player.get('puuid', '')
        position = self._get_position_name(player.get('assignedPosition', ''))
        spell1 = self._get_spell_name(player.get('spell1Id', 0))
        spell2 = self._get_spell_name(player.get('spell2Id', 0))
        cell_id = player.get('cellId', 0)
        # 选人阶段仅以 nameVisibilityType=HIDDEN 判断隐藏玩家（能拿到puuid即可识别，不算隐藏）
        is_hidden = player.get('nameVisibilityType') == 'HIDDEN'

        riot_id = f'{game_name}#{tag_line}' if game_name else '未知'
        summoner_name = game_name or '未知'

        is_me = False
        if cell_id == local_player_cell_id:
            is_me = True
        elif self.current_summoner_puuid and puuid == self.current_summoner_puuid:
            is_me = True
        elif self.current_summoner_name and riot_id == self.current_summoner_name:
            is_me = True

        return {
            'summoner_name': summoner_name,
            'riot_id': riot_id,
            'champion_id': champion_id,
            'puuid': puuid,
            'role': '自己' if is_me else default_role,
            'position': position,
            'spell1': spell1,
            'spell2': spell2,
            'cell_id': cell_id,
            'is_hidden': is_hidden,
            'team': team
        }

    def _fetch_match_history_puuids(self, game_id=None):
        """获取对局全体玩家信息并展示（对局中仅使用gameflow session数据源，战绩接口只在结束阶段使用）"""
        if not game_id:
            game_id = self.get_current_game_id() or self.cached_game_id

        # 进入地图加载阶段后先等待一段时间再查询session，避免触发LCU限流
        self._log('进入游戏加载阶段，等待5秒后再查询lol-gameflow/v1/session（避免触发LCU限流）...')
        for _ in range(5):
            if self.game_phase not in ('GameStart', 'InProgress', 'Reconnecting'):
                self._log('对局已结束，放弃等待')
                return
            time.sleep(1.0)

        # 数据源1: gameflow session的gameData（读条/加载阶段直接轮询该接口，进图后即可提取10人数据）
        if self._try_gameflow_participants(game_id):
            return

        # gameData未就绪：读条阶段直接轮询session接口（每3秒检测，最多90秒）
        self._log('读条阶段gameData未就绪，轮询lol-gameflow/v1/session（每3秒检测，最多90秒）...')
        for wait_round in range(30):
            if self.game_phase not in ('GameStart', 'InProgress', 'Reconnecting'):
                self._log('对局已结束，放弃等待')
                return
            time.sleep(3.0)
            if self._try_gameflow_participants(game_id):
                self._log(f'等待{(wait_round + 1) * 3}s后gameData就绪，已展示对局信息')
                return

        # 等待超时仍未就绪，用BP缓存兜底
        self._log('等待超时，gameData仍未就绪，使用BP缓存兜底')
        if self.cached_bp_match_data:
            self._send_fallback_match_data()
        else:
            self._send_clear()

    def _try_gameflow_participants(self, game_id):
        """从gameflow session的gameData中提取对局玩家信息（数据源1，立即可用）"""
        try:
            resp = self.http_session.get(
                f'{self.lcu_base_url}/lol-gameflow/v1/session',
                auth=('riot', self.lcu_token),
                timeout=5
            )
            if resp.status_code != 200:
                self._log(f'gameflow session返回 {resp.status_code}')
                return False

            data = resp.json()
            game_data = data.get('gameData', {})

            participants = game_data.get('participants', [])
            team_one = game_data.get('teamOne', [])
            team_two = game_data.get('teamTwo', [])
            self._log(f'gameData: participants={len(participants)}, teamOne={len(team_one)}, teamTwo={len(team_two)}')

            # 优先使用 participants 数组
            if participants and isinstance(participants, list):
                sample = participants[0]
                sample_keys = list(sample.keys()) if isinstance(sample, dict) else str(type(sample))
                self._log(f'participant首条keys: {sample_keys}')

                match_data = self._build_match_data_from_gameflow(participants, None)
                if match_data and (match_data['my_team'] or match_data['enemy_team']):
                    total = len(match_data['my_team']) + len(match_data['enemy_team'])
                    unnamed = sum(1 for p in match_data['my_team'] + match_data['enemy_team']
                                  if p.get('summoner_name', '') in ('', '未知'))
                    self._log(f'gameflow成功提取 {total} 名玩家信息，其中无名玩家 {unnamed} 名')
                    # participants名字缺失时改用teamOne/teamTwo（其summonerName字段可靠）
                    if unnamed > 0 and (team_one or team_two):
                        self._log('participants名字缺失，改用teamOne/teamTwo重建')
                        match_data = self._build_match_data_from_gameflow(team_one, team_two)
                        if match_data and (match_data['my_team'] or match_data['enemy_team']):
                            total = len(match_data['my_team']) + len(match_data['enemy_team'])
                            self._log(f'gameflow(teamOne/Two)成功提取 {total} 名玩家信息')
                    self._send_match(match_data)
                    return True

            # 尝试 teamOne/teamTwo
            if team_one or team_two:
                if team_one:
                    sample = team_one[0]
                    if isinstance(sample, dict):
                        sample_keys = list(sample.keys())
                        self._log(f'teamOne首条keys: {sample_keys}')
                        # 输出实际值用于调试名称为空的问题
                        self._log(f'teamOne首条值: summonerName="{sample.get("summonerName", "")}", '
                                  f'summonerInternalName="{sample.get("summonerInternalName", "")}", '
                                  f'puuid="{sample.get("puuid", "")[:16]}..."')

                match_data = self._build_match_data_from_gameflow(team_one, team_two)
                if match_data and (match_data['my_team'] or match_data['enemy_team']):
                    total = len(match_data['my_team']) + len(match_data['enemy_team'])
                    self._log(f'gameflow(teamOne/Two)成功提取 {total} 名玩家信息')
                    self._send_match(match_data)
                    return True

            self._log('gameData中未找到可用的玩家数据')
            return False
        except Exception as e:
            self._log(f'从gameflow提取玩家信息失败: {type(e).__name__}: {e}')
            return False

    def search_summoner(self, riot_id):
        """通过完整 Riot ID 搜索召唤师信息

        使用 GET /lol-summoner/v1/alias/lookup?gameName=xxx&tagLine=yyy
        将 Riot ID 拆分为 gameName 和 tagLine 分别传递

        Args:
            riot_id: 完整的 Riot ID（如 游戏名#TAG）

        Returns:
            dict: 召唤师信息，失败返回 None
        """
        if not self.lcu_base_url or not self.lcu_token:
            self._log('LCU 未连接，无法搜索召唤师')
            return None

        query = riot_id.strip()
        # 移除换行符、回车符等控制字符（用户复制粘贴时可能带入）
        query = re.sub(r'[\r\n\t]+', '', query)

        # 拆分 Riot ID
        if '#' not in query:
            self._log(f'搜索失败: 输入不是有效的 Riot ID 格式: {query}')
            return None
        game_name, tag_line = query.split('#', 1)
        game_name = game_name.strip()
        tag_line = tag_line.strip()
        if not game_name or not tag_line:
            self._log(f'搜索失败: 游戏名或 TAG 为空: gameName={game_name}, tagLine={tag_line}')
            return None

        url = f'{self.lcu_base_url}/lol-summoner/v1/alias/lookup'
        params = {'gameName': game_name, 'tagLine': tag_line}

        try:
            self._log(f'搜索召唤师: gameName={game_name}, tagLine={tag_line}')
            resp = self.http_session.get(
                url,
                params=params,
                auth=('riot', self.lcu_token),
                timeout=10
            )
            self._log(f'搜索响应: HTTP {resp.status_code}, url={resp.url}, body={resp.text[:500]}')

            if resp.status_code == 200:
                data = resp.json()
                self._log(f'返回数据: {data}')
                if isinstance(data, list):
                    return data[0] if data else None
                return data if data else None
        except Exception as e:
            self._log(f'搜索召唤师异常: {type(e).__name__}: {e}')

        return None

    def _lookup_riot_id_by_puuid(self, puuid):
        """通过puuid调用LCU summoner接口反查Riot ID（对局中teamOne/teamTwo名字为空时使用，带缓存）"""
        if not puuid:
            return ''
        cached = self.puuid_riot_cache.get(puuid)
        if cached:
            return cached
        try:
            resp = self.http_session.get(
                f'{self.lcu_base_url}/lol-summoner/v2/summoners/puuid/{puuid}',
                auth=('riot', self.lcu_token),
                timeout=5
            )
            if resp.status_code == 200:
                data = resp.json()
                game_name = (data.get('gameName') or data.get('displayName') or '').strip()
                tag_line = (data.get('tagLine') or '').strip()
                if game_name and tag_line:
                    riot_id = f'{game_name}#{tag_line}'
                elif game_name:
                    riot_id = game_name
                else:
                    riot_id = ''
                if riot_id:
                    self.puuid_riot_cache[puuid] = riot_id
                    self._log(f'puuid反查Riot ID成功: {riot_id}')
                else:
                    self._log(f'puuid反查结果为空: {puuid[:16]}...')
                return riot_id
            self._log(f'puuid反查Riot ID失败: 状态码={resp.status_code} (puuid={puuid[:16]}...)')
        except Exception as e:
            self._log(f'puuid反查Riot ID异常: {type(e).__name__}: {e}')
        return ''

    def _build_match_data_from_gameflow(self, team_one_players, team_two_players=None):
        """从gameflow session构建对局信息

        Args:
            team_one_players: teamOne数组或participants数组（ORDER方）
            team_two_players: teamTwo数组（CHAOS方），为None时用teamId判断队伍
        """
        all_players = []
        myself = None
        current_puuid = self.current_summoner_puuid

        # 构建 puuid -> name 反查表（从BP缓存）
        puuid_to_name = {}
        for cached_name, cached_puuid in self.puuid_cache.items():
            if not cached_puuid:
                continue
            # 优先保留 Riot ID 格式（含#）的名称
            if cached_puuid not in puuid_to_name or '#' in cached_name:
                puuid_to_name[cached_puuid] = cached_name

        def _parse_player(p, team):
            nonlocal myself
            if not isinstance(p, dict):
                return None

            puuid = p.get('puuid', '')
            champion_id = p.get('championId', 0)

            # 优先使用 gameName + gameTag (Riot ID 新格式)，summonerName 在 gameflow session 中为空，不使用
            game_name = p.get('gameName', '').strip()
            game_tag = p.get('gameTag', '').strip()

            summoner_name = ''
            riot_id = ''
            if game_name and game_tag:
                riot_id = f'{game_name}#{game_tag}'
                summoner_name = riot_id
            elif game_name:
                summoner_name = game_name
                riot_id = game_name

            # 名字为空或不是Riot ID格式时，通过puuid反查Riot ID
            if puuid and '#' not in summoner_name:
                if puuid in puuid_to_name and '#' in puuid_to_name[puuid]:
                    summoner_name = puuid_to_name[puuid]
                    riot_id = puuid_to_name[puuid]
                else:
                    lookup_name = self._lookup_riot_id_by_puuid(puuid)
                    if lookup_name:
                        summoner_name = lookup_name
                        riot_id = lookup_name

            if not summoner_name:
                summoner_name = '未知'
                if not riot_id:
                    riot_id = '未知'

            is_me = (puuid and puuid == current_puuid)

            if not puuid:
                puuid = (self.puuid_cache.get(summoner_name, '') or
                         self.puuid_cache.get(riot_id, ''))

            if puuid:
                if summoner_name and summoner_name != '未知':
                    self.puuid_cache[summoner_name] = puuid
                if riot_id and riot_id != '未知':
                    self.puuid_cache[riot_id] = puuid

            # 能拿到puuid即可识别该玩家，不算隐藏玩家；仅当既无名又无puuid时才显示为隐藏
            is_hidden = summoner_name == '未知' and not puuid

            player_info = {
                'summoner_name': summoner_name,
                'riot_id': riot_id,
                'champion_id': champion_id,
                'champion_name': f'英雄{champion_id}',
                'puuid': puuid,
                'team': team,
                'role': '自己' if is_me else '',
                'is_hidden': is_hidden
            }

            if is_me:
                myself = player_info

            return player_info

        if team_two_players is not None:
            for p in team_one_players:
                info = _parse_player(p, 'ORDER')
                if info:
                    all_players.append(info)
            for p in team_two_players:
                info = _parse_player(p, 'CHAOS')
                if info:
                    all_players.append(info)
        else:
            for p in team_one_players:
                if not isinstance(p, dict):
                    continue
                team_id = p.get('teamId', 100)
                team = 'ORDER' if team_id == 100 else 'CHAOS'
                info = _parse_player(p, team)
                if info:
                    all_players.append(info)

        # 根据myself所在队伍分组：自己所在队=my_team，另一队=enemy_team
        if myself:
            my_team_side = myself['team']
        else:
            # myself未识别时，优先通过当前召唤师puuid精确匹配gameflow玩家所在队伍
            account_puuid = self.current_summoner_puuid or ''
            matched_side = ''
            for p in all_players:
                if p.get('puuid') and p['puuid'] == account_puuid:
                    matched_side = p['team']
                    break
            if matched_side:
                my_team_side = matched_side
            else:
                # 兜底：BP缓存myself的team（仅当BP阶段已知我方队伍方向）
                bp_myself = (self.cached_bp_match_data or {}).get('myself')
                my_team_side = (bp_myself or {}).get('team', 'ORDER')
        my_team = [p for p in all_players if p['team'] == my_team_side]
        enemy_team = [p for p in all_players if p['team'] != my_team_side]

        for p in my_team:
            if p['role'] != '自己':
                p['role'] = '队友'
        for p in enemy_team:
            p['role'] = '敌方'

        return {
            'my_team': my_team,
            'enemy_team': enemy_team,
            'myself': myself,
            'stage': 'in_game'
        }

    def _request_match_history_once(self, game_id):
        """单次请求战绩接口，返回解析后的JSON数据或None"""
        try:
            resp = self.http_session.get(
                f'{self.lcu_base_url}/lol-match-history/v1/games/{game_id}',
                auth=('riot', self.lcu_token),
                timeout=5
            )
            if resp.status_code == 200:
                data = resp.json()
                self._log(f'[战绩接口] /lol-match-history/v1/games/{game_id} 状态码=200, 顶层字段: {list(data.keys())}')
                return data
            self._log(f'[战绩接口] /lol-match-history/v1/games/{game_id} 状态码={resp.status_code}, 响应: {resp.text[:500]}')
            return None
        except Exception as e:
            self._log(f'[战绩接口] /lol-match-history/v1/games/{game_id} 请求异常: {type(e).__name__}: {e}')
            return None

    def _process_match_history_data(self, data, game_id):
        """处理战绩数据：缓存puuid、构建对局信息并发送UI，成功返回True"""
        if not isinstance(data, dict):
            return False

        participants = data.get('participants', [])
        identities = data.get('participantIdentities', [])

        if not participants:
            self._log('participants为空，战绩可能尚未生成')
            return False

        # 从 participantIdentities 收集 participantId -> (summonerName, puuid)
        id_map = {}
        for pi in identities:
            pid = pi.get('participantId', 0)
            player = pi.get('player', {})
            puuid = player.get('puuid', '')
            name = player.get('summonerName', '') or player.get('gameName', '')
            if puuid and name:
                self.puuid_cache[name] = puuid
            if pid:
                id_map[pid] = {'puuid': puuid, 'name': name}

        # 从 participants 补充 summonerName -> puuid 映射
        count = 0
        for p in participants:
            puuid = p.get('puuid', '')
            name = p.get('summonerName', '') or p.get('gameName', '')
            pid = p.get('participantId', 0)
            if not puuid and pid in id_map:
                puuid = id_map[pid].get('puuid', '')
            if not name and pid in id_map:
                name = id_map[pid].get('name', '')
            if puuid and name:
                self.puuid_cache[name] = puuid
                count += 1
            riot_name = p.get('riotIdGameName', '')
            riot_tag = p.get('riotIdTagline', '')
            if puuid and riot_name:
                riot_id_str = f'{riot_name}#{riot_tag}' if riot_tag else riot_name
                self.puuid_cache[riot_id_str] = puuid

        if count > 0:
            self._log(f'战绩接口成功获取 {count} 名玩家信息 (gameId={game_id})')
            match_data = self._build_match_data_from_history(data)
            if match_data:
                self._send_match(match_data)
            return True

        # 200但count=0，输出调试信息
        sample = participants[0]
        sample_keys = list(sample.keys()) if isinstance(sample, dict) else str(type(sample))
        self._log(f'participants非空但count=0，首条keys: {sample_keys}')
        return False

    def _fetch_match_history_at_game_end(self, game_id):
        """对局结束时重新请求战绩接口，获取完整对局信息（此时隐藏玩家信息可见）"""
        self._log(f'对局结束，重新获取完整战绩 (gameId={game_id})')
        # 战绩接口在结束时可能延迟生成，最多重试4次，每次间隔2秒
        for attempt in range(4):
            data = self._request_match_history_once(game_id)
            if data and self._process_match_history_data(data, game_id):
                self._log('对局结束，战绩信息已更新（含隐藏玩家信息）')
                return True
            if attempt < 3:
                self._log(f'对局结束获取战绩: 第{attempt + 1}/4次未就绪，2秒后重试')
                time.sleep(2.0)
        self._log('对局结束后战绩接口未就绪，保留原展示')
        return False

    def _build_match_data_from_history(self, history_data):
        """从战绩接口数据构建对局信息（替代Live Client Data）"""
        all_players = []
        myself = None

        current_puuid = self.current_summoner_puuid

        id_map = {}
        for pi in history_data.get('participantIdentities', []):
            pid = pi.get('participantId', 0)
            id_map[pid] = pi.get('player', {})

        for p in history_data.get('participants', []):
            pid = p.get('participantId', 0)
            player = id_map.get(pid, {})

            summoner_name = (player.get('summonerName', '') or player.get('gameName', '') or '未知').strip()
            puuid = player.get('puuid', '') or p.get('puuid', '')
            champion_id = p.get('championId', 0)
            team_id = p.get('teamId', 100)
            team = 'ORDER' if team_id == 100 else 'CHAOS'

            game_name = player.get('gameName', '') or p.get('riotIdGameName', '')
            tag_line = player.get('tagLine', '') or p.get('riotIdTagline', '')
            if game_name and tag_line:
                riot_id = f'{game_name}#{tag_line}'
                # 召唤师名字优先使用 Riot ID 完整格式显示（gameName#tagLine）
                summoner_name = riot_id
            elif game_name:
                riot_id = game_name
            else:
                riot_id = summoner_name

            is_me = (puuid and puuid == current_puuid)

            if not puuid:
                puuid = self.puuid_cache.get(summoner_name, '') or self.puuid_cache.get(riot_id, '')

            player_info = {
                'summoner_name': summoner_name,
                'riot_id': riot_id,
                'champion_id': champion_id,
                'champion_name': f'英雄{champion_id}',
                'puuid': puuid,
                'team': team,
                'role': '自己' if is_me else '',
                'is_hidden': False
            }

            if is_me:
                myself = player_info

            all_players.append(player_info)

        # 根据myself所在队伍分组：自己所在队=my_team，另一队=enemy_team
        if myself:
            my_team_side = myself['team']
        else:
            # myself未识别时，优先通过当前召唤师puuid精确匹配gameflow玩家所在队伍
            account_puuid = self.current_summoner_puuid or ''
            matched_side = ''
            for p in all_players:
                if p.get('puuid') and p['puuid'] == account_puuid:
                    matched_side = p['team']
                    break
            if matched_side:
                my_team_side = matched_side
            else:
                # 兜底：BP缓存myself的team（仅当BP阶段已知我方队伍方向）
                bp_myself = (self.cached_bp_match_data or {}).get('myself')
                my_team_side = (bp_myself or {}).get('team', 'ORDER')
        my_team = [p for p in all_players if p['team'] == my_team_side]
        enemy_team = [p for p in all_players if p['team'] != my_team_side]

        for p in my_team:
            if p['role'] != '自己':
                p['role'] = '队友'
        for p in enemy_team:
            p['role'] = '敌方'

        return {
            'my_team': my_team,
            'enemy_team': enemy_team,
            'myself': myself,
            'stage': 'in_game'
        }

    def _send_fallback_match_data(self):
        """战绩接口失败时，使用BP缓存数据兜底展示（标记为in_game阶段）"""
        if not self.cached_bp_match_data:
            return
        # 复制BP数据，将stage改为in_game以正确显示UI状态
        fallback = {
            'my_team': self.cached_bp_match_data.get('my_team', []),
            'enemy_team': self.cached_bp_match_data.get('enemy_team', []),
            'myself': self.cached_bp_match_data.get('myself'),
            'stage': 'in_game'
        }
        self._send_match(fallback)

    def start(self):
        with self.lock:
            if self.running:
                return False
            self.running = True

        if not self.find_client():
            self.running = False
            return False

        # WebSocket 事件驱动线程（替代 gameflow 轮询）
        self.ws_thread = threading.Thread(target=self._ws_loop, daemon=True)
        self.ws_thread.start()
        # gameflow-phase兜底轮询：WS推送可能丢失，确保能检测到进入游戏阶段
        if not self.phase_poll_thread or not self.phase_poll_thread.is_alive():
            self.phase_poll_thread = threading.Thread(target=self._phase_poll_loop, daemon=True)
            self.phase_poll_thread.start()
        return True

    def stop(self):
        with self.lock:
            self.running = False
        self._champ_select_retry = False
        if self.ws is not None:
            try:
                self.ws.close()
            except Exception:
                pass

    def _ws_loop(self):
        """WebSocket 主循环，带自动重连"""
        while self.running:
            if not self.lcu_port:
                if not self.find_client():
                    self._log('未找到LCU进程，等待重试...')
                    time.sleep(2)
                    continue

            # WAMP 子协议 + Basic Auth
            auth = base64.b64encode(f'riot:{self.lcu_token}'.encode()).decode()
            url = f'wss://127.0.0.1:{self.lcu_port}/'
            self._log(f'正在连接WebSocket: {url}')

            self.ws = websocket.WebSocketApp(
                url,
                subprotocols=["wamp"],
                header=[f"Authorization: Basic {auth}"],
                on_open=self._on_ws_open,
                on_message=self._on_ws_message,
                on_error=self._on_ws_error,
                on_close=self._on_ws_close,
            )
            try:
                # 关闭证书校验（LCU使用自签名证书）
                self.ws.run_forever(
                    sslopt={"cert_reqs": ssl.CERT_NONE},
                    ping_interval=30,
                    ping_timeout=10,
                )
            except Exception as e:
                self._log(f'WebSocket运行异常: {e}')

            self.ws = None
            if not self.running:
                break
            self._log('WebSocket断开，2秒后重连...')
            # 先尝试用现有连接信息重连，失败后再重新查找LCU进程
            self.game_phase = None  # 重置为哨兵值，确保重连后首次阶段推送能触发更新
            time.sleep(2)
            # 若连续3次重连失败，则重置连接信息重新查找LCU进程
            self._ws_reconnect_fail_count = getattr(self, '_ws_reconnect_fail_count', 0) + 1
            if self._ws_reconnect_fail_count >= 3:
                self._ws_reconnect_fail_count = 0
                self.lcu_port = None
                self.lcu_token = None
                self.lcu_base_url = None

    def _phase_poll_loop(self):
        """兜底轮询gameflow-phase：WS推送可能丢失（尤其选人→进游戏过渡期），
        定时HTTP拉取阶段确保不错过进入游戏的转折（gameflow-phase接口极轻量，不会触发限流）"""
        while self.running:
            try:
                if self.lcu_port and self.lcu_base_url:
                    self._fetch_gameflow_phase(silent=True)
            except Exception:
                pass
            time.sleep(5.0)
