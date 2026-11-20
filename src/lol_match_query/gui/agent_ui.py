"""AgentUIMixin：AgentQuay 接入（在 service / 客户端方法上加 @agent_tool 注解）。

设计：
- 在 MatchMonitorService / ViolationClient 的方法上直接加 @agent_tool 注解
- AgentUIMixin 负责创建 AgentQuayClient、注册工具、后台线程运行 asyncio loop
- 危险操作通过主线程确认对话框征得用户同意后再执行；Agent 不可用时自动降级
"""
import asyncio
import json
import threading
import time
from tkinter import messagebox


class AgentUIMixin:
    """为 MatchQueryGUI 提供 AgentQuay 接入的混入类"""

    APP_ID = 'lol-match-query'
    APP_NAME = 'LoLMatchQuery'
    CONFIRM_TIMEOUT = 60.0  # 等待用户确认的最长秒数，超时按拒绝处理

    def start_agent_service(self):
        """创建 AgentQuayClient、注册工具，并在后台线程运行 asyncio loop"""
        self.agent_client = None
        self._agent_loop = None
        self._agent_thread = None
        self._agent_shutting_down = False

        # 延迟导入：AgentQuay 不可用时只禁用 AI 功能，不影响主程序启动
        try:
            from agentquay import AgentQuayClient
        except Exception as e:
            self._agent_unavailable(f'SDK 导入失败: {e}')
            return

        try:
            self.agent_client = AgentQuayClient(
                app_id=self.APP_ID,
                app_name=self.APP_NAME,
                auto_spawn_bridge=True,  # 零安装：没装 Bridge 时自动拉起内嵌二进制
                on_confirm=self._confirm_agent_action,  # 危险操作需用户确认
            )
            # 直接注册 service，方法上已加 @agent_tool 注解；
            # LCU 底层客户端不再直接暴露给 Agent
            self.agent_client.register_tools(self.match_service)
            self.agent_client.register_tools(self.violation_client)
        except Exception as e:
            self.agent_client = None
            self._agent_unavailable(f'初始化失败: {e}')
            return

        client = self.agent_client

        def run_loop():
            loop = asyncio.new_event_loop()
            self._agent_loop = loop
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(client.connect())
                self._set_agent_label('Agent: 已接入', self.COLORS['green'])
                loop.run_forever()
            except Exception as e:
                self._on_log(f'AgentQuay 服务异常: {e}')
                self._set_agent_label('Agent: 异常', self.COLORS['red'])
            finally:
                try:
                    if not loop.is_closed():
                        loop.close()
                except Exception:
                    pass
                self._agent_loop = None

        self._agent_thread = threading.Thread(target=run_loop, daemon=True)
        self._agent_thread.start()

    def stop_agent_service(self):
        """优雅断开 AgentQuay 连接（停止 asyncio loop 并等待后台线程退出）"""
        self._agent_shutting_down = True
        client = getattr(self, 'agent_client', None)
        loop = getattr(self, '_agent_loop', None)
        thread = getattr(self, '_agent_thread', None)
        self.agent_client = None

        if client is not None:
            close = getattr(client, 'close', None)
            if close is not None:
                try:
                    result = close()
                    if asyncio.iscoroutine(result):
                        if loop is not None and loop.is_running():
                            asyncio.run_coroutine_threadsafe(result, loop).result(timeout=2)
                        else:
                            # 无法在已停止的 loop 上等待，关闭协程避免 "never awaited" 警告
                            result.close()
                except Exception as e:
                    self._on_log(f'关闭 Agent 连接失败: {e}')

        if loop is not None and not loop.is_closed():
            try:
                loop.call_soon_threadsafe(loop.stop)
            except Exception:
                pass

        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=2)
        self._agent_loop = None
        self._agent_thread = None

    # ===== 危险操作确认 =====

    def _confirm_agent_action(self, msg, args=None):
        """Agent 工具确认回调（可能在工作线程调用）。

        在 Tk 主线程弹窗询问用户，并等待结果；关闭窗口或超时按拒绝处理。
        """
        if getattr(self, '_agent_shutting_down', False):
            return False

        # 回调本身就在主线程时直接弹窗，避免 after + Event 死锁
        if threading.current_thread() is threading.main_thread():
            return self._ask_agent_confirmation(msg, args)

        approved = {'value': False}
        done = threading.Event()

        def _ask():
            try:
                if self._agent_shutting_down:
                    approved['value'] = False
                else:
                    approved['value'] = self._ask_agent_confirmation(msg, args)
            finally:
                done.set()

        try:
            self.root.after(0, _ask)
        except Exception as e:
            self._on_log(f'调度 Agent 确认弹窗失败: {e}')
            return False

        deadline = time.monotonic() + self.CONFIRM_TIMEOUT
        while not done.is_set():
            if self._agent_shutting_down:
                return False
            if time.monotonic() >= deadline:
                self._on_log('Agent 操作确认超时，已按拒绝处理')
                return False
            done.wait(0.2)
        return approved['value']

    def _ask_agent_confirmation(self, msg, args):
        """在主线程弹出确认对话框，返回用户是否批准"""
        try:
            text = msg if isinstance(msg, str) else str(msg)
            if args:
                try:
                    args_text = json.dumps(args, ensure_ascii=False, indent=2, default=str)
                except Exception:
                    args_text = repr(args)
                if len(args_text) > 1500:
                    args_text = args_text[:1500] + '\n...（已截断）'
                text = f'{text}\n\n参数：\n{args_text}'
            return bool(messagebox.askyesno(
                'AI Agent 请求确认',
                f'AI Agent 请求执行以下操作：\n\n{text}\n\n是否允许？',
                parent=self.root
            ))
        except Exception as e:
            self._on_log(f'Agent 确认弹窗异常: {e}')
            return False

    # ===== 状态与降级 =====

    def _agent_unavailable(self, reason):
        """AgentQuay 不可用时降级：只记录日志并更新状态标签"""
        self._on_log(f'AgentQuay 不可用（AI Agent 功能已禁用）: {reason}')
        self._set_agent_label('Agent: 不可用', self.COLORS['text_secondary'])

    def _set_agent_label(self, text, color):
        """从任意线程安全地更新 Agent 状态标签"""
        try:
            self.root.after(0, lambda: self.agent_label.configure(text=text, text_color=color))
        except Exception:
            pass
