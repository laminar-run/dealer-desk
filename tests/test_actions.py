import json

import pytest


@pytest.fixture(autouse=True)
def sdk(tmp_path, monkeypatch):
    monkeypatch.setenv("ProgramW6432", str(tmp_path))
    dest = tmp_path / "MinicorDesktopService" / "sdk"
    dest.mkdir(parents=True)
    (dest / "injected_actions.py").write_text(
        "def claim_request(target): return {'request': None}\n"
        "def report(target, request_id, outcome): return {'ok': True}\n"
    )

from action_control.receiver import ACTION, Receiver, install


class Root:
    def after(self, delay, callback):
        pass


def test_registration_and_execution(tmp_path, monkeypatch):
    monkeypatch.setenv('PROGRAMDATA', str(tmp_path))
    path = install('Robot', 'desk', 'v1')
    registration = json.loads(path.read_text())
    assert 'inbox' not in registration
    receiver = Receiver(Root(), registration)
    calls = []
    monkeypatch.setattr('chaos.scenarios.scenario_critical_error', lambda root, immediate: calls.append(immediate))
    request = {'requestId': 'one', 'target': registration['target'], 'actionId': ACTION['id'], 'actionVersion': 1, 'parameters': {}}
    assert receiver.execute(request)['outcome'] == {'kind': 'completed'}
    assert calls == [True]
    assert receiver.execute({**request, 'parameters': {'extra': True}})['outcome']['kind'] == 'rejected'
    monkeypatch.setattr('chaos.scenarios.scenario_critical_error', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('failure')))
    assert receiver.execute(request)['outcome'] == {'kind': 'failed', 'reason': 'failure'}


def test_claim_runs_on_poll_and_reports_outcome(tmp_path, monkeypatch):
    monkeypatch.setenv('PROGRAMDATA', str(tmp_path))
    registration = json.loads(install('robot', 'desk', 'v1').read_text())
    receiver = Receiver(Root(), registration)
    messages = []
    def call(message):
        messages.append(message)
        receiver.busy = True
    monkeypatch.setattr(receiver, 'call', call)
    monkeypatch.setattr('chaos.scenarios.scenario_critical_error', lambda *a, **k: None)
    request = {'requestId': 'one', 'target': registration['target'], 'actionId': ACTION['id'], 'actionVersion': 1, 'parameters': {}}
    receiver.busy = True
    receiver.results.put(({'op': 'claim_request'}, {'request': request}, None))
    receiver.poll()
    assert messages[0] == {'op': 'report', 'target': registration['target'], 'requestId': 'one', 'outcome': {'kind': 'completed'}}


def test_failed_claim_keeps_polling(tmp_path, monkeypatch):
    monkeypatch.setenv('PROGRAMDATA', str(tmp_path))
    registration = json.loads(install('robot', 'desk', 'v1').read_text())
    receiver = Receiver(Root(), registration)
    messages = []
    monkeypatch.setattr(receiver, 'call', messages.append)
    receiver.busy = True
    receiver.results.put(({'op': 'claim_request'}, None, TimeoutError('unavailable')))
    receiver.poll()
    assert messages == [{'op': 'claim_request', 'target': registration['target']}]


def test_call_uses_sdk_functions(tmp_path, monkeypatch):
    monkeypatch.setenv('PROGRAMDATA', str(tmp_path))
    registration = json.loads(install('robot', 'desk', 'v1').read_text())
    receiver = Receiver(Root(), registration)
    claim = {'op': 'claim_request', 'target': registration['target']}
    receiver.call(claim)
    assert receiver.results.get(timeout=2) == (claim, {'request': None}, None)
    report = {'op': 'report', 'target': registration['target'], 'requestId': 'one', 'outcome': {'kind': 'completed'}}
    receiver.call(report)
    assert receiver.results.get(timeout=2) == (report, {'ok': True}, None)
