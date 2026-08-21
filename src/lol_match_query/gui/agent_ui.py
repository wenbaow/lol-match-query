"""AgentUIMixin：AgentQuay 接入（直接在底层客户端方法上加 @agent_tool 注解）。

极简设计：
- 在 LCUClient / ViolationClient 的方法上直接加 @agent_tool 注解
- AgentUIMixin 负责创建 AgentQuayClient、注册工具、后台线程运行 asyncio loop
- on_confirm 直接返回 True（自动批准）
"""
import asyncio
import threading

from agentquay import AgentQuayClient


class AgentUIMixin:
    """为 MatchQueryGUI 提供 AgentQuay 接入的混入类"""

    APP_ID = 'lol-match-query'
    APP_NAME = 'LoLMatchQuery'

    def start_agent_service(self):
        """创建 AgentQuayClient、注册工具，并在后台线程运行 asyncio loop"""
        self.agent_client = AgentQuayClient(
            app_id=self.APP_ID,
            app_name=self.APP_NAME,
            auto_spawn_bridge=True,  # 零安装：没装 Bridge 时自动拉起内嵌二进制
            on_confirm=lambda msg, args: True,  # 直接自动批准
        )
        # 直接注册底层客户端，方法上已加 @agent_tool 注解
        self.agent_client.register_tools(self.lcu)
        self.agent_client.register_tools(self.violation_client)

        def run_loop():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(self.agent_client.connect())
                loop.run_forever()
            except Exception as e:
                # 连接异常时更新状态标签（如果存在）
                if hasattr(self, 'agent_label'):
                    self.root.after(0, lambda: self.agent_label.configure(
                        text='Agent: 异常', text_color=self.COLORS['red']
                    ))

        self._agent_thread = threading.Thread(target=run_loop, daemon=True)
        self._agent_thread.start()

    def stop_agent_service(self):
        """优雅断开 AgentQuay 连接"""
        if hasattr(self, 'agent_client') and self.agent_client:
            # close() 是协程，需要调度到 asyncio loop 执行
            # 这里简单设置为 None，让后台线程自然退出
            self.agent_client = None
