"""LCU 连接辅助：进程发现与 WebSocket 客户端构造。"""
import base64
import re

import psutil
import websocket


def discover_lcu_credentials():
    """扫描 LeagueClientUx 进程，返回 (port, token)；未找到返回 None"""
    for proc in psutil.process_iter(['name', 'cmdline']):
        try:
            if (proc.name() or '').lower() != 'leagueclientux.exe':
                continue
            cmdline = ' '.join(proc.cmdline())
            # 只匹配 --app-port，不匹配 riotclient-app-port
            port_match = re.search(r'--app-port=(\d+)', cmdline)
            token_match = re.search(r'--remoting-auth-token=([^\s]+)', cmdline)
            if port_match and token_match:
                return port_match.group(1), token_match.group(1)
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            continue
    return None


def create_ws_app(port, token, callbacks=None):
    """创建带 WAMP 子协议与 Basic Auth 的 WebSocketApp"""
    auth = base64.b64encode(f'riot:{token}'.encode()).decode()
    options = {
        'subprotocols': ['wamp'],
        'header': [f'Authorization: Basic {auth}'],
    }
    if callbacks:
        options.update(callbacks)
    return websocket.WebSocketApp(f'wss://127.0.0.1:{port}/', **options)
