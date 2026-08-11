"""应用入口：初始化窗口并启动主循环。

注意：本文件是 PyInstaller 的入口脚本，打包后以 __main__ 执行，
因此使用绝对导入（其他包内模块保持相对导入）。
"""
import os
import sys
from pathlib import Path

import customtkinter as ctk

from lol_match_query import __app_title__
from lol_match_query.gui.app import MatchQueryGUI


def _resolve_icon_path():
    """返回应用图标路径。

    兼容两种运行方式：
    - PyInstaller 打包后：图标被打入 sys._MEIPASS 根目录
    - 源码运行：图标位于项目根目录的 assets/ 下
    """
    if getattr(sys, 'frozen', False):
        return os.path.join(sys._MEIPASS, 'app_icon.ico')
    # src/lol_match_query/app.py -> 项目根目录
    project_root = Path(__file__).resolve().parent.parent.parent
    return str(project_root / 'assets' / 'app_icon.ico')


def main():
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
    root.mainloop()


if __name__ == '__main__':
    main()
