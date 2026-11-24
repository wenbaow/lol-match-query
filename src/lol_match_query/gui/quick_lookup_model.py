"""召唤师速查的纯函数：Riot ID 解析、违规结果摘要、结果卡片定位。

不依赖 tkinter，便于在 CI 上直接测试。
"""
import re

from .utils import safe_int

_TAG_PATTERN = re.compile(r'^[0-9A-Za-z]{2,8}$')
_QUOTES = '"\'“”‘’「」『』'


def parse_riot_id(text):
    """从剪贴板文本解析 Riot ID → (game_name, tag)，非法返回 None

    兼容：整段只有 Riot ID、带首尾空白/引号、全角 '＃'、多行文本取第一行。
    """
    if not text:
        return None
    raw = str(text).replace('＃', '#').strip()
    if not raw:
        return None
    line = raw.splitlines()[0].strip()
    line = line.strip(_QUOTES).strip()
    if '#' not in line:
        return None

    game_name, _, tag = line.rpartition('#')
    game_name = game_name.strip()
    tag = tag.strip()
    if not game_name or not tag:
        return None
    if len(game_name) > 32 or not _TAG_PATTERN.match(tag):
        return None
    return game_name, tag


def summarize_lookup(data):
    """违规接口返回（dict / int / None）→ {'total': int, 'types': [(名称, 次数)]}"""
    total = 0
    types = []

    if isinstance(data, dict):
        total = safe_int(data.get('totalCount'))
        raw_types = data.get('typeCounts')
        if isinstance(raw_types, list):
            for item in raw_types:
                if not isinstance(item, dict):
                    continue
                count = safe_int(item.get('count'))
                if count > 0:
                    types.append((str(item.get('typeName') or '未知'), count))
    elif isinstance(data, int) and not isinstance(data, bool):
        total = data
    elif isinstance(data, float) and not isinstance(data, bool):
        total = safe_int(data)

    types.sort(key=lambda item: item[1], reverse=True)
    if total <= 0 and types:
        total = sum(count for _name, count in types)
    return {'total': total, 'types': types}


def compute_card_position(cursor, size, work_area):
    """结果卡片出现在鼠标右下方；越界时翻转到左上方，并夹在工作区内"""
    cursor_x, cursor_y = cursor
    card_w, card_h = size
    left, top, right, bottom = work_area

    x = cursor_x + 16
    if x + card_w > right - 4:
        x = cursor_x - card_w - 16
    y = cursor_y + 18
    if y + card_h > bottom - 4:
        y = cursor_y - card_h - 18

    min_x, max_x = left + 4, max(left + 4, right - card_w - 4)
    min_y, max_y = top + 4, max(top + 4, bottom - card_h - 4)
    return int(max(min_x, min(x, max_x))), int(max(min_y, min(y, max_y)))
