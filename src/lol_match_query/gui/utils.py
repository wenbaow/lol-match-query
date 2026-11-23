"""GUI 层通用工具函数（纯函数，便于单元测试）。"""


def safe_int(value, default=0):
    """把后端可能返回的字符串/None 安全转换为 int"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def only_champion_changed(old_player, new_player):
    """判断两个玩家卡片数据是否只有 champion_id 不同（用于 BP 原位更新）"""
    if not isinstance(old_player, dict) or not isinstance(new_player, dict):
        return False
    keys = set(old_player) | set(new_player)
    return all(
        old_player.get(key) == new_player.get(key)
        for key in keys
        if key != 'champion_id'
    )


def format_violation_detail(detail_data):
    """将违规详情数据格式化为显示文本，兼容 int / dict / 脏数据"""
    # 兼容 int 格式（API 返回的 data 直接是总次数）
    if isinstance(detail_data, int):
        if detail_data == 0:
            return '违规次数: 0 (无违规记录)'
        return f'违规次数: {detail_data}'
    if not isinstance(detail_data, dict):
        return f'违规次数: {detail_data}'

    total = safe_int(detail_data.get('totalCount'))
    type_counts = detail_data.get('typeCounts') or []
    if not isinstance(type_counts, list):
        type_counts = []
    if total == 0:
        return '违规次数: 0 (无违规记录)'

    # 只显示次数 > 0 的类型
    active_types = [
        t for t in type_counts
        if isinstance(t, dict) and safe_int(t.get('count')) > 0
    ]
    lines = [f'违规次数: {total}']
    if active_types:
        type_str = '  '.join(
            f'{t.get("typeName", "未知")}: {safe_int(t.get("count"))}次'
            for t in active_types
        )
        lines.append(f'  明细: {type_str}')
    return '\n'.join(lines)
