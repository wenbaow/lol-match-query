"""悬浮层展示模型测试。"""
from lol_match_query.gui.overlay_model import (
    MODE_CHAMP_SELECT,
    MODE_IDLE,
    MODE_IN_GAME,
    MODE_LOADING,
    build_overlay_model,
    build_row,
    collect_puuids,
    compute_overlay_position,
    count_text,
    geometry_position,
    match_signature,
    phase_mode,
    truncate_name,
)


def _player(**kwargs):
    base = {
        'puuid': 'p1',
        'riot_id': 'Test#1234',
        'champion_id': 0,
        'is_hidden': False,
        'position': '',
    }
    base.update(kwargs)
    return base


def test_phase_mode():
    assert phase_mode('ChampSelect') == MODE_CHAMP_SELECT
    assert phase_mode('GameStart') == MODE_LOADING
    assert phase_mode('InProgress') == MODE_IN_GAME
    assert phase_mode('Reconnect') == MODE_IN_GAME
    assert phase_mode('Reconnecting') == MODE_IN_GAME
    assert phase_mode('Lobby') == MODE_IDLE
    assert phase_mode(None) == MODE_IDLE
    assert phase_mode('') == MODE_IDLE


def test_count_text():
    assert count_text(0) == ''
    assert count_text(None) == ''
    assert count_text(3) == '3次'
    assert count_text('2') == '2次'
    assert count_text('bad') == ''


def test_truncate_name():
    assert truncate_name('短名字') == '短名字'
    assert truncate_name('一二三四五六七八九十一二三四五', 6) == '一二三四五…'
    assert truncate_name('', 6) == ''
    assert truncate_name(None) == ''


def test_build_row():
    row = build_row(_player(puuid='a', riot_id='A#1'), {'a': 3}, self_puuid='a',
                    champion_names={157: '亚索'})
    assert row['name'] == 'A#1'
    assert row['count'] == 3
    assert row['count_text'] == '3次'
    assert row['flagged'] is True
    assert row['self'] is True

    hidden = build_row(_player(puuid='', is_hidden=True), {'': 9})
    assert hidden['name'] == '隐藏玩家'
    assert hidden['count'] == 0
    assert hidden['flagged'] is False

    hidden_position = build_row(
        _player(puuid='', is_hidden=True, position='中单'), {})
    assert hidden_position['name'] == '隐藏玩家·中单'

    unknown = build_row({}, None)
    assert unknown['name'] == '未知'


def test_build_overlay_model_groups():
    match_data = {
        'my_team': [
            _player(puuid='a', riot_id='A#1', champion_id=157),
            _player(puuid='b', riot_id='B#2'),
        ],
        'enemy_team': [
            _player(puuid='c', riot_id='C#3', is_hidden=True),
        ],
    }
    model = build_overlay_model(match_data, {'a': 3}, 'ChampSelect',
                                self_puuid='b', champion_names={157: '亚索'})
    assert model['mode'] == MODE_CHAMP_SELECT
    assert model['badge'] == '选人'
    assert [group['title'] for group in model['groups']] == ['我方 2', '敌方 1']
    rows = model['groups'][0]['rows']
    assert rows[0]['count'] == 3 and rows[0]['flagged'] is True
    assert rows[0]['champion'] == '亚索'
    assert rows[1]['self'] is True
    assert model['groups'][1]['rows'][0]['name'] == '隐藏玩家'
    assert model['known'] == 3
    assert model['flagged'] == 1
    assert model['queryable'] == 3


def test_build_overlay_model_idle():
    model = build_overlay_model(None, None, 'Lobby')
    assert model['mode'] == MODE_IDLE
    assert model['groups'] == []
    assert model['hint'] == ''


def test_build_overlay_model_hint():
    model = build_overlay_model(None, None, 'GameStart')
    assert model['mode'] == MODE_LOADING
    assert model['hint'] == '等待加载数据…'
    assert model['known'] == 0


def test_match_signature():
    match_data = {
        'my_team': [_player(puuid='b'), _player(puuid='a')],
        'enemy_team': [_player(puuid='a'), {}],
    }
    assert match_signature(match_data) == 'a|b'
    assert match_signature(None) == ''
    assert match_signature({'my_team': [{}]}) == ''


def test_collect_puuids_order():
    match_data = {
        'my_team': [_player(puuid='b'), _player(puuid='a')],
        'enemy_team': [_player(puuid='a'), _player(puuid='c')],
    }
    assert collect_puuids(match_data) == ['b', 'a', 'c']
    assert collect_puuids(None) == []


def test_compute_overlay_position_right():
    pos = compute_overlay_position(
        (100, 50, 800, 600), (272, 200), (12, 56), (0, 0, 1920, 1080))
    assert pos == (912, 106)


def test_compute_overlay_position_flip_left():
    # 目标窗口贴右边，右侧放不下 → 贴左侧
    pos = compute_overlay_position(
        (1200, 100, 700, 600), (272, 200), (12, 56), (0, 0, 1920, 1080))
    assert pos == (916, 156)


def test_compute_overlay_position_clamp_inside():
    # 全屏游戏窗口两侧都放不下 → 压在窗口右侧内部
    pos = compute_overlay_position(
        (0, 0, 1920, 1080), (272, 200), (12, 56), (0, 0, 1920, 1080))
    assert pos == (1636, 56)


def test_compute_overlay_position_clamp_vertical():
    pos = compute_overlay_position(
        (100, 900, 800, 200), (272, 200), (12, 56), (0, 0, 1920, 1080))
    assert pos[1] == 1080 - 200 - 4


def test_geometry_position():
    assert geometry_position(100, 50) == '+100+50'
    assert geometry_position(-1920, 0) == '-1920+0'
    assert geometry_position(0, -60) == '+0-60'
