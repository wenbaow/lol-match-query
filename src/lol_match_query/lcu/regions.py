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

# 国服 platformId -> 大区名称
#
# 国服合区后，客户端对合并大区上报的是「联盟大区」代码（NJ100/GZ100/CQ100/
# TJ100/TJ101），未合并的艾欧尼亚、黑色玫瑰、峡谷之巅等仍用各自代码。
# 旧电信/网通代码保留，兼容合区前的客户端与历史数据；但 CQ100 现在表示联盟三区，
# 峡谷之巅改为 BGP2。
LOL_CN_PLATFORM_MAP = {
    # 合并后大区（客户端实际上报的 platformId）
    "NJ100": "联盟一区",   # 祖安 / 皮尔特沃夫 / 巨神峰 / 教育网 / 男爵领域 / 均衡教派 / 影流 / 守望之海
    "GZ100": "联盟二区",   # 诺克萨斯 / 战争学院 / 雷瑟守备 / 征服之海 / 暗影岛 / 卡拉曼达
    "CQ100": "联盟三区",   # 班德尔城 / 裁决之地 / 水晶之痕 / 钢铁烈阳 / 皮城警备
    "TJ100": "联盟四区",   # 比尔吉沃特 / 弗雷尔卓德 / 扭曲丛林
    "TJ101": "联盟五区",   # 德玛西亚 / 无畏先锋 / 恕瑞玛 / 巨龙之巢
    # 独立大区
    "HN1": "艾欧尼亚",
    "HN10": "黑色玫瑰",
    "BGP1": "男爵领域",
    "BGP2": "峡谷之巅",
    "PBE": "体验服",
    # 旧电信区（合区前的 platformId，仅历史数据会出现）
    "HN2": "祖安", "HN3": "诺克萨斯", "HN4": "班德尔城",
    "HN5": "皮尔特沃夫", "HN6": "战争学院", "HN7": "巨神峰", "HN8": "雷瑟守备",
    "HN9": "裁决之地", "HN11": "暗影岛", "HN12": "钢铁烈阳",
    "HN13": "水晶之痕", "HN14": "均衡教派", "HN15": "影流", "HN16": "守望之海",
    "HN17": "征服之海", "HN18": "卡拉曼达", "HN19": "皮城警备",
    # 旧网通区（合区前的 platformId，仅历史数据会出现）
    "WT1": "比尔吉沃特", "WT2": "德玛西亚", "WT3": "弗雷尔卓德",
    "WT4": "无畏先锋", "WT5": "恕瑞玛", "WT6": "扭曲丛林", "WT7": "巨龙之巢",
    # 旧特殊大区（合区前）
    "GX1": "男爵领域", "EDU1": "教育网专区",
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
