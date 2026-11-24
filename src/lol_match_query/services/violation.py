"""违规标记系统 API 客户端。

对接自定义违规标记后端服务，提供举报、批量状态查询、次数与记录查询能力。
每次请求使用独立连接，天然支持多线程调用（GUI 后台线程并发）。
"""
import requests


class ViolationClient:
    """违规标记系统API客户端"""
    BASE_URL = 'https://ffmy.top/api'
    TIMEOUT = 10

    VIOLATION_TYPES = {
        1: '挂机', 2: '送人头', 3: '言语辱骂', 4: '伤害队友',
        5: '不当言论', 6: '使用外挂', 7: '使用脚本', 8: '代练',
        9: '恶意掉分', 10: '中途退出', 11: '消极比赛', 12: '骚扰行为',
        13: '仇恨言论', 14: '刷屏', 15: '冒充他人'
    }

    def __init__(self, log_callback=None):
        self.log_callback = log_callback

    def _log(self, msg):
        if self.log_callback:
            self.log_callback(msg)

    def _request(self, method, path, **kwargs):
        """发送单次请求并解析 JSON；失败统一返回 code=500 结构"""
        url = f'{self.BASE_URL}{path}'
        try:
            # 不复用 Session：requests.Session 并非线程安全，而本客户端会被多个线程调用
            resp = requests.request(
                method, url, timeout=self.TIMEOUT, proxies={}, **kwargs
            )
            try:
                return resp.json()
            except ValueError:
                return {
                    'code': resp.status_code or 500,
                    'message': f'服务端返回非JSON响应 (HTTP {resp.status_code})',
                    'data': None,
                }
        except Exception as e:
            self._log(f'违规接口请求异常({path}): {e}')
            return {'code': 500, 'message': f'请求异常: {e}', 'data': None}

    def report_violation(self, reporter_puuid, platform_id, platform_name,
                         game_id, reported_puuid, violation_type):
        """举报玩家违规行为 POST /lol/violation/report"""
        payload = {
            'reporterPuuid': reporter_puuid,
            'platformId': platform_id,
            'platformName': platform_name,
            'gameId': game_id,
            'reportedPuuid': reported_puuid,
            'violationType': violation_type
        }
        return self._request('POST', '/lol/violation/report', json=payload)

    def batch_query_status(self, players):
        """批量查询对局中所有玩家的违规状态 POST /lol/violation/status/batch"""
        return self._request('POST', '/lol/violation/status/batch',
                             json={'players': players})

    def query_count(self, puuid, platform_id):
        """查询单个玩家违规次数 GET /lol/violation/count"""
        return self._request('GET', '/lol/violation/count',
                             params={'puuid': puuid, 'platformId': platform_id})

    def query_records(self, puuid, platform_id):
        """查询玩家违规记录列表 GET /lol/violation/records"""
        return self._request('GET', '/lol/violation/records',
                             params={'puuid': puuid, 'platformId': platform_id})

    def get_violation_types(self):
        """获取违规类型代码对照表"""
        return [{'code': code, 'name': name} for code, name in self.VIOLATION_TYPES.items()]
