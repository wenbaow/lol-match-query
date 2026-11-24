"""全局热键：Windows RegisterHotKey 封装 + 热键字符串解析。

RegisterHotKey 是系统级 API：不装键盘钩子、不注入进程，只把按键事件投递到
本进程的独立消息循环线程，再转回 Tk 主线程。非 Windows 平台直接不可用。
"""
import ctypes
import logging
import os
import threading
from ctypes import wintypes

LOGGER = logging.getLogger('lol_match_query')

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

HOTKEY_ID = 0x4C4D  # 进程内唯一 id（LM）

_VK_BY_NAME = {}
_NAME_BY_VK = {}

for _code in range(0x41, 0x5B):          # A-Z
    _VK_BY_NAME[chr(_code).lower()] = _code
    _NAME_BY_VK[_code] = chr(_code)
for _code in range(0x30, 0x3A):          # 0-9
    _VK_BY_NAME[chr(_code)] = _code
    _NAME_BY_VK[_code] = chr(_code)
for _index in range(1, 13):              # F1-F12
    _VK_BY_NAME[f'f{_index}'] = 0x70 + _index - 1
    _NAME_BY_VK[0x70 + _index - 1] = f'F{_index}'


def parse_hotkey(spec):
    """'ctrl+alt+q' → (修饰键掩码, 虚拟键码)；非法或缺少修饰键返回 None"""
    if not isinstance(spec, str) or not spec.strip():
        return None
    parts = [part.strip().lower() for part in spec.replace(' ', '').split('+')]
    parts = [part for part in parts if part]
    if len(parts) < 2:
        return None

    mods = 0
    key = None
    for part in parts:
        if part in ('ctrl', 'control'):
            mods |= MOD_CONTROL
        elif part == 'alt':
            mods |= MOD_ALT
        elif part == 'shift':
            mods |= MOD_SHIFT
        elif part in ('win', 'super', 'meta'):
            mods |= MOD_WIN
        elif key is None and part in _VK_BY_NAME:
            key = part
        else:
            return None
    if key is None or mods == 0:
        return None
    return mods, _VK_BY_NAME[key]


def format_hotkey(spec):
    """'ctrl+alt+q' → 'Ctrl+Alt+Q'（无法解析时原样返回）"""
    parsed = parse_hotkey(spec)
    if not parsed:
        return str(spec or '')
    mods, vk = parsed
    names = []
    if mods & MOD_CONTROL:
        names.append('Ctrl')
    if mods & MOD_ALT:
        names.append('Alt')
    if mods & MOD_SHIFT:
        names.append('Shift')
    if mods & MOD_WIN:
        names.append('Win')
    names.append(_NAME_BY_VK.get(vk, '?'))
    return '+'.join(names)


class HotkeyManager:
    """在独立线程里注册全局热键并跑消息循环，回调时通知调用方"""

    def __init__(self, spec, callback):
        self.spec = spec
        self.callback = callback
        self.available = False
        self.error = ''
        self._thread = None
        self._thread_id = 0
        self._ready = threading.Event()
        self._mods = 0
        self._vk = 0

    @property
    def thread_id(self):
        return self._thread_id

    def start(self):
        """注册热键；返回是否成功（失败原因见 error）"""
        if os.name != 'nt':
            self.error = '全局热键仅支持 Windows'
            return False
        parsed = parse_hotkey(self.spec)
        if parsed is None:
            self.error = f'热键格式不正确: {self.spec}'
            return False
        self._mods, self._vk = parsed
        self._thread = threading.Thread(
            target=self._run, name='lolmq-hotkey', daemon=True)
        self._thread.start()
        self._ready.wait(1.0)
        return self.available

    def stop(self):
        """请求消息循环退出（线程退出时会注销热键）"""
        if not self._thread_id:
            return
        try:
            ctypes.windll.user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        except Exception:
            LOGGER.exception('停止热键线程失败')

    def _run(self):
        try:
            self._loop()
        except Exception as exc:
            self.error = f'热键线程异常: {exc}'
            LOGGER.exception('热键线程异常')
            self._ready.set()

    def _loop(self):
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        user32.RegisterHotKey.argtypes = (
            wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT)
        user32.RegisterHotKey.restype = wintypes.BOOL
        user32.UnregisterHotKey.argtypes = (wintypes.HWND, ctypes.c_int)
        user32.UnregisterHotKey.restype = wintypes.BOOL
        user32.GetMessageW.argtypes = (
            ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT)
        user32.GetMessageW.restype = ctypes.c_int
        user32.PeekMessageW.argtypes = (
            ctypes.POINTER(wintypes.MSG), wintypes.HWND,
            wintypes.UINT, wintypes.UINT, wintypes.UINT)
        user32.PeekMessageW.restype = wintypes.BOOL
        user32.PostThreadMessageW.argtypes = (
            wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
        user32.PostThreadMessageW.restype = wintypes.BOOL
        kernel32.GetCurrentThreadId.restype = wintypes.DWORD

        self._thread_id = int(kernel32.GetCurrentThreadId())
        message = wintypes.MSG()
        # 先创建线程消息队列，再注册热键（WM_HOTKEY 会投递到该队列）
        user32.PeekMessageW(ctypes.byref(message), None, 0, 0, 0)

        if not user32.RegisterHotKey(
                None, HOTKEY_ID, self._mods | MOD_NOREPEAT, self._vk):
            self.error = (f'热键 {format_hotkey(self.spec)} 注册失败'
                          '（可能已被其它程序占用）')
            LOGGER.warning(self.error)
            self._ready.set()
            return

        self.available = True
        self._ready.set()
        try:
            while True:
                result = user32.GetMessageW(ctypes.byref(message), None, 0, 0)
                if result <= 0:
                    break
                if (message.message == WM_HOTKEY
                        and int(message.wParam) == HOTKEY_ID):
                    try:
                        self.callback()
                    except Exception:
                        LOGGER.exception('热键回调异常')
        finally:
            user32.UnregisterHotKey(None, HOTKEY_ID)
            self.available = False
