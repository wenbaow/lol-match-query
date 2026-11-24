"""大区映射测试。"""
from lol_match_query.lcu.regions import get_region_name


def test_cn_platform_names():
    assert get_region_name('CN', 'HN1') == '艾欧尼亚'
    assert get_region_name('TENCENT', 'HN10') == '黑色玫瑰'
    assert get_region_name('CN', 'WT1') == '比尔吉沃特'
    assert get_region_name('CN', 'UNKNOWN') == 'UNKNOWN'


def test_cn_merged_platform_names():
    # 合区后客户端上报联盟大区代码（实测：德玛西亚 TJ101、扭曲丛林 TJ100）
    assert get_region_name('CN', 'TJ101') == '联盟五区'
    assert get_region_name('CN', 'TJ100') == '联盟四区'
    assert get_region_name('CN', 'NJ100') == '联盟一区'
    assert get_region_name('CN', 'GZ100') == '联盟二区'
    assert get_region_name('CN', 'CQ100') == '联盟三区'
    # 未合并的独立大区
    assert get_region_name('CN', 'BGP2') == '峡谷之巅'
    assert get_region_name('CN', 'BGP1') == '男爵领域'
    assert get_region_name('CN', 'HN1') == '艾欧尼亚'



def test_international_platform_names():
    assert get_region_name('NA', 'NA1') == '北美'
    assert get_region_name('EUW', 'EUW1') == '西欧'
    assert get_region_name('NA', 'UNKNOWN') == 'UNKNOWN'


def test_region_fallback_without_platform():
    assert get_region_name('CN', '') == '国服'
    assert get_region_name('EUW', '') == '西欧'
    assert get_region_name('', '') == '未知'
    assert get_region_name('UNKNOWN_REGION', '') == 'UNKNOWN_REGION'
