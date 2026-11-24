"""全局热键字符串解析测试。"""
from lol_match_query.gui.hotkey import (
    MOD_ALT,
    MOD_CONTROL,
    MOD_SHIFT,
    MOD_WIN,
    format_hotkey,
    parse_hotkey,
)


def test_parse_hotkey():
    assert parse_hotkey('ctrl+alt+q') == (MOD_CONTROL | MOD_ALT, ord('Q'))
    assert parse_hotkey('CTRL + SHIFT + F1') == (MOD_CONTROL | MOD_SHIFT, 0x70)
    assert parse_hotkey('win+alt+9') == (MOD_WIN | MOD_ALT, ord('9'))
    assert parse_hotkey('ctrl+alt+q+shift') == (
        MOD_CONTROL | MOD_ALT | MOD_SHIFT, ord('Q'))


def test_parse_hotkey_invalid():
    assert parse_hotkey(None) is None
    assert parse_hotkey('') is None
    assert parse_hotkey('q') is None            # 必须有修饰键
    assert parse_hotkey('ctrl') is None         # 没有主键
    assert parse_hotkey('ctrl+q+w') is None     # 两个主键
    assert parse_hotkey('ctrl+alt+?') is None   # 不支持的按键
    assert parse_hotkey('ctrl+alt+') is None


def test_format_hotkey():
    assert format_hotkey('ctrl+alt+q') == 'Ctrl+Alt+Q'
    assert format_hotkey('shift+ctrl+f12') == 'Ctrl+Shift+F12'
    assert format_hotkey('ctrl+alt+q+shift') == 'Ctrl+Alt+Shift+Q'
    assert format_hotkey('bad') == 'bad'
    assert format_hotkey(None) == ''
