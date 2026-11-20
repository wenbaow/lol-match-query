"""LCU 大区 / 平台映射（纯数据与纯函数，便于单元测试）。"""

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


def get_region_name(region_code, platform_id):
    """根据 region 与 platformId 解析出可读的大区名称"""
    is_cn = region_code in ('CN', 'TENCENT')
    if platform_id:
        pid = platform_id.upper()
        if is_cn:
            return LOL_CN_PLATFORM_MAP.get(pid, platform_id)
        return PLATFORM_ID_MAP.get(pid, platform_id)
    if is_cn:
        return '国服'
    return REGION_MAP.get(region_code, region_code or '未知')
