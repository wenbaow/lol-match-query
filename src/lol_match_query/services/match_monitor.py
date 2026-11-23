"""对局监控服务：阶段状态机、缓存与事件源。

职责：
- 消费 LCU 传输层的原始事件（gameflow / champ-select / region-locale）
- 维护对局阶段、BP 缓存、puuid 缓存、gameId、手动刷新等状态
- 向 GUI / Agent 暴露少量方法和事件，不暴露内部字段

线程模型：
- 事件在产生它们的线程上同步分发；GUI 订阅者需自行 ``root.after`` 回主线程。
- 对外状态只在服务内部读写；事件与 snapshot 返回副本。
"""
import copy
import logging
import re
import threading
import time

from agentquay import agent_tool

from ..lcu.events import (
    CHAMP_SELECT_URI,
    GAMEFLOW_PHASE_URI,
    REGION_LOCALE_URI,
    WS_OPEN_EVENT,
)
from ..lcu.parser import (
    build_match_data_from_gameflow,
    build_match_data_from_history,
    collect_puuid_cache,
    parse_champ_select,
)
from ..lcu.regions import get_region_name


class MatchMonitorService:
    """对局监控服务：唯一持有对局状态的对象"""

    EVENTS = frozenset({
        'phase_changed',      # phase
        'match_updated',      # match_data（副本）
        'display_cleared',    # 无参数
        'account_updated',    # account_info（副本）
        'log',                # message
    })

    def __init__(self, log_callback=None, lcu_client=None):
        self._subscribers = {}
        self._subscriber_lock = threading.Lock()
        self._log_callback = log_callback

        if lcu_client is None:
            # 延迟导入：测试可注入 FakeTransport，避免依赖 requests/psutil/websocket
            from ..lcu.client import LCUClient
            lcu_client = LCUClient(log_callback=self._log)
        self._lcu = lcu_client

        # ===== 生命周期 =====
        self._running = False
        self._lock = threading.Lock()
        self._run_token = 0

        # ===== 对局状态 / 缓存 =====
        self._game_phase = None
        self._champ_select_retry = False
        self._current_summoner_puuid = None
        self._current_summoner_name = None
        self._puuid_cache = {}
        self._puuid_riot_cache = {}
        self._cached_game_id = ''
        self._match_history_fetched = False
        self._cached_bp_match_data = None
        self._game_end_fetched = False
        self._game_id_fetch_ts = 0.0
        self._refresh_lock = threading.Lock()
        self._refresh_in_progress = False

        # ===== 对外快照 =====
        self._last_match_data = None
        self._account_info = {}

    # ===== 事件订阅 =====

    def subscribe(self, event, handler):
        """订阅事件；事件在产生事件的线程同步分发"""
        if event not in self.EVENTS:
            raise ValueError(f'未知事件: {event}')
        with self._subscriber_lock:
            self._subscribers.setdefault(event, []).append(handler)
        return handler

    def _emit(self, event, *args):
        with self._subscriber_lock:
            handlers = list(self._subscribers.get(event, ()))
        for handler in handlers:
            try:
                handler(*args)
            except Exception:
                # 不用 self._log，避免日志事件处理器异常时递归
                logging.getLogger('lol_match_query').exception(
                    '事件处理器异常: %s', event)

    def snapshot(self):
        """返回当前状态副本（供晚订阅/重连后恢复）"""
        return {
            'running': self._running,
            'phase': self._game_phase,
            'match_data': copy.deepcopy(self._last_match_data),
            'account': copy.deepcopy(self._account_info),
            'game_id': self._cached_game_id,
        }

    # ===== 日志与发送 =====

    def _log(self, msg, debug=False):
        if debug and not logging.getLogger('lol_match_query').isEnabledFor(logging.DEBUG):
            return
        if self._log_callback:
            self._log_callback(msg)
        else:
            self._emit('log', msg)

    def _send_match(self, data):
        self._last_match_data = copy.deepcopy(data)
        self._emit('match_updated', copy.deepcopy(data))

    def _send_clear(self):
        self._last_match_data = None
        self._emit('display_cleared')

    def _send_account(self, account_info):
        self._account_info = dict(account_info)
        self._emit('account_updated', dict(account_info))

    # ===== 生命周期 =====

    def _is_run_active(self, token=None):
        if not self._running:
            return False
        return token is None or token == self._run_token

    def start(self):
        with self._lock:
            if self._running:
                return True
            self._running = True
            self._run_token += 1
            # 重置阶段哨兵与单局标记：确保重启后即使仍处于同一阶段也会重新推送数据
            self._game_phase = None
            self._champ_select_retry = False
            self._match_history_fetched = False
            self._game_end_fetched = False
            self._game_id_fetch_ts = 0.0

        try:
            started = self._lcu.start(self._on_lcu_event)
        except Exception as e:
            self._log(f'启动 LCU 传输层失败: {type(e).__name__}: {e}')
            started = False

        if not started:
            with self._lock:
                self._running = False
                self._run_token += 1
            return False

        # 不依赖 WS 是否成功打开，先补齐当前召唤师信息
        self._get_current_summoner()
        return True

    def stop(self):
        with self._lock:
            self._running = False
            self._run_token += 1
            self._game_phase = None
        self._champ_select_retry = False
        try:
            self._lcu.stop()
        except Exception as e:
            self._log(f'停止 LCU 传输层失败: {type(e).__name__}: {e}')

    # ===== 传输层事件入口 =====

    def _on_lcu_event(self, uri, data, event_type):
        if uri == WS_OPEN_EVENT:
            if not self._is_run_active():
                return
            reconnect = bool(isinstance(data, dict) and data.get('reconnect'))
            if reconnect:
                self._game_phase = None
            if reconnect or not self._current_summoner_puuid:
                self._get_current_summoner()
            self._fetch_gameflow_phase()
            self._get_region_info()
            return

        if not self._is_run_active() or data is None:
            return

        if uri == GAMEFLOW_PHASE_URI:
            phase = data if isinstance(data, str) else str(data).strip().strip('"')
            self._log(f'游戏阶段: {phase} ({event_type})', debug=(event_type == 'Poll'))
            self._handle_game_phase(phase)
        elif uri == CHAMP_SELECT_URI:
            if event_type == 'Delete':
                self._log('英雄选择会话已结束')
            elif event_type in ('Create', 'Update') and isinstance(data, dict):
                self._handle_champ_select_data(data)
        elif uri == REGION_LOCALE_URI:
            if isinstance(data, dict):
                self._handle_region_locale(data)

    def _fetch_gameflow_phase(self):
        """WS 连接建立/重连时补齐当前阶段"""
        try:
            resp = self._lcu.get(GAMEFLOW_PHASE_URI, timeout=3)
            if resp.status_code == 200:
                phase = resp.text.strip().strip('"')
                self._log(f'初始游戏阶段: {phase}')
                if not self._is_run_active():
                    return
                self._handle_game_phase(phase)
            elif resp.status_code == 401:
                self._log('❌ 认证失败，token可能已过期')
        except Exception as e:
            self._log(f'获取初始游戏阶段失败: {e}')

    # ===== 账号 / 大区 =====

    def _get_current_summoner(self):
        """获取当前召唤师信息"""
        try:
            resp = self._lcu.get('/chat/v1/session', timeout=3)
            if resp.status_code == 200:
                data = resp.json()
                self._current_summoner_puuid = data.get('puuid')
                game_name = data.get('game_name', '')
                game_tag = data.get('game_tag', '')
                if game_name and game_tag:
                    self._current_summoner_name = f'{game_name}#{game_tag}'
                else:
                    self._current_summoner_name = data.get('name', '未知')
        except Exception as e:
            self._log(f'获取召唤师信息失败: {e}')

    def _get_region_info(self):
        """获取当前登录大区信息"""
        try:
            resp = self._lcu.get(REGION_LOCALE_URI, timeout=3)
            if resp.status_code == 200:
                self._handle_region_locale(resp.json())
        except Exception as e:
            self._log(f'获取大区信息失败: {e}')

    def _handle_region_locale(self, data):
        """处理 region-locale 数据，获取大区和账号信息"""
        region_code = data.get('region', '')
        account_info = self._fetch_account_info()
        # 回填puuid到current_summoner_puuid，供对局中识别自己所在队伍
        if not self._current_summoner_puuid and account_info['puuid']:
            self._current_summoner_puuid = account_info['puuid']
        platform_id = account_info['platform_id']
        region_name = get_region_name(region_code, platform_id)
        if not platform_id:
            self._log(f'大区: {region_name} (region={region_code}, 未能获取具体大区的 platformId)')

        account_info['region_name'] = region_name
        account_info['region_code'] = region_code

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
            resp = self._lcu.get('/lol-chat/v1/me', timeout=3)
            if resp.status_code == 200:
                data = resp.json()
                info['platform_id'] = data.get('platformId', '') or data.get('lol', {}).get('platformId', '')
                info['game_name'] = data.get('gameName', '')
                info['game_tag'] = data.get('gameTag', '')
                info['puuid'] = data.get('puuid', '')
        except Exception as e:
            self._log(f'获取账号信息失败: {type(e).__name__}: {e}', debug=True)
        return info

    def get_current_game_id(self):
        """获取当前对局的游戏ID（用于违规举报），从LCU gameflow session或缓存获取"""
        try:
            resp = self._lcu.get('/lol-gameflow/v1/session', timeout=3)
            if resp.status_code == 200:
                data = resp.json()
                # BP阶段: data["gameId"]（顶层），InProgress: data["gameData"]["gameId"]
                game_id = data.get('gameId') or data.get('gameData', {}).get('gameId', '')
                if game_id and str(game_id) != '0':
                    self._cached_game_id = str(game_id)
                    return str(game_id)
        except Exception as e:
            self._log(f'从LCU获取对局ID失败: {e}')
        if self._cached_game_id:
            return self._cached_game_id
        return ''

    # ===== 阶段状态机 =====

    def _handle_game_phase(self, phase):
        """处理游戏阶段变化"""
        if phase == self._game_phase:
            return
        self._game_phase = phase
        if phase != 'ChampSelect':
            self._champ_select_retry = False
        self._emit('phase_changed', phase)

        if phase in ['None', 'Lobby', 'Matchmaking', 'ReadyCheck']:
            self._puuid_cache = {}
            self._puuid_riot_cache = {}
            self._cached_game_id = ''
            self._match_history_fetched = False
            self._cached_bp_match_data = None
            self._game_end_fetched = False
            self._game_id_fetch_ts = 0.0
            self._send_clear()
        elif phase == 'ChampSelect':
            self._champ_select_retry = True
            self._send_clear()
            # 阶段刚切换时session可能尚未就绪，未成功则自动重试，确保召唤师立即显示
            self._check_champ_select(retry=True, token=self._run_token)
        elif phase in ['GameStart', 'InProgress', 'Reconnecting']:
            # 选人结束后不立即清空队伍栏：优先沿用BP缓存数据展示，避免读条/进图期间信息消失
            if self._cached_bp_match_data:
                self._send_fallback_match_data()
            else:
                self._send_clear()
            if not self._match_history_fetched:
                self._match_history_fetched = True
                threading.Thread(
                    target=self._fetch_match_history_puuids,
                    kwargs={'token': self._run_token},
                    daemon=True
                ).start()
        elif phase in ['PreEndOfGame', 'EndOfGame']:
            # PreEndOfGame 可能拿不到最终数据，EndOfGame 必定再拉取一次
            if phase == 'PreEndOfGame' and self._game_end_fetched:
                return
            self._game_end_fetched = True
            game_id = self.get_current_game_id() or self._cached_game_id
            if not game_id:
                self._log('对局结束，无gameId，跳过完整战绩拉取')
                return
            threading.Thread(
                target=self._fetch_match_history_at_game_end,
                args=(game_id, self._run_token),
                daemon=True
            ).start()

    def _handle_champ_select_data(self, data):
        """直接使用WS推送的英雄选择会话数据进行解析"""
        try:
            self._apply_champ_select_session(data)
        except Exception as e:
            self._log(f'解析英雄选择数据失败: {type(e).__name__}: {e}')

    def _apply_champ_select_session(self, data):
        """解析并应用英雄选择会话（WS 推送与 HTTP 拉取共用）"""
        result = self._parse_champ_select_data(
            data.get('myTeam') or [],
            data.get('theirTeam') or [],
            data.get('localPlayerCellId', 0),
        )
        match_data = {
            'my_team': result['my_team'],
            'enemy_team': result['enemy_team'],
            'myself': result['myself'],
            'stage': 'champ_select'
        }
        self._cached_bp_match_data = match_data
        # 选人阶段保留 champion_id，GUI 会在原卡片上就地更新头像/英雄名，避免重建闪烁
        self._send_match(match_data)
        # session Update 事件很频繁，这里做5秒节流，避免每个事件都请求一次LCU
        if not self._cached_game_id and time.time() - self._game_id_fetch_ts >= 5.0:
            self._game_id_fetch_ts = time.time()
            game_id = self.get_current_game_id()
            if game_id:
                self._log(f'BP阶段缓存对局ID: {game_id}')
        return match_data

    def _check_champ_select(self, retry=False, token=None):
        """检查英雄选择阶段；retry=True时会话未就绪会持续重试"""
        if not self._is_run_active(token):
            return False
        if retry and not (self._champ_select_retry and self._game_phase == 'ChampSelect'):
            return False
        try:
            resp = self._lcu.get(CHAMP_SELECT_URI, timeout=3)
            if resp.status_code == 200:
                if not self._is_run_active(token):
                    return False
                self._apply_champ_select_session(resp.json())
                return True
            elif not retry:
                self._log(f'英雄选择会话尚未就绪 (HTTP {resp.status_code})')
        except Exception as e:
            if not retry:
                self._log(f'获取英雄选择数据失败: {type(e).__name__}: {str(e)}')

        if (retry and self._champ_select_retry and self._game_phase == 'ChampSelect'
                and self._is_run_active(token)):
            timer = threading.Timer(0.5, self._check_champ_select, args=(True, token))
            timer.daemon = True
            timer.start()
        return False

    def _parse_champ_select_data(self, my_team_data, enemy_team_data, local_player_cell_id=0):
        """解析英雄选择阶段的完整队伍数据，并刷新 puuid 缓存"""
        result = parse_champ_select(
            my_team_data,
            enemy_team_data,
            local_player_cell_id,
            self._current_summoner_puuid,
            self._current_summoner_name,
        )
        self._puuid_cache = collect_puuid_cache(result['my_team'] + result['enemy_team'])
        return result

    # ===== 对局中 / 结束 =====

    def _fetch_match_history_puuids(self, token=None, skip_initial_wait=False):
        """获取对局全体玩家信息并展示"""
        if not self._is_run_active(token):
            return

        if not skip_initial_wait:
            self._log('进入游戏加载阶段，等待5秒后再查询lol-gameflow/v1/session（避免触发LCU限流）...')
            for _ in range(5):
                if (not self._is_run_active(token)
                    or self._game_phase not in ('GameStart', 'InProgress', 'Reconnecting')):
                    self._log('对局已结束，放弃等待')
                    return
                time.sleep(1.0)

        if not self._is_run_active(token):
            return
        if self._try_gameflow_participants():
            return

        self._log('读条阶段gameData未就绪，轮询lol-gameflow/v1/session（每3秒检测，最多90秒）...')
        for wait_round in range(30):
            if (not self._is_run_active(token)
                    or self._game_phase not in ('GameStart', 'InProgress', 'Reconnecting')):
                self._log('对局已结束，放弃等待')
                return
            time.sleep(3.0)
            if not self._is_run_active(token):
                return
            if self._try_gameflow_participants():
                self._log(f'等待{(wait_round + 1) * 3}s后gameData就绪，已展示对局信息')
                return

        self._log('等待超时，gameData仍未就绪，使用BP缓存兜底')
        if not self._is_run_active(token):
            return
        if self._cached_bp_match_data:
            self._send_fallback_match_data()
        else:
            self._send_clear()

    def _try_gameflow_participants(self):
        """从gameflow session的gameData中提取对局玩家信息"""
        try:
            resp = self._lcu.get('/lol-gameflow/v1/session', timeout=5)
            if resp.status_code != 200:
                self._log(f'gameflow session返回 {resp.status_code}')
                return False

            data = resp.json()
            game_data = data.get('gameData', {})
            participants = game_data.get('participants', [])
            team_one = game_data.get('teamOne', [])
            team_two = game_data.get('teamTwo', [])
            self._log(
                f'gameData: participants={len(participants)}, teamOne={len(team_one)}, teamTwo={len(team_two)}',
                debug=True)

            if participants and isinstance(participants, list):
                sample = participants[0]
                sample_keys = list(sample.keys()) if isinstance(sample, dict) else str(type(sample))
                self._log(f'participant首条keys: {sample_keys}', debug=True)

                match_data = self._build_match_data_from_gameflow(participants, None)
                if match_data and (match_data['my_team'] or match_data['enemy_team']):
                    total = len(match_data['my_team']) + len(match_data['enemy_team'])
                    unnamed = sum(1 for p in match_data['my_team'] + match_data['enemy_team']
                                  if p.get('summoner_name', '') in ('', '未知'))
                    self._log(f'gameflow成功提取 {total} 名玩家信息，其中无名玩家 {unnamed} 名')
                    if unnamed > 0 and (team_one or team_two):
                        self._log('participants名字缺失，改用teamOne/teamTwo重建')
                        match_data = self._build_match_data_from_gameflow(team_one, team_two)
                        if match_data and (match_data['my_team'] or match_data['enemy_team']):
                            total = len(match_data['my_team']) + len(match_data['enemy_team'])
                            self._log(f'gameflow(teamOne/Two)成功提取 {total} 名玩家信息')
                    self._send_match(match_data)
                    return True

            if team_one or team_two:
                if team_one:
                    sample = team_one[0]
                    if isinstance(sample, dict):
                        sample_keys = list(sample.keys())
                        self._log(f'teamOne首条keys: {sample_keys}', debug=True)
                        self._log(
                            f'teamOne首条值: summonerName="{sample.get("summonerName", "")}", '
                            f'summonerInternalName="{sample.get("summonerInternalName", "")}", '
                            f'puuid="{sample.get("puuid", "")[:16]}..."', debug=True)

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

    def _request_match_history_once(self, game_id):
        """单次请求战绩接口，返回解析后的JSON数据或None"""
        try:
            resp = self._lcu.get(
                f'/lol-match-history/v1/games/{game_id}', timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                self._log(
                    f'[战绩接口] /lol-match-history/v1/games/{game_id} '
                    f'状态码=200, 顶层字段: {list(data.keys())}')
                return data
            self._log(
                f'[战绩接口] /lol-match-history/v1/games/{game_id} '
                f'状态码={resp.status_code}, 响应: {resp.text[:500]}')
            return None
        except Exception as e:
            self._log(f'[战绩接口] /lol-match-history/v1/games/{game_id} '
                      f'请求异常: {type(e).__name__}: {e}')
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

        id_map = {}
        for pi in identities:
            pid = pi.get('participantId', 0)
            player = pi.get('player', {})
            puuid = player.get('puuid', '')
            name = player.get('summonerName', '') or player.get('gameName', '')
            if puuid and name:
                self._puuid_cache[name] = puuid
            if pid:
                id_map[pid] = {'puuid': puuid, 'name': name}

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
                self._puuid_cache[name] = puuid
                count += 1
            riot_name = p.get('riotIdGameName', '')
            riot_tag = p.get('riotIdTagline', '')
            if puuid and riot_name:
                riot_id_str = f'{riot_name}#{riot_tag}' if riot_tag else riot_name
                self._puuid_cache[riot_id_str] = puuid

        if count > 0:
            self._log(f'战绩接口成功获取 {count} 名玩家信息 (gameId={game_id})')
            match_data = self._build_match_data_from_history(data)
            if match_data:
                self._send_match(match_data)
            return True

        sample = participants[0]
        sample_keys = list(sample.keys()) if isinstance(sample, dict) else str(type(sample))
        self._log(f'participants非空但count=0，首条keys: {sample_keys}', debug=True)
        return False

    def _fetch_match_history_at_game_end(self, game_id, token=None):
        """对局结束时重新请求战绩接口，获取完整对局信息"""
        if not self._is_run_active(token):
            return False
        self._log(f'对局结束，重新获取完整战绩 (gameId={game_id})')
        for attempt in range(4):
            if not self._is_run_active(token):
                return False
            data = self._request_match_history_once(game_id)
            if data and self._process_match_history_data(data, game_id):
                self._log('对局结束，战绩信息已更新（含隐藏玩家信息）')
                return True
            if attempt < 3:
                self._log(f'对局结束获取战绩: 第{attempt + 1}/4次未就绪，2秒后重试')
                time.sleep(2.0)
        self._log('对局结束后战绩接口未就绪，保留原展示')
        return False

    # ===== 解析封装 =====

    def _build_match_data_from_gameflow(self, team_one_players, team_two_players=None):
        return build_match_data_from_gameflow(
            team_one_players,
            team_two_players,
            current_puuid=self._current_summoner_puuid,
            puuid_cache=self._puuid_cache,
            cached_bp_match_data=self._cached_bp_match_data,
            lookup_riot_id=self._lookup_riot_id_by_puuid,
        )

    def _build_match_data_from_history(self, history_data):
        return build_match_data_from_history(
            history_data,
            current_puuid=self._current_summoner_puuid,
            puuid_cache=self._puuid_cache,
            cached_bp_match_data=self._cached_bp_match_data,
        )

    def _send_fallback_match_data(self):
        """战绩接口失败时，使用BP缓存数据兜底展示（标记为in_game阶段）"""
        if not self._cached_bp_match_data:
            return
        fallback = {
            'my_team': self._cached_bp_match_data.get('my_team', []),
            'enemy_team': self._cached_bp_match_data.get('enemy_team', []),
            'myself': self._cached_bp_match_data.get('myself'),
            'stage': 'in_game'
        }
        self._send_match(fallback)

    # ===== 召唤师查询 =====

    @agent_tool("search_summoner",
                description="通过完整 Riot ID（游戏名#TAG）搜索召唤师，返回 PUUID 与 Riot ID 信息")
    def search_summoner(self, riot_id):
        """通过完整 Riot ID 搜索召唤师信息

        使用 GET /lol-summoner/v1/alias/lookup?gameName=xxx&tagLine=yyy
        """
        if not self._lcu.is_connected():
            self._log('LCU 未连接，无法搜索召唤师')
            return None

        query = re.sub(r'[\r\n\t]+', '', riot_id.strip())
        if '#' not in query:
            self._log(f'搜索失败: 输入不是有效的 Riot ID 格式: {query}')
            return None
        game_name, tag_line = query.split('#', 1)
        game_name = game_name.strip()
        tag_line = tag_line.strip()
        if not game_name or not tag_line:
            self._log(f'搜索失败: 游戏名或 TAG 为空: gameName={game_name}, tagLine={tag_line}')
            return None

        params = {'gameName': game_name, 'tagLine': tag_line}
        try:
            self._log(f'搜索召唤师: gameName={game_name}, tagLine={tag_line}')
            resp = self._lcu.get(
                '/lol-summoner/v1/alias/lookup', params=params, timeout=10)
            self._log(f'搜索响应: HTTP {resp.status_code}, url={resp.url}, body={resp.text[:500]}')

            if resp.status_code == 200:
                data = resp.json()
                self._log(f'返回数据: {data}', debug=True)
                if isinstance(data, list):
                    return data[0] if data else None
                return data if data else None
        except Exception as e:
            self._log(f'搜索召唤师异常: {type(e).__name__}: {e}')

        return None

    def _lookup_riot_id_by_puuid(self, puuid):
        """通过puuid反查Riot ID（对局中名字为空时使用，带缓存）"""
        if not puuid:
            return ''
        cached = self._puuid_riot_cache.get(puuid)
        if cached:
            return cached
        try:
            resp = self._lcu.get(
                f'/lol-summoner/v2/summoners/puuid/{puuid}', timeout=5)
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
                    self._puuid_riot_cache[puuid] = riot_id
                    self._log(f'puuid反查Riot ID成功: {riot_id}', debug=True)
                else:
                    self._log(f'puuid反查结果为空: {puuid[:16]}...', debug=True)
                return riot_id
            self._log(f'puuid反查Riot ID失败: 状态码={resp.status_code} (puuid={puuid[:16]}...)',
                      debug=True)
        except Exception as e:
            self._log(f'puuid反查Riot ID异常: {type(e).__name__}: {e}')
        return ''

    # ===== 手动刷新 =====

    def refresh(self, done_callback=None):
        """手动刷新当前对局数据（后台线程执行，返回是否成功排队）"""
        with self._refresh_lock:
            if self._refresh_in_progress:
                return False
            self._refresh_in_progress = True
        token = self._run_token

        def _run():
            try:
                if not self._is_run_active(token):
                    return
                phase = self._game_phase
                if phase == 'ChampSelect':
                    self._check_champ_select(token=token)
                elif phase in ('GameStart', 'InProgress', 'Reconnecting'):
                    self._match_history_fetched = False
                    self._fetch_match_history_puuids(
                        token=token, skip_initial_wait=True)
                else:
                    self._log(f'当前阶段 {phase} 无对局数据可刷新')
            except Exception as e:
                self._log(f'手动刷新异常: {type(e).__name__}: {e}')
            finally:
                with self._refresh_lock:
                    self._refresh_in_progress = False
                if done_callback:
                    try:
                        done_callback()
                    except Exception as e:
                        self._log(f'刷新完成回调异常: {e}')

        threading.Thread(target=_run, daemon=True).start()
        return True
