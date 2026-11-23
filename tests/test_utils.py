"""GUI 通用纯函数测试。"""
from lol_match_query.gui.utils import (
    format_violation_detail,
    only_champion_changed,
    safe_int,
)


def test_safe_int():
    assert safe_int(None) == 0
    assert safe_int('') == 0
    assert safe_int('3') == 3
    assert safe_int('bad') == 0
    assert safe_int(None, default=5) == 5


def test_only_champion_changed():
    base = {'champion_id': 1, 'puuid': 'p1', 'spell1': '闪现', 'spell2': '引燃'}
    assert only_champion_changed(base, {**base, 'champion_id': 2}) is True
    assert only_champion_changed(base, {**base, 'spell2': '传送'}) is False
    assert only_champion_changed(
        base, {**base, 'champion_id': 2, 'spell2': '传送'}) is False
    assert only_champion_changed(None, base) is False


def test_format_violation_detail_int():
    assert format_violation_detail(0) == '违规次数: 0 (无违规记录)'
    assert format_violation_detail(3) == '违规次数: 3'


def test_format_violation_detail_dict():
    assert format_violation_detail({'totalCount': 0}) == '违规次数: 0 (无违规记录)'

    text = format_violation_detail({
        'totalCount': 3,
        'typeCounts': [
            {'typeName': '挂机', 'count': '2'},
            {'typeName': '送人头'},
            None,
            'bad',
        ],
    })
    assert '违规次数: 3' in text
    assert '挂机: 2次' in text


def test_format_violation_detail_dirty_input():
    assert '违规次数' in format_violation_detail(None)
    assert format_violation_detail({'totalCount': 1, 'typeCounts': 'bad'}) == '违规次数: 1'
