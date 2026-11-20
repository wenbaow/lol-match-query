"""LCU 对局数据解析。

这里只放纯函数：不依赖网络、线程、GUI，便于单元测试。
客户端负责取数、缓存与回调，解析/分组逻辑集中在本文档。
"""
from typing import Callable, Optional

# 召唤师技能ID -> 中文名（ID 以 Data Dragon summoner.json 为准）
SPELL_NAMES = {
    1: '净化', 3: '虚弱', 4: '闪现', 6: '幽灵疾步', 7: '治疗术',
    11: '惩戒', 12: '传送', 13: '清晰术', 14: '引燃', 21: '屏障',
    30: '护驾！', 31: '魄罗投掷', 32: '标记', 39: '标记',
}

POSITION_NAMES = {
    'top': '上单', 'jungle': '打野', 'mid': '中单',
    'bottom': 'ADC', 'support': '辅助', '': '未知',
}

UNKNOWN = '未知'


def _safe_name(value):
    """把可能为 None / 非字符串的字段安全转换为去空白字符串"""
    return value.strip() if isinstance(value, str) else ''


def get_spell_name(spell_id):
    """根据技能ID获取技能名称；0/空表示尚未选定，返回空字符串"""
    if not spell_id:
        return ''
    return SPELL_NAMES.get(spell_id, f'技能{spell_id}')


def get_position_name(position):
    """将位置缩写转换为中文名称"""
    return POSITION_NAMES.get(position, position)


def strip_champion_info(match_data):
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
    for player in match_data.get('my_team') or []:
        item = dict(player)
        item['champion_id'] = 0
        stripped['my_team'].append(item)
    for player in match_data.get('enemy_team') or []:
        item = dict(player)
        item['champion_id'] = 0
        stripped['enemy_team'].append(item)
    myself = match_data.get('myself')
    if myself:
        item = dict(myself)
        item['champion_id'] = 0
        stripped['myself'] = item
    return stripped


def parse_champ_select(my_team_data, enemy_team_data, local_player_cell_id=0,
                       current_summoner_puuid=None, current_summoner_name=None):
    """解析英雄选择阶段的完整队伍数据"""
    my_team = []
    enemy_team = []
    myself = None

    def build_player(player, default_role, team):
        game_name = _safe_name(player.get('gameName'))
        tag_line = _safe_name(player.get('tagLine'))
        champion_id = player.get('championId', 0)
        puuid = player.get('puuid', '')
        position = get_position_name(player.get('assignedPosition', ''))
        spell1 = get_spell_name(player.get('spell1Id', 0))
        spell2 = get_spell_name(player.get('spell2Id', 0))
        cell_id = player.get('cellId', 0)
        # 选人阶段仅以 nameVisibilityType=HIDDEN 判断隐藏玩家（能拿到puuid即可识别，不算隐藏）
        is_hidden = player.get('nameVisibilityType') == 'HIDDEN'

        riot_id = f'{game_name}#{tag_line}' if game_name else UNKNOWN
        summoner_name = game_name or UNKNOWN

        is_me = (
            cell_id == local_player_cell_id
            or (current_summoner_puuid and puuid == current_summoner_puuid)
            or (current_summoner_name and riot_id == current_summoner_name)
        )

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
            'team': team,
        }

    for player in my_team_data or []:
        if not isinstance(player, dict):
            continue
        player_info = build_player(player, '队友', 'ORDER')
        if player_info['role'] == '自己':
            myself = player_info
        my_team.append(player_info)

    for player in enemy_team_data or []:
        if not isinstance(player, dict):
            continue
        enemy_team.append(build_player(player, '敌方', 'CHAOS'))

    return {'my_team': my_team, 'enemy_team': enemy_team, 'myself': myself}


def collect_puuid_cache(players):
    """从玩家列表中收集 name / riot_id -> puuid 映射"""
    cache = {}
    for player in players or []:
        if not isinstance(player, dict):
            continue
        puuid = player.get('puuid', '')
        if not puuid:
            continue
        for key in ('summoner_name', 'riot_id'):
            name = player.get(key, '')
            if name and name != UNKNOWN:
                cache[name] = puuid
    return cache


def group_players_by_side(players, myself=None, current_puuid=None,
                          cached_bp_match_data=None):
    """根据自己所在队伍分组，并统一设置角色标签"""
    if myself:
        my_team_side = myself.get('team', 'ORDER')
    else:
        # myself未识别时，优先通过当前召唤师puuid精确匹配玩家所在队伍
        account_puuid = current_puuid or ''
        matched_side = ''
        for player in players:
            if player.get('puuid') and player.get('puuid') == account_puuid:
                matched_side = player.get('team', '')
                break
        if matched_side:
            my_team_side = matched_side
        else:
            # 兜底：BP缓存myself的team（仅当BP阶段已知我方队伍方向）
            bp_myself = (cached_bp_match_data or {}).get('myself') or {}
            my_team_side = bp_myself.get('team', 'ORDER')

    my_team = [p for p in players if p.get('team') == my_team_side]
    enemy_team = [p for p in players if p.get('team') != my_team_side]

    for player in my_team:
        if player.get('role') != '自己':
            player['role'] = '队友'
    for player in enemy_team:
        player['role'] = '敌方'
    return my_team, enemy_team


def build_match_data_from_gameflow(team_one_players, team_two_players=None,
                                   current_puuid=None, puuid_cache=None,
                                   cached_bp_match_data=None,
                                   lookup_riot_id: Optional[Callable[[str], str]] = None):
    """从 gameflow session 构建对局信息

    Args:
        team_one_players: teamOne数组或participants数组（ORDER方）
        team_two_players: teamTwo数组（CHAOS方），为None时用teamId判断队伍
        puuid_cache: 会被原地补充 name/riot_id -> puuid 映射
        lookup_riot_id: 名字缺失时的 puuid 反查回调（可为 None）
    """
    puuid_cache = puuid_cache if puuid_cache is not None else {}

    # 构建 puuid -> name 反查表（从BP缓存）
    puuid_to_name = {}
    for cached_name, cached_puuid in puuid_cache.items():
        if not cached_puuid:
            continue
        # 优先保留 Riot ID 格式（含#）的名称
        if cached_puuid not in puuid_to_name or '#' in cached_name:
            puuid_to_name[cached_puuid] = cached_name

    all_players = []
    myself = None

    def parse_player(player, team):
        nonlocal myself
        if not isinstance(player, dict):
            return None

        puuid = player.get('puuid', '')
        champion_id = player.get('championId', 0)

        # 优先使用 gameName + gameTag (Riot ID 新格式)，summonerName 在 gameflow session 中为空
        game_name = _safe_name(player.get('gameName'))
        game_tag = _safe_name(player.get('gameTag'))

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
            cached_name = puuid_to_name.get(puuid)
            if cached_name and '#' in cached_name:
                summoner_name = cached_name
                riot_id = cached_name
            elif lookup_riot_id:
                lookup_name = lookup_riot_id(puuid)
                if lookup_name:
                    summoner_name = lookup_name
                    riot_id = lookup_name

        if not summoner_name:
            summoner_name = UNKNOWN
            if not riot_id:
                riot_id = UNKNOWN

        is_me = bool(puuid and puuid == current_puuid)

        if not puuid:
            puuid = (puuid_cache.get(summoner_name, '')
                     or puuid_cache.get(riot_id, ''))

        if puuid:
            if summoner_name and summoner_name != UNKNOWN:
                puuid_cache[summoner_name] = puuid
            if riot_id and riot_id != UNKNOWN:
                puuid_cache[riot_id] = puuid

        # 能拿到puuid即可识别该玩家，不算隐藏玩家；仅当既无名又无puuid时才显示为隐藏
        is_hidden = summoner_name == UNKNOWN and not puuid

        player_info = {
            'summoner_name': summoner_name,
            'riot_id': riot_id,
            'champion_id': champion_id,
            'champion_name': f'英雄{champion_id}',
            'puuid': puuid,
            'team': team,
            'role': '自己' if is_me else '',
            'is_hidden': is_hidden,
        }

        if is_me:
            myself = player_info
        return player_info

    if team_two_players is not None:
        for player in team_one_players or []:
            info = parse_player(player, 'ORDER')
            if info:
                all_players.append(info)
        for player in team_two_players or []:
            info = parse_player(player, 'CHAOS')
            if info:
                all_players.append(info)
    else:
        for player in team_one_players or []:
            if not isinstance(player, dict):
                continue
            team_id = player.get('teamId', 100)
            team = 'ORDER' if team_id == 100 else 'CHAOS'
            info = parse_player(player, team)
            if info:
                all_players.append(info)

    my_team, enemy_team = group_players_by_side(
        all_players, myself, current_puuid, cached_bp_match_data)
    return {
        'my_team': my_team,
        'enemy_team': enemy_team,
        'myself': myself,
        'stage': 'in_game',
    }


def build_match_data_from_history(history_data, current_puuid=None,
                                  puuid_cache=None, cached_bp_match_data=None):
    """从战绩接口数据构建对局信息（替代 Live Client Data）"""
    puuid_cache = puuid_cache if puuid_cache is not None else {}
    all_players = []
    myself = None

    id_map = {}
    for pi in history_data.get('participantIdentities') or []:
        if not isinstance(pi, dict):
            continue
        pid = pi.get('participantId', 0)
        id_map[pid] = pi.get('player') or {}

    for participant in history_data.get('participants') or []:
        if not isinstance(participant, dict):
            continue
        pid = participant.get('participantId', 0)
        player = id_map.get(pid) or {}

        summoner_name = (
            _safe_name(player.get('summonerName') or player.get('gameName'))
            or UNKNOWN
        )
        puuid = player.get('puuid', '') or participant.get('puuid', '')
        champion_id = participant.get('championId', 0)
        team_id = participant.get('teamId', 100)
        team = 'ORDER' if team_id == 100 else 'CHAOS'

        game_name = _safe_name(player.get('gameName') or participant.get('riotIdGameName'))
        tag_line = _safe_name(player.get('tagLine') or participant.get('riotIdTagline'))
        if game_name and tag_line:
            riot_id = f'{game_name}#{tag_line}'
            # 召唤师名字优先使用 Riot ID 完整格式显示（gameName#tagLine）
            summoner_name = riot_id
        elif game_name:
            riot_id = game_name
        else:
            riot_id = summoner_name

        is_me = bool(puuid and puuid == current_puuid)

        if not puuid:
            puuid = (puuid_cache.get(summoner_name, '')
                     or puuid_cache.get(riot_id, ''))

        player_info = {
            'summoner_name': summoner_name,
            'riot_id': riot_id,
            'champion_id': champion_id,
            'champion_name': f'英雄{champion_id}',
            'puuid': puuid,
            'team': team,
            'role': '自己' if is_me else '',
            'is_hidden': False,
        }

        if is_me:
            myself = player_info
        all_players.append(player_info)

    my_team, enemy_team = group_players_by_side(
        all_players, myself, current_puuid, cached_bp_match_data)
    return {
        'my_team': my_team,
        'enemy_team': enemy_team,
        'myself': myself,
        'stage': 'in_game',
    }
