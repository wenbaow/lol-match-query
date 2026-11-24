"""召唤师速查纯函数测试。"""
from lol_match_query.gui.quick_lookup_model import (
    compute_card_position,
    parse_riot_id,
    summarize_lookup,
)


def test_parse_riot_id():
    assert parse_riot_id('玩家A#1234') == ('玩家A', '1234')
    assert parse_riot_id('  My Name#TAG  ') == ('My Name', 'TAG')
    assert parse_riot_id('玩家＃1234') == ('玩家', '1234')          # 全角井号
    assert parse_riot_id('"玩家A#1234"') == ('玩家A', '1234')       # 带引号
    assert parse_riot_id('玩家A#1234\n多余的行') == ('玩家A', '1234')


def test_parse_riot_id_invalid():
    assert parse_riot_id(None) is None
    assert parse_riot_id('') is None
    assert parse_riot_id('没有井号') is None
    assert parse_riot_id('#1234') is None
    assert parse_riot_id('玩家A#') is None
    assert parse_riot_id('玩家A#12 34') is None
    assert parse_riot_id('玩家A#中文') is None
    assert parse_riot_id('玩家A#1') is None                          # tag 太短


def test_summarize_lookup_dict():
    summary = summarize_lookup({
        'totalCount': 3,
        'typeCounts': [
            {'typeName': '挂机', 'count': '2'},
            {'typeName': '送人头', 'count': 1},
            {'typeName': '辱骂', 'count': 0},
            None,
            'bad',
        ],
    })
    assert summary['total'] == 3
    assert summary['types'] == [('挂机', 2), ('送人头', 1)]


def test_summarize_lookup_scalar_and_dirty():
    assert summarize_lookup(0) == {'total': 0, 'types': []}
    assert summarize_lookup(4) == {'total': 4, 'types': []}
    assert summarize_lookup(None) == {'total': 0, 'types': []}
    assert summarize_lookup('bad') == {'total': 0, 'types': []}
    # total 缺失时用分类型求和兜底
    assert summarize_lookup({
        'typeCounts': [{'typeName': '挂机', 'count': 2}]})['total'] == 2
    assert summarize_lookup({'totalCount': 2, 'typeCounts': 'bad'}) == {
        'total': 2, 'types': []}
    assert summarize_lookup({'totalCount': 'x'}) == {'total': 0, 'types': []}


def test_compute_card_position():
    assert compute_card_position(
        (500, 500), (300, 200), (0, 0, 1920, 1080)) == (516, 518)

    # 靠近右下角 → 翻转到左上方
    assert compute_card_position(
        (1900, 1060), (300, 200), (0, 0, 1920, 1080)) == (1584, 842)

    # 鼠标在左侧副屏（负坐标）
    assert compute_card_position(
        (-100, -50), (300, 200), (-1920, 0, 0, 1080)) == (-416, 4)
