"""对局解析纯函数测试。"""
from lol_match_query.lcu.parser import (
    build_match_data_from_gameflow,
    build_match_data_from_history,
    collect_puuid_cache,
    get_position_name,
    get_spell_name,
    group_players_by_side,
    parse_champ_select,
    strip_champion_info,
)


def test_get_spell_and_position_names():
    assert get_spell_name(4) == '闪现'
    assert get_spell_name(0) == ''
    assert get_spell_name(999) == '技能999'
    assert get_position_name('mid') == '中单'
    assert get_position_name('') == '未知'
    assert get_position_name('other') == 'other'


def test_parse_champ_select_marks_self_and_maps_fields():
    my_team = [
        {
            'cellId': 0, 'gameName': '自己', 'tagLine': '0001', 'championId': 103,
            'puuid': 'p1', 'assignedPosition': 'mid', 'spell1Id': 4, 'spell2Id': 14,
        },
        {
            'cellId': 1, 'gameName': '队友', 'tagLine': '0002', 'championId': 64,
            'puuid': 'p2', 'assignedPosition': 'jungle', 'spell1Id': 4, 'spell2Id': 11,
        },
    ]
    enemy_team = [
        {
            'cellId': 5, 'gameName': '敌人', 'tagLine': '0003', 'championId': 0,
            'puuid': 'p3', 'assignedPosition': 'top', 'spell1Id': 4, 'spell2Id': 12,
            'nameVisibilityType': 'HIDDEN',
        },
    ]

    result = parse_champ_select(my_team, enemy_team, 0, 'p1', '自己#0001')

    assert result['myself']['riot_id'] == '自己#0001'
    assert result['my_team'][0]['role'] == '自己'
    assert result['my_team'][1]['role'] == '队友'
    assert result['my_team'][1]['position'] == '打野'
    assert result['my_team'][0]['spell1'] == '闪现'
    assert result['my_team'][0]['spell2'] == '引燃'
    assert result['enemy_team'][0]['role'] == '敌方'
    assert result['enemy_team'][0]['is_hidden'] is True


def test_collect_puuid_cache_uses_name_and_riot_id():
    players = [
        {'summoner_name': '自己', 'riot_id': '自己#0001', 'puuid': 'p1'},
        {'summoner_name': '未知', 'riot_id': '队友#0002', 'puuid': 'p2'},
        {'summoner_name': '无puuid', 'riot_id': '无puuid#0003', 'puuid': ''},
        None,
    ]

    cache = collect_puuid_cache(players)

    assert cache['自己'] == 'p1'
    assert cache['自己#0001'] == 'p1'
    assert cache['队友#0002'] == 'p2'
    assert '无puuid' not in cache


def test_strip_champion_info_copies_without_touching_original():
    match_data = {
        'my_team': [{'riot_id': 'A#1', 'champion_id': 103}],
        'enemy_team': [{'riot_id': 'B#2', 'champion_id': 64}],
        'myself': {'riot_id': 'A#1', 'champion_id': 103},
        'stage': 'champ_select',
    }

    stripped = strip_champion_info(match_data)

    assert stripped['my_team'][0]['champion_id'] == 0
    assert stripped['enemy_team'][0]['champion_id'] == 0
    assert stripped['myself']['champion_id'] == 0
    assert stripped['stage'] == 'champ_select'
    # 原数据不受影响
    assert match_data['my_team'][0]['champion_id'] == 103


def test_group_players_by_side_uses_self_puuid_then_bp_fallback():
    players = [
        {'team': 'ORDER', 'role': '', 'puuid': 'p1'},
        {'team': 'ORDER', 'role': '', 'puuid': 'p2'},
        {'team': 'CHAOS', 'role': '', 'puuid': 'p3'},
    ]

    my_team, enemy_team = group_players_by_side(players, None, 'p2')
    assert [p['puuid'] for p in my_team] == ['p1', 'p2']
    assert [p['puuid'] for p in enemy_team] == ['p3']
    assert all(p['role'] == '队友' for p in my_team)
    assert enemy_team[0]['role'] == '敌方'

    # 找不到自己时使用 BP 缓存的队伍方向
    my_team2, enemy_team2 = group_players_by_side(
        players, None, 'missing', {'myself': {'team': 'CHAOS'}})
    assert [p['puuid'] for p in my_team2] == ['p3']
    assert [p['puuid'] for p in enemy_team2] == ['p1', 'p2']


def test_build_match_data_from_gameflow_participants():
    participants = [
        {'teamId': 100, 'puuid': 'p1', 'championId': 103,
         'gameName': '自己', 'gameTag': '0001'},
        {'teamId': 100, 'puuid': 'p2', 'championId': 64,
         'gameName': '队友', 'gameTag': '0002'},
        {'teamId': 200, 'puuid': 'p3', 'championId': 17,
         'gameName': '敌人', 'gameTag': '0003'},
        {'teamId': 100, 'puuid': 'p4', 'championId': 0},
    ]
    lookup_calls = []

    def lookup(puuid):
        lookup_calls.append(puuid)
        return '反查#0004' if puuid == 'p4' else ''

    cache = {}
    result = build_match_data_from_gameflow(
        participants, None, current_puuid='p1', puuid_cache=cache,
        lookup_riot_id=lookup)

    assert result['myself']['riot_id'] == '自己#0001'
    assert [p['riot_id'] for p in result['my_team']] == [
        '自己#0001', '队友#0002', '反查#0004']
    assert result['enemy_team'][0]['riot_id'] == '敌人#0003'
    assert result['enemy_team'][0]['role'] == '敌方'
    assert lookup_calls == ['p4']
    assert cache['反查#0004'] == 'p4'
    assert result['stage'] == 'in_game'


def test_build_match_data_from_gameflow_team_lists():
    team_one = [
        {'puuid': 'p1', 'championId': 103, 'gameName': '上', 'gameTag': '1'},
    ]
    team_two = [
        {'puuid': 'p2', 'championId': 64, 'gameName': '下', 'gameTag': '2'},
    ]

    result = build_match_data_from_gameflow(
        team_one, team_two, current_puuid='p2')

    assert [p['puuid'] for p in result['my_team']] == ['p2']
    assert [p['puuid'] for p in result['enemy_team']] == ['p1']
    assert result['myself']['riot_id'] == '下#2'


def test_build_match_data_from_history():
    history = {
        'participantIdentities': [
            {'participantId': 1, 'player': {
                'summonerName': '自己', 'gameName': '自己', 'tagLine': '0001', 'puuid': 'p1'}},
            {'participantId': 2, 'player': {
                'summonerName': '队友', 'gameName': '队友', 'tagLine': '0002', 'puuid': 'p2'}},
            {'participantId': 3, 'player': {}},
        ],
        'participants': [
            {'participantId': 1, 'championId': 103, 'teamId': 100},
            {'participantId': 2, 'championId': 64, 'teamId': 200},
            {'participantId': 3, 'championId': 17, 'teamId': 200,
             'puuid': 'p3', 'riotIdGameName': '敌人', 'riotIdTagline': '0003'},
        ],
    }

    result = build_match_data_from_history(history, current_puuid='p1')

    assert result['myself']['riot_id'] == '自己#0001'
    assert [p['riot_id'] for p in result['my_team']] == ['自己#0001']
    assert [p['riot_id'] for p in result['enemy_team']] == ['队友#0002', '敌人#0003']
    assert result['enemy_team'][1]['puuid'] == 'p3'
