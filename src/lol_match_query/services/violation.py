"""违规标记系统 API 客户端。

对接自定义违规标记后端服务，提供举报、批量状态查询、次数与记录查询能力。
"""
import requests
from agentquay import agent_tool


class ViolationClient:
    """违规标记系统API客户端"""
    BASE_URL = 'https://ffmy.top/api'

    VIOLATION_TYPES = {
        1: '挂机', 2: '送人头', 3: '言语辱骂', 4: '伤害队友',
        5: '不当言论', 6: '使用外挂', 7: '使用脚本', 8: '代练',
        9: '恶意掉分', 10: '中途退出', 11: '消极比赛', 12: '骚扰行为',
        13: '仇恨言论', 14: '刷屏', 15: '冒充他人'
    }

    def __init__(self, log_callback=None):
        self.session = requests.Session()
        self.session.verify = False
        self.session.proxies = {}
        self.log_callback = log_callback

    def _log(self, msg):
        if self.log_callback:
            self.log_callback(msg)

    @agent_tool("report_violation",
                description="举报玩家违规行为（危险操作，需要用户确认后才会提交）",
                requires_confirmation=True)
    def report_violation(self, reporter_puuid, platform_id, platform_name,
                         game_id, reported_puuid, violation_type):
        """举报玩家违规行为 POST /lol/violation/report"""
        url = f'{self.BASE_URL}/lol/violation/report'
        payload = {
            'reporterPuuid': reporter_puuid,
            'platformId': platform_id,
            'platformName': platform_name,
            'gameId': game_id,
            'reportedPuuid': reported_puuid,
            'violationType': violation_type
        }
        try:
            resp = self.session.post(url, json=payload, timeout=10)
            return resp.json()
        except Exception as e:
            self._log(f'举报违规请求异常: {e}')
            return {'code': 500, 'message': f'请求异常: {e}', 'data': None}

    def batch_query_status(self, players):
        """批量查询对局中所有玩家的违规状态 POST /lol/violation/status/batch"""
        url = f'{self.BASE_URL}/lol/violation/status/batch'
        payload = {'players': players}
        try:
            resp = self.session.post(url, json=payload, timeout=10)
            return resp.json()
        except Exception as e:
            self._log(f'批量查询违规状态异常: {e}')
            return {'code': 500, 'message': f'请求异常: {e}', 'data': None}

    @agent_tool("query_violation_count", description="查询指定玩家的违规记录总次数")
    def query_count(self, puuid, platform_id):
        """查询单个玩家违规次数 GET /lol/violation/count"""
        url = f'{self.BASE_URL}/lol/violation/count'
        params = {'puuid': puuid, 'platformId': platform_id}
        try:
            resp = self.session.get(url, params=params, timeout=10)
            return resp.json()
        except Exception as e:
            self._log(f'查询违规次数异常: {e}')
            return {'code': 500, 'message': f'请求异常: {e}', 'data': None}

    def query_records(self, puuid, platform_id):
        """查询玩家违规记录列表 GET /lol/violation/records"""
        url = f'{self.BASE_URL}/lol/violation/records'
        params = {'puuid': puuid, 'platformId': platform_id}
        try:
            resp = self.session.get(url, params=params, timeout=10)
            return resp.json()
        except Exception as e:
            self._log(f'查询违规记录异常: {e}')
            return {'code': 500, 'message': f'请求异常: {e}', 'data': None}

    @agent_tool("get_violation_types", description="获取可选的违规类型代码与名称对照表（report_violation 的 violation_type 参数用）")
    def get_violation_types(self):
        """获取违规类型代码对照表"""
        return [{'code': code, 'name': name} for code, name in self.VIOLATION_TYPES.items()]
