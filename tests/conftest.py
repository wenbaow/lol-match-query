"""测试环境最小依赖桩。

CI 只安装 pytest/ruff，不安装运行时依赖；service 模块顶层的
@agent_tool 需要一个可用的 agentquay 模块。真实环境已安装时使用真实包。
"""
import sys
import types

try:
    import agentquay  # noqa: F401
except ImportError:
    _module = types.ModuleType('agentquay')

    def _agent_tool(*args, **kwargs):
        def decorator(func):
            return func
        return decorator

    _module.agent_tool = _agent_tool
    sys.modules['agentquay'] = _module
