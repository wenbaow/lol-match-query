"""Win32 原生窗口辅助：定位英雄联盟客户端 / 游戏窗口。

只在 Windows 上执行实际调用；其他平台所有查询返回空值，便于单元测试与
在 CI（Linux）上导入而不报错。

窗口识别优先用窗口类名（客户端 RCLIENT / 游戏 RiotWindowClass），
类名匹配不到时回退到进程名（LeagueClientUx.exe / League of Legends.exe），
避免客户端版本更新改类名导致悬浮层失效。
"""
import ctypes
import os
import time
from ctypes import wintypes

IS_WINDOWS = os.name == 'nt'

CLIENT_CLASS_NAMES = frozenset({'rclient'})
GAME_CLASS_NAMES = frozenset({'riotwindowclass'})
CLIENT_PROCESS_NAMES = frozenset({'leagueclientux.exe'})
GAME_PROCESS_NAMES = frozenset({'league of legends.exe'})

# GetAncestor 的 GA_ROOT：取顶层父窗口
_GA_ROOT = 2
# MonitorFromWindow 的 MONITOR_DEFAULTTONEAREST
_MONITOR_DEFAULTTONEAREST = 2
# 窗口扩展样式：不抢焦点 / 不进入 Alt-Tab
_GWL_EXSTYLE = -20
_WS_EX_TOOLWINDOW = 0x00000080
_WS_EX_NOACTIVATE = 0x08000000

# 进程名回退结果的缓存：避免每 250ms 都遍历一次进程列表
_FALLBACK_TTL = 3.0
_FALLBACK_CACHE = {}

_USER32 = None


class _MONITORINFO(ctypes.Structure):
    _fields_ = [
        ('cbSize', wintypes.DWORD),
        ('rcMonitor', wintypes.RECT),
        ('rcWork', wintypes.RECT),
        ('dwFlags', wintypes.DWORD),
    ]


def _u32():
    """惰性初始化 user32 并声明函数原型（64 位下句柄必须按指针返回）"""
    global _USER32
    if _USER32 is not None:
        return _USER32

    u32 = ctypes.windll.user32
    u32.GetClassNameW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
    u32.GetClassNameW.restype = ctypes.c_int
    u32.GetWindowRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
    u32.GetWindowRect.restype = wintypes.BOOL
    u32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
    u32.GetWindowThreadProcessId.restype = wintypes.DWORD
    u32.IsWindow.argtypes = (wintypes.HWND,)
    u32.IsWindow.restype = wintypes.BOOL
    u32.IsWindowVisible.argtypes = (wintypes.HWND,)
    u32.IsWindowVisible.restype = wintypes.BOOL
    u32.IsIconic.argtypes = (wintypes.HWND,)
    u32.IsIconic.restype = wintypes.BOOL
    u32.GetForegroundWindow.restype = wintypes.HWND
    u32.GetAncestor.argtypes = (wintypes.HWND, wintypes.UINT)
    u32.GetAncestor.restype = wintypes.HWND
    u32.GetWindowLongW.argtypes = (wintypes.HWND, ctypes.c_int)
    u32.GetWindowLongW.restype = ctypes.c_long
    u32.SetWindowLongW.argtypes = (wintypes.HWND, ctypes.c_int, ctypes.c_long)
    u32.SetWindowLongW.restype = ctypes.c_long
    u32.MonitorFromWindow.argtypes = (wintypes.HWND, wintypes.DWORD)
    u32.MonitorFromWindow.restype = ctypes.c_void_p
    u32.MonitorFromPoint.argtypes = (wintypes.POINT, wintypes.DWORD)
    u32.MonitorFromPoint.restype = ctypes.c_void_p
    u32.GetCursorPos.argtypes = (ctypes.POINTER(wintypes.POINT),)
    u32.GetCursorPos.restype = wintypes.BOOL
    u32.GetMonitorInfoW.argtypes = (ctypes.c_void_p, ctypes.POINTER(_MONITORINFO))
    u32.GetMonitorInfoW.restype = wintypes.BOOL

    _USER32 = u32
    return u32


def _class_name(hwnd):
    buffer = ctypes.create_unicode_buffer(256)
    length = _u32().GetClassNameW(hwnd, buffer, len(buffer))
    return buffer.value if length else ''


def _window_pid(hwnd):
    pid = wintypes.DWORD()
    _u32().GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value)


def window_rect(hwnd):
    """窗口外框矩形 → (x, y, w, h)，失败返回 None"""
    if not IS_WINDOWS or not hwnd:
        return None
    rect = wintypes.RECT()
    if not _u32().GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    return (rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top)


def is_window(hwnd):
    return bool(IS_WINDOWS and hwnd and _u32().IsWindow(hwnd))


def is_visible(hwnd):
    return bool(IS_WINDOWS and hwnd and _u32().IsWindowVisible(hwnd))


def is_minimized(hwnd):
    return bool(IS_WINDOWS and hwnd and _u32().IsIconic(hwnd))


def foreground_window():
    """当前前台窗口句柄，失败返回 0"""
    if not IS_WINDOWS:
        return 0
    return int(_u32().GetForegroundWindow() or 0)


def toplevel_hwnd(widget):
    """Tk 控件 → 顶层窗口句柄（Toplevel 的 winfo_id 是内层窗口，需要取根祖先）"""
    if not IS_WINDOWS:
        return 0
    try:
        hwnd = _u32().GetAncestor(widget.winfo_id(), _GA_ROOT)
    except Exception:
        return 0
    return int(hwnd or 0)


def work_area(hwnd):
    """窗口所在显示器的工作区（不含任务栏）→ (left, top, right, bottom)"""
    if not IS_WINDOWS or not hwnd:
        return None
    monitor = _u32().MonitorFromWindow(hwnd, _MONITOR_DEFAULTTONEAREST)
    if not monitor:
        return None
    info = _MONITORINFO()
    info.cbSize = ctypes.sizeof(_MONITORINFO)
    if not _u32().GetMonitorInfoW(monitor, ctypes.byref(info)):
        return None
    rect = info.rcWork
    return (rect.left, rect.top, rect.right, rect.bottom)


def make_overlay_window(hwnd):
    """把窗口标记为悬浮层：不抢焦点、不进入 Alt-Tab，避免显示时打断客户端输入"""
    if not IS_WINDOWS or not hwnd:
        return False
    try:
        u32 = _u32()
        style = u32.GetWindowLongW(hwnd, _GWL_EXSTYLE)
        u32.SetWindowLongW(
            hwnd, _GWL_EXSTYLE, style | _WS_EX_TOOLWINDOW | _WS_EX_NOACTIVATE)
        return True
    except Exception:
        return False


def cursor_pos():
    """鼠标位置 → (x, y)，失败返回 None"""
    if not IS_WINDOWS:
        return None
    point = wintypes.POINT()
    if not _u32().GetCursorPos(ctypes.byref(point)):
        return None
    return int(point.x), int(point.y)


def work_area_at_point(x, y):
    """指定坐标所在显示器的工作区 → (left, top, right, bottom)"""
    if not IS_WINDOWS:
        return None
    monitor = _u32().MonitorFromPoint(wintypes.POINT(int(x), int(y)),
                                      _MONITOR_DEFAULTTONEAREST)
    if not monitor:
        return None
    info = _MONITORINFO()
    info.cbSize = ctypes.sizeof(_MONITORINFO)
    if not _u32().GetMonitorInfoW(monitor, ctypes.byref(info)):
        return None
    rect = info.rcWork
    return (rect.left, rect.top, rect.right, rect.bottom)


def _enum_windows(class_names=None, pids=None):
    """枚举匹配类名或进程的可见顶层窗口 → [(hwnd, rect), ...]"""
    if not IS_WINDOWS or (not class_names and not pids):
        return []

    u32 = _u32()
    found = []
    callback_type = ctypes.WINFUNCTYPE(
        wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def _callback(hwnd, _lparam):
        try:
            if not u32.IsWindowVisible(hwnd):
                return True
            matched = bool(class_names) and _class_name(hwnd).lower() in class_names
            if not matched and pids and _window_pid(hwnd) in pids:
                matched = True
            if matched:
                rect = window_rect(hwnd)
                if rect and rect[2] > 1 and rect[3] > 1:
                    found.append((hwnd, rect))
        except Exception:
            # 单个窗口查询失败不影响整体枚举
            pass
        return True

    callback = callback_type(_callback)
    u32.EnumWindows.argtypes = (callback_type, wintypes.LPARAM)
    u32.EnumWindows.restype = wintypes.BOOL
    u32.EnumWindows(callback, 0)
    return found


def _process_pids(process_names):
    try:
        import psutil
    except ImportError:
        return set()

    pids = set()
    for proc in psutil.process_iter(['name']):
        try:
            if (proc.info.get('name') or '').lower() in process_names:
                pids.add(proc.pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return pids


def _find_by_process(process_names, cache_key):
    """类名匹配失败时按进程名找窗口（带 3 秒缓存，避免频繁遍历进程）"""
    now = time.monotonic()
    cached = _FALLBACK_CACHE.get(cache_key)
    if cached and now - cached[0] < _FALLBACK_TTL:
        hwnd = cached[1]
        rect = window_rect(hwnd)
        if rect and is_visible(hwnd):
            return hwnd, rect

    pids = _process_pids(process_names)
    if not pids:
        _FALLBACK_CACHE.pop(cache_key, None)
        return None

    candidates = _enum_windows(pids=pids)
    if not candidates:
        return None
    hwnd, rect = max(candidates, key=lambda item: item[1][2] * item[1][3])
    _FALLBACK_CACHE[cache_key] = (now, hwnd)
    return hwnd, rect


def _find_target(class_names, process_names, cache_key):
    windows = _enum_windows(class_names=class_names)
    if windows:
        return max(windows, key=lambda item: item[1][2] * item[1][3])
    return _find_by_process(process_names, cache_key)


def find_client_window():
    """英雄联盟客户端主窗口 → (hwnd, rect) 或 None"""
    return _find_target(CLIENT_CLASS_NAMES, CLIENT_PROCESS_NAMES, 'client')


def find_game_window():
    """英雄联盟游戏窗口 → (hwnd, rect) 或 None"""
    return _find_target(GAME_CLASS_NAMES, GAME_PROCESS_NAMES, 'game')
