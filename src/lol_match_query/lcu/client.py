"""LCU 传输层客户端。

只负责：
- 扫描客户端进程获取端口/token
- 带认证的 HTTP GET
- WebSocket 连接、原始 JSON API 事件转发
- gameflow-phase 兜底轮询

对局阶段状态机、缓存和面向 UI/Agent 的事件由
``services.match_monitor.MatchMonitorService`` 负责。
"""
import json
import ssl
import threading
import time

import requests
import urllib3

from .connection import create_ws_app, discover_lcu_credentials
from .events import GAMEFLOW_PHASE_URI, WS_OPEN_EVENT

urllib3.disable_warnings()


class LCUClient:
    """LCU 本地接口传输层（不持有对局业务状态）"""

    def __init__(self, log_callback=None):
        self.lcu_port = None
        self.lcu_token = None
        self.lcu_base_url = None
        self.running = False
        self.lock = threading.Lock()
        self.log_callback = log_callback
        # requests.Session 并非线程安全：WS/Timer/Agent 工具会并发请求，
        # 因此按线程各持有一个 Session
        self._session_local = threading.local()
        # WebSocket/轮询线程
        self.ws = None
        self.ws_thread = None
        self.phase_poll_thread = None
        # 运行代次：start/stop 时递增，旧线程据此自行退出
        self._run_token = 0
        self._ws_reconnect_fail_count = 0
        self._ws_opened_once = False
        # 原始事件回调：callback(uri, data, event_type)
        self._event_callback = None

    def _log(self, msg):
        if self.log_callback:
            self.log_callback(msg)

    def _emit(self, uri, data, event_type=''):
        callback = self._event_callback
        if callback is None:
            return
        try:
            callback(uri, data, event_type)
        except Exception as e:
            self._log(f'LCU事件回调异常({uri}): {type(e).__name__}: {e}')

    def _is_run_active(self, token=None):
        if not self.running:
            return False
        return token is None or token == self._run_token

    def is_connected(self):
        """当前是否已获得 LCU 端口与 token"""
        return bool(self.lcu_base_url and self.lcu_token)

    def _session(self):
        """获取当前线程独立的 requests.Session（LCU 使用自签名证书、禁用代理）"""
        session = getattr(self._session_local, 'session', None)
        if session is None:
            session = requests.Session()
            session.verify = False
            session.proxies = {}
            self._session_local.session = session
        return session

    def _lcu_get(self, path, timeout=3, **kwargs):
        return self._session().get(
            f'{self.lcu_base_url}{path}',
            auth=('riot', self.lcu_token),
            timeout=timeout,
            **kwargs
        )

    def get(self, path, timeout=3, **kwargs):
        """带 LCU 认证的 GET，返回 requests.Response"""
        return self._lcu_get(path, timeout=timeout, **kwargs)

    def find_client(self, force_refresh=False):
        """查找 LCU 客户端进程并刷新端口/token"""
        if self.lcu_port and not force_refresh:
            return True

        credentials = discover_lcu_credentials()
        if not credentials:
            return False

        self.lcu_port, self.lcu_token = credentials
        self.lcu_base_url = f'https://127.0.0.1:{self.lcu_port}'
        return True

    def start(self, event_callback):
        """启动连接线程；event_callback(uri, data, event_type) 接收原始事件"""
        with self.lock:
            self._event_callback = event_callback
            if self.running:
                return True
            self.running = True
            self._run_token += 1
            token = self._run_token
            self._ws_reconnect_fail_count = 0
            self._ws_opened_once = False

        try:
            found = self.find_client()
        except Exception as e:
            self._log(f'查找LCU进程失败: {type(e).__name__}: {e}')
            found = False

        if not found:
            with self.lock:
                self.running = False
                self._run_token += 1
            return False

        self.ws_thread = threading.Thread(
            target=self._ws_loop, args=(token,), daemon=True)
        self.ws_thread.start()
        self.phase_poll_thread = threading.Thread(
            target=self._phase_poll_loop, args=(token,), daemon=True)
        self.phase_poll_thread.start()
        return True

    def stop(self):
        with self.lock:
            self.running = False
            self._run_token += 1
        self._event_callback = None
        ws = self.ws
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass
        self.ws = None  # 立即失效旧连接的回调

        current = threading.current_thread()
        for thread, timeout in ((self.ws_thread, 3), (self.phase_poll_thread, 0.5)):
            if thread is not None and thread.is_alive() and thread is not current:
                thread.join(timeout=timeout)
        self.ws_thread = None
        self.phase_poll_thread = None

    # ===== WebSocket =====

    def _on_ws_open(self, ws):
        if self.ws is not ws or not self.running:
            return
        self._ws_reconnect_fail_count = 0
        reconnect = self._ws_opened_once
        self._ws_opened_once = True
        self._log('WebSocket已连接，订阅 OnJsonApiEvent ...')
        ws.send(json.dumps([5, "OnJsonApiEvent"]))
        # 通知服务层：首次连接或重连。重连时服务层会重置阶段哨兵。
        self._emit(WS_OPEN_EVENT, {'reconnect': reconnect}, 'Open')

    def _on_ws_message(self, ws, message):
        """解析 WAMP 消息并转发原始 uri/data/eventType"""
        if self.ws is not ws or not self.running:
            return
        try:
            msg = json.loads(message)
            if not isinstance(msg, list) or len(msg) < 3:
                return
            if msg[1] != "OnJsonApiEvent":
                return
            payload = msg[2]
            if not isinstance(payload, dict):
                return
            self._emit(
                payload.get("uri", ""),
                payload.get("data"),
                payload.get("eventType", ""),
            )
        except Exception as e:
            self._log(f'解析WS消息失败: {e}')

    def _on_ws_error(self, ws, error):
        if self.ws is not ws:
            return
        self._log(f'WebSocket错误: {error}')

    def _on_ws_close(self, ws, close_status_code, close_msg):
        if self.ws is not ws:
            return
        self._log(f'WebSocket关闭: code={close_status_code} msg={close_msg}')

    def _ws_loop(self, token):
        """WebSocket 主循环，带自动重连"""
        while self._is_run_active(token):
            if not self.lcu_port:
                if not self.find_client():
                    self._log('未找到LCU进程，等待重试...')
                    time.sleep(2)
                    continue

            url = f'wss://127.0.0.1:{self.lcu_port}/'
            self._log(f'正在连接WebSocket: {url}')

            app = create_ws_app(self.lcu_port, self.lcu_token, {
                'on_open': self._on_ws_open,
                'on_message': self._on_ws_message,
                'on_error': self._on_ws_error,
                'on_close': self._on_ws_close,
            })
            self.ws = app
            try:
                # 关闭证书校验（LCU 使用自签名证书）
                app.run_forever(
                    sslopt={"cert_reqs": ssl.CERT_NONE},
                    ping_interval=30,
                    ping_timeout=10,
                )
            except Exception as e:
                self._log(f'WebSocket运行异常: {e}')

            # 只清理自己创建的连接，避免旧线程退出时把重启后的新连接置空
            if self.ws is app:
                self.ws = None
            if not self._is_run_active(token):
                break
            self._log('WebSocket断开，2秒后重连...')
            time.sleep(2)
            # 若连续3次重连失败，则重置连接信息重新查找LCU进程
            self._ws_reconnect_fail_count += 1
            if self._ws_reconnect_fail_count >= 3:
                self._ws_reconnect_fail_count = 0
                self.lcu_port = None
                self.lcu_token = None
                self.lcu_base_url = None

    def _phase_poll_loop(self, token):
        """兜底轮询 gameflow-phase：WS 推送可能丢失（尤其选人→进游戏过渡期）"""
        while self._is_run_active(token):
            if self.lcu_port and self.lcu_base_url:
                try:
                    resp = self._lcu_get(GAMEFLOW_PHASE_URI, timeout=3)
                    if resp.status_code == 200:
                        phase = resp.text.strip().strip('"')
                        self._emit(GAMEFLOW_PHASE_URI, phase, 'Poll')
                except Exception:
                    pass
            time.sleep(5.0)
