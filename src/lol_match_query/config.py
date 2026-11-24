"""应用配置持久化（~/.lol_helper/config.json）。

只保存少量界面偏好；文件损坏或字段非法时回退到默认值，不影响启动。
"""
import json
import os
from pathlib import Path

CONFIG_DIR = Path.home() / '.lol_helper'
CONFIG_PATH = CONFIG_DIR / 'config.json'

DEFAULT_CONFIG = {
    'overlay_enabled': True,       # 启动时自动打开悬浮层
    'overlay_auto_query': True,    # 悬浮层出现对局时自动查询违规次数
    'overlay_alpha': 0.95,         # 悬浮层不透明度
    'overlay_offset': [12, 56],    # 相对目标窗口右边缘/顶部的偏移
    'overlay_collapsed': False,    # 悬浮层是否收起为贴边小图标
    'overlay_icon_pos': None,      # 小图标的屏幕坐标 [x, y]，None 表示自动贴右边
    'hotkey_enabled': True,        # 复制 Riot ID 后按热键速查
    'hotkey': 'ctrl+alt+q',        # 全局热键（修饰键+单键，如 ctrl+shift+f）
}

_MIN_ALPHA = 0.55
_MAX_ALPHA = 1.0
_OFFSET_LIMIT = 4000
_ICON_POS_LIMIT = 32000  # 多屏坐标可能远超单屏尺寸


def _coerce_alpha(value):
    try:
        alpha = float(value)
    except (TypeError, ValueError):
        return DEFAULT_CONFIG['overlay_alpha']
    if alpha != alpha:  # NaN
        return DEFAULT_CONFIG['overlay_alpha']
    return min(_MAX_ALPHA, max(_MIN_ALPHA, alpha))


def _coerce_offset(value):
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return list(DEFAULT_CONFIG['overlay_offset'])
    try:
        dx, dy = int(value[0]), int(value[1])
    except (TypeError, ValueError):
        return list(DEFAULT_CONFIG['overlay_offset'])
    clamp = lambda v: max(-_OFFSET_LIMIT, min(_OFFSET_LIMIT, v))  # noqa: E731
    return [clamp(dx), clamp(dy)]


def _coerce_icon_pos(value):
    """收起图标坐标：非法值回退为 None（自动贴边）"""
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    try:
        x, y = int(value[0]), int(value[1])
    except (TypeError, ValueError):
        return None
    clamp = lambda v: max(-_ICON_POS_LIMIT, min(_ICON_POS_LIMIT, v))  # noqa: E731
    return [clamp(x), clamp(y)]


def load_config(path=None):
    """读取配置；不存在或损坏时返回默认配置副本"""
    config_path = Path(path) if path is not None else CONFIG_PATH
    config = dict(DEFAULT_CONFIG)
    config['overlay_offset'] = list(DEFAULT_CONFIG['overlay_offset'])

    try:
        raw = json.loads(config_path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return config
    if not isinstance(raw, dict):
        return config

    if isinstance(raw.get('overlay_enabled'), bool):
        config['overlay_enabled'] = raw['overlay_enabled']
    if isinstance(raw.get('overlay_auto_query'), bool):
        config['overlay_auto_query'] = raw['overlay_auto_query']
    if 'overlay_alpha' in raw:
        config['overlay_alpha'] = _coerce_alpha(raw['overlay_alpha'])
    if 'overlay_offset' in raw:
        config['overlay_offset'] = _coerce_offset(raw['overlay_offset'])
    if isinstance(raw.get('overlay_collapsed'), bool):
        config['overlay_collapsed'] = raw['overlay_collapsed']
    if 'overlay_icon_pos' in raw:
        config['overlay_icon_pos'] = _coerce_icon_pos(raw['overlay_icon_pos'])
    if isinstance(raw.get('hotkey_enabled'), bool):
        config['hotkey_enabled'] = raw['hotkey_enabled']
    if isinstance(raw.get('hotkey'), str) and raw['hotkey'].strip():
        config['hotkey'] = raw['hotkey'].strip()[:40]
    return config


def save_config(config, path=None):
    """原子写入配置，失败时静默返回 False（不影响主流程）"""
    config_path = Path(path) if path is not None else CONFIG_PATH
    payload = {
        key: config.get(key, default)
        for key, default in DEFAULT_CONFIG.items()
    }
    payload['overlay_alpha'] = _coerce_alpha(payload['overlay_alpha'])
    payload['overlay_offset'] = _coerce_offset(payload['overlay_offset'])
    payload['overlay_icon_pos'] = _coerce_icon_pos(payload.get('overlay_icon_pos'))
    try:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = config_path.with_name(config_path.name + '.tmp')
        tmp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(tmp_path, config_path)
        return True
    except OSError:
        return False
