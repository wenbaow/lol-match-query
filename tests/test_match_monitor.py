"""MatchMonitorService 行为测试（FakeTransport，无网络依赖）。"""
import threading
from collections import defaultdict

import pytest

from lol_match_query.lcu.events import (
    CHAMP_SELECT_URI,
    GAMEFLOW_PHASE_URI,
    REGION_LOCALE_URI,
    WS_OPEN_EVENT,
)
from lol_match_query.services.match_monitor import MatchMonitorService


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, text=''):
        self.status_code = status_code
        self._json = {} if json_data is None else json_data
        self.text = text
        self.url = 'https://127.0.0.1:0/mock'

    def json(self):
        return self._json


class FakeTransport:
    def __init__(self):
        self.responses = {}
        self.calls = []
        self.started = False
        self.stopped = False
        self.connected = True
        self.callback = None

    def start(self, event_callback):
        self.started = True
        self.callback = event_callback
        return True

    def stop(self):
        self.started = False
        self.stopped = True

    def is_connected(self):
        return self.connected

    def get(self, path, timeout=3, **kwargs):
        self.calls.append((path, kwargs))
        response = self.responses.get(path, FakeResponse())
        if callable(response):
            return response(path, kwargs)
        return response

    def emit(self, uri, data=None, event_type=''):
        assert self.callback is not None, 'transport not started'
        self.callback(uri, data, event_type)


def make_service():
    transport = FakeTransport()
    service = MatchMonitorService(lcu_client=transport)
    events = defaultdict(list)
    for name in service.EVENTS:
        service.subscribe(name, lambda *args, _name=name: events[_name].append(args))
    return service, transport, events


CHAMP_SELECT_SESSION = {
    'myTeam': [{
        'cellId': 0, 'gameName': '我', 'tagLine': '0001', 'championId': 103,
        'puuid': 'p1', 'assignedPosition': 'mid', 'spell1Id': 4, 'spell2Id': 14,
    }],
    'theirTeam': [{
        'cellId': 5, 'gameName': '敌', 'tagLine': '0002', 'championId': 64,
        'puuid': 'p2', 'assignedPosition': 'top', 'spell1Id': 4, 'spell2Id': 12,
    }],
    'localPlayerCellId': 0,
}


def test_start_stop_delegates_and_resets_phase():
    service, transport, _ = make_service()
    service._game_phase = 'ChampSelect'

    assert service.start() is True
    assert transport.started is True
    assert service._running is True
    assert service._game_phase is None

    service.stop()

    assert transport.stopped is True
    assert service._running is False
    assert service._game_phase is None


def test_start_failure_resets_running_state():
    class RaisingTransport(FakeTransport):
        def start(self, event_callback):
            raise RuntimeError('boom')

    service = MatchMonitorService(lcu_client=RaisingTransport())
    assert service.start() is False
    assert service._running is False


def test_subscribe_validates_event_and_log_event():
    service, _, events = make_service()

    service._log('hello')
    assert events['log'] == [('hello',)]

    with pytest.raises(ValueError):
        service.subscribe('not-an-event', lambda: None)


def test_lobby_phase_clears_caches_and_emits_clear():
    service, transport, events = make_service()
    service.start()
    service._puuid_cache = {'A': 'p1'}
    service._cached_game_id = '123'
    service._cached_bp_match_data = {'my_team': [], 'enemy_team': [], 'myself': None}

    transport.emit(GAMEFLOW_PHASE_URI, 'Lobby', 'Update')

    assert events['phase_changed'][-1] == ('Lobby',)
    assert events['display_cleared']
    assert service._puuid_cache == {}
    assert service._cached_game_id == ''
    assert service._cached_bp_match_data is None


def test_champ_select_event_updates_cache_and_sends_champion_for_ui():
    service, transport, events = make_service()
    service.start()
    service._current_summoner_puuid = 'p1'
    transport.responses['/lol-gameflow/v1/session'] = FakeResponse(json_data={'gameId': 0})

    transport.emit(CHAMP_SELECT_URI, CHAMP_SELECT_SESSION, 'Update')

    assert service._cached_bp_match_data['my_team'][0]['champion_id'] == 103
    # 选人阶段保留 champion_id，GUI 才能显示头像并在原卡片上更新
    assert events['match_updated'][-1][0]['my_team'][0]['champion_id'] == 103
    assert service._puuid_cache['我#0001'] == 'p1'
    assert service._cached_bp_match_data['myself']['role'] == '自己'


def test_phase_champ_select_fetches_session_over_http():
    service, transport, events = make_service()
    service.start()
    transport.responses[CHAMP_SELECT_URI] = FakeResponse(json_data=CHAMP_SELECT_SESSION)
    transport.responses['/lol-gameflow/v1/session'] = FakeResponse(json_data={'gameId': 0})

    transport.emit(GAMEFLOW_PHASE_URI, 'ChampSelect', 'Update')

    paths = [path for path, _ in transport.calls]
    assert CHAMP_SELECT_URI in paths
    assert events['match_updated']
    assert service._game_phase == 'ChampSelect'


def test_ws_open_reconnect_refreshes_phase_and_region():
    service, transport, events = make_service()
    service.start()
    transport.responses[GAMEFLOW_PHASE_URI] = FakeResponse(text='"ChampSelect"')
    transport.responses[CHAMP_SELECT_URI] = FakeResponse(json_data=CHAMP_SELECT_SESSION)
    transport.responses['/lol-gameflow/v1/session'] = FakeResponse(json_data={'gameId': 0})
    transport.responses[REGION_LOCALE_URI] = FakeResponse(json_data={'region': 'CN'})
    transport.responses['/lol-chat/v1/me'] = FakeResponse(json_data={
        'platformId': 'HN1', 'gameName': '我', 'gameTag': '0001', 'puuid': 'p1',
    })

    transport.emit(WS_OPEN_EVENT, {'reconnect': True}, 'Open')

    assert events['phase_changed'][-1] == ('ChampSelect',)
    assert events['match_updated']
    account = events['account_updated'][-1][0]
    assert account['region_name'] == '艾欧尼亚'
    assert account['puuid'] == 'p1'


def test_refresh_is_deduplicated_and_calls_done_callback():
    service, _, _ = make_service()
    service.start()
    service._game_phase = 'ChampSelect'

    entered = threading.Event()
    release = threading.Event()
    done = threading.Event()

    def fake_check(token=None):
        entered.set()
        release.wait(2)

    service._check_champ_select = fake_check

    assert service.refresh(done_callback=done.set) is True
    assert entered.wait(2)
    assert service.refresh() is False

    release.set()
    assert done.wait(2)
    assert service._refresh_in_progress is False


def test_search_summoner_and_game_id_cache():
    service, transport, _ = make_service()
    transport.responses['/lol-summoner/v1/alias/lookup'] = FakeResponse(json_data={
        'puuid': 'p1', 'alias': {'gameName': 'A', 'tagLine': '1'},
    })
    transport.responses['/lol-gameflow/v1/session'] = FakeResponse(json_data={'gameId': 123})

    result = service.search_summoner(' A#1 ')
    assert result['puuid'] == 'p1'
    assert transport.calls[-1][1]['params'] == {'gameName': 'A', 'tagLine': '1'}

    assert service.search_summoner('bad-format') is None
    assert service.get_current_game_id() == '123'

    transport.responses['/lol-gameflow/v1/session'] = FakeResponse(json_data={})
    assert service.get_current_game_id() == '123'


def test_snapshot_and_events_are_copies():
    service, _, events = make_service()
    service._send_match({'my_team': [{'puuid': 'p1'}], 'enemy_team': [], 'myself': None})

    payload = events['match_updated'][-1][0]
    payload['my_team'][0]['puuid'] = 'changed'
    assert service.snapshot()['match_data']['my_team'][0]['puuid'] == 'p1'

    snapshot = service.snapshot()
    snapshot['match_data']['my_team'][0]['puuid'] = 'changed-again'
    assert service.snapshot()['match_data']['my_team'][0]['puuid'] == 'p1'
