"""悬浮层展示模型（纯函数，不依赖 tkinter，便于单元测试）。

职责：
- 把 LCU 阶段映射成悬浮层显示模式（选人 / 加载中 / 对局中）
- 把对局数据 + 违规次数整理成可直接渲染的分组行
- 计算悬浮层贴靠目标窗口的坐标（右侧优先 → 左侧 → 贴边）

悬浮窗只负责画，所有"显示什么"的决策都在这里，方便测试。
"""
from .utils import safe_int

MODE_IDLE = 'idle'
MODE_CHAMP_SELECT = 'champ_select'
MODE_LOADING = 'loading'
MODE_IN_GAME = 'in_game'

# LCU gameflow 阶段 → 悬浮层模式；其余阶段（大厅/匹配/结算…）都视为 idle
PHASE_MODES = {
    'ChampSelect': MODE_CHAMP_SELECT,
    'GameStart': MODE_LOADING,
    'InProgress': MODE_IN_GAME,
    'Reconnect': MODE_IN_GAME,
    'Reconnecting': MODE_IN_GAME,
}

MODE_BADGES = {
    MODE_CHAMP_SELECT: '选人',
    MODE_LOADING: '加载中',
    MODE_IN_GAME: '对局中',
}

MODE_HINTS = {
    MODE_CHAMP_SELECT: '等待选人数据…',
    MODE_LOADING: '等待加载数据…',
    MODE_IN_GAME: '等待对局数据…',
}

HIDDEN_NAME = '隐藏玩家'
UNKNOWN_NAME = '未知'
ICON_MARGIN = 4


def phase_mode(phase):
    """LCU 阶段 → 悬浮层模式"""
    return PHASE_MODES.get(phase or '', MODE_IDLE)


def is_active_mode(mode):
    """是否为需要展示玩家的模式"""
    return mode in (MODE_CHAMP_SELECT, MODE_LOADING, MODE_IN_GAME)


def count_text(count):
    """违规次数文案：0 次返回空串，由界面显示占位符"""
    value = safe_int(count)
    return f'{value}次' if value > 0 else ''


def truncate_name(name, limit=13):
    """超长 Riot ID 截断（悬浮层宽度有限）"""
    text = str(name or '')
    if limit <= 0 or len(text) <= limit:
        return text
    return text[:limit - 1] + '…'


def build_row(player, counts, self_puuid='', champion_names=None):
    """单个玩家 → 悬浮层行数据"""
    puuid = player.get('puuid') or ''
    hidden = bool(player.get('is_hidden'))
    position = player.get('position', '')
    if hidden:
        # 敌方被隐藏时保留位置信息，避免显示一排相同的"隐藏玩家"
        name = f'{HIDDEN_NAME}·{position}' if position else HIDDEN_NAME
    else:
        name = player.get('riot_id') or UNKNOWN_NAME
    champion_id = safe_int(player.get('champion_id'))
    champion = (champion_names or {}).get(champion_id, '')
    count = safe_int((counts or {}).get(puuid)) if puuid else 0
    return {
        'puuid': puuid,
        'name': name,
        'champion': champion,
        'champion_id': champion_id,
        'count': count,
        'count_text': count_text(count),
        'flagged': count > 0,
        'hidden': hidden,
        'self': bool(puuid and self_puuid and puuid == self_puuid),
        'position': position,
    }


def build_overlay_model(match_data, counts=None, phase=None,
                        self_puuid='', champion_names=None):
    """把对局数据整理成悬浮层模型（分组 + 统计 + 空态提示）"""
    mode = phase_mode(phase)
    if mode == MODE_IDLE:
        return {
            'mode': MODE_IDLE,
            'badge': '',
            'groups': [],
            'hint': '',
            'known': 0,
            'flagged': 0,
            'queryable': 0,
        }

    counts = counts or {}
    groups = []
    for title, key in (('我方', 'my_team'), ('敌方', 'enemy_team')):
        players = (match_data or {}).get(key) or []
        rows = [
            build_row(player, counts, self_puuid, champion_names)
            for player in players
            if isinstance(player, dict)
        ]
        if rows:
            groups.append({'title': f'{title} {len(rows)}', 'rows': rows})

    known = sum(len(group['rows']) for group in groups)
    return {
        'mode': mode,
        'badge': MODE_BADGES[mode],
        'groups': groups,
        'hint': '' if known else MODE_HINTS[mode],
        'known': known,
        'flagged': sum(1 for group in groups for row in group['rows'] if row['flagged']),
        'queryable': sum(1 for group in groups for row in group['rows'] if row['puuid']),
    }


def match_signature(match_data):
    """当前对局玩家 puuid 签名（用于自动查询去重与失败重试判断）"""
    puuids = []
    for key in ('my_team', 'enemy_team'):
        for player in (match_data or {}).get(key) or []:
            puuid = player.get('puuid') if isinstance(player, dict) else ''
            if puuid:
                puuids.append(puuid)
    return '|'.join(sorted(set(puuids)))


def collect_puuids(match_data):
    """按出现顺序收集当前对局可查询的 puuid（去重）"""
    seen = set()
    puuids = []
    for key in ('my_team', 'enemy_team'):
        for player in (match_data or {}).get(key) or []:
            puuid = player.get('puuid') if isinstance(player, dict) else ''
            if puuid and puuid not in seen:
                seen.add(puuid)
                puuids.append(puuid)
    return puuids


def snap_icon_position(x, y, icon_size, work_area, anchor_x=None):
    """收起后的小图标贴边定位。

    水平方向吸附到工作区最近的左 / 右边缘，垂直方向限制在工作区内。
    icon_size: (w, h) 图标尺寸
    work_area: (left, top, right, bottom) 图标所在显示器的工作区
    anchor_x: 判断贴左 / 贴右的参考点，默认用图标中心；
              从面板收起时传入面板中心，避免按图标左边缘判断错边
    """
    width, height = icon_size
    left, top, right, bottom = work_area

    min_x = left + ICON_MARGIN
    max_x = max(min_x, right - width - ICON_MARGIN)
    min_y = top + ICON_MARGIN
    max_y = max(min_y, bottom - height - ICON_MARGIN)

    y = max(min_y, min(int(y), max_y))
    if anchor_x is None:
        anchor_x = int(x) + width // 2
    if int(anchor_x) < (left + right) // 2:
        return int(min_x), int(y)
    return int(max_x), int(y)


def compute_overlay_position(target_rect, overlay_size, offset, work_area):
    """计算悬浮层坐标。

    target_rect: (x, y, w, h) 目标窗口
    overlay_size: (w, h) 悬浮层尺寸
    offset: (dx, dy) 相对目标窗口右上角的偏移；dx 为与右边缘的水平间距，dy 为与顶部的距离
    work_area: (left, top, right, bottom) 目标窗口所在显示器的工作区
    """
    tx, ty, tw, _th = target_rect
    ow, oh = overlay_size
    dx, dy = offset
    left, top, right, bottom = work_area

    min_x, max_x = left + 4, max(left + 4, right - ow - 4)
    min_y, max_y = top + 4, max(top + 4, bottom - oh - 4)

    # 优先贴右侧，空间不足贴左侧，两侧都放不下则压在目标窗口右侧内部
    x = tx + tw + dx
    if x > max_x:
        x = tx - dx - ow
    if x < min_x:
        x = tx + tw - ow - dx
    x = max(min_x, min(x, max_x))

    y = ty + dy
    y = max(min_y, min(y, max_y))
    return int(x), int(y)


def geometry_position(x, y):
    """生成 Tk geometry 的位置串，正确处理负坐标（副屏在左侧）"""
    x_part = f'+{x}' if x >= 0 else f'-{abs(x)}'
    y_part = f'+{y}' if y >= 0 else f'-{abs(y)}'
    return f'{x_part}{y_part}'
