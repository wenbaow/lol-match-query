"""大区映射测试。"""
from lol_match_query.lcu.regions import get_region_name


def test_cn_platform_names():
    assert get_region_name('CN', 'HN1') == '艾欧尼亚'
    assert get_region_name('TENCENT', 'HN10') == '黑色玫瑰'
    assert get_region_name('CN', 'WT1') == '比尔吉沃特'
    assert get_region_name('CN', 'CQ100') == '峡谷之巅'
    assert get_region_name('CN', 'UNKNOWN') == 'UNKNOWN'


def test_international_platform_names():
    assert get_region_name('NA', 'NA1') == '北美'
    assert get_region_name('EUW', 'EUW1') == '西欧'
    assert get_region_name('NA', 'UNKNOWN') == 'UNKNOWN'


def test_region_fallback_without_platform():
    assert get_region_name('CN', '') == '国服'
    assert get_region_name('EUW', '') == '西欧'
    assert get_region_name('', '') == '未知'
    assert get_region_name('UNKNOWN_REGION', '') == 'UNKNOWN_REGION'
