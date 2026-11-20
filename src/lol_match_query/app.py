"""应用入口：初始化窗口并启动主循环。

注意：本文件是 PyInstaller 的入口脚本，打包后以 __main__ 执行，
因此使用绝对导入（其他包内模块保持相对导入）。
"""
import os
import sys
from pathlib import Path

import customtkinter as ctk

from lol_match_query import __app_title__, __version__
from lol_match_query.gui.app import MatchQueryGUI
from lol_match_query.logging_utils import get_logger, setup_logging


def _resolve_icon_path():
    """返回应用图标路径。

    兼容两种运行方式：
    - PyInstaller 打包后：图标被打入 sys._MEIPASS 根目录
    - 源码运行 / pip 安装后：图标位于包内 assets/ 下
    """
    if getattr(sys, 'frozen', False):
        return os.path.join(sys._MEIPASS, 'app_icon.ico')
    return str(Path(__file__).resolve().parent / 'assets' / 'app_icon.ico')


def main():
    setup_logging()
    get_logger().info('=== %s v%s 启动 ===', __app_title__, __version__)
    ctk.set_appearance_mode('dark')
    ctk.set_default_color_theme('dark-blue')
    root = ctk.CTk()
    root.title(__app_title__)
    icon_path = _resolve_icon_path()
    if os.path.exists(icon_path):
        root.iconbitmap(icon_path)
    root.geometry('780x760')
    root.minsize(560, 600)
    app = MatchQueryGUI(root)
    root.protocol('WM_DELETE_WINDOW', lambda: _on_close(root, app))
    root.mainloop()


def _on_close(root, app):
    """关闭窗口：先优雅断开 Agent 客户端，再销毁主窗口。"""
    try:
        app.stop_agent_service()
    except Exception:
        get_logger().exception('关闭 Agent 服务失败')
    get_logger().info('=== 应用退出 ===')
    root.destroy()


if __name__ == '__main__':
    main()
