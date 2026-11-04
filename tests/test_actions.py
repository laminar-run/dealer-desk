import json
import os
import threading
import time
from unittest.mock import MagicMock, Mock
from uuid import uuid4

import pytest
from action_control.receiver import ACTION, Receiver, start_test_inbox

@pytest.fixture
def receiver(tmp_path):
    return Receiver(Mock(), tmp_path, "http://middleware.test")

def request(receiver):
    return {"attemptId": str(uuid4()), "token": "secret", "action": ACTION, "pid": os.getpid()}


def test_claim_verifies_off_thread_then_creates_dialog_on_poll(receiver, monkeypatch):
    payload = request(receiver)
    path = receiver.directory / f'{payload["attemptId"]}.request.json'
    path.write_text(json.dumps(payload))
    effect = Mock()
    monkeypatch.setattr("chaos.scenarios.scenario_critical_error", effect)
    threads = []
    receiver.verify = lambda value: threads.append(threading.get_ident()) or time.time() * 1000 + 10000
    receiver.poll()
    result = receiver.results.get(timeout=2)
    assert not path.exists()
    assert threads != [threading.get_ident()]
    effect.assert_not_called()
    receiver.results.put(result)
    receiver.poll()
    effect.assert_called_once_with(receiver.root, immediate=True)
    assert not list(receiver.directory.iterdir())
    path.write_text(json.dumps(payload))
    receiver.poll()
    receiver.results.put(receiver.results.get(timeout=2))
    receiver.poll()
    effect.assert_called_once_with(receiver.root, immediate=True)
    assert not list(receiver.directory.iterdir())


def test_rejects_wrong_target_and_checks_deadline_at_effect(receiver, monkeypatch):
    payload = request(receiver)
    payload["pid"] += 1
    with pytest.raises(ValueError, match="target"):
        receiver.verify(payload)
    payload["pid"] = os.getpid()
    opener = MagicMock()
    opener.open.return_value.__enter__.return_value.read.return_value = json.dumps({"active": True, "deadlineAt": time.time() * 1000 + 10000}).encode()
    monkeypatch.setattr("action_control.receiver.build_opener", lambda *args: opener)
    assert receiver.verify(payload) > time.time() * 1000
    sent = opener.open.call_args.args[0]
    assert sent.get_header("Authorization") == "Bearer secret"
    effect = Mock()
    monkeypatch.setattr("chaos.scenarios.scenario_critical_error", effect)
    path = receiver.directory / "expired.claimed"
    path.touch()
    receiver.results.put((path, time.time() * 1000 - 1))
    receiver.poll()
    effect.assert_not_called()
    assert not path.exists()


def test_authentication_failure_is_consumed_without_effect(receiver, monkeypatch):
    payload = request(receiver)
    path = receiver.directory / f'{payload["attemptId"]}.request.claimed'
    path.write_text(json.dumps(payload))
    receiver.verify = Mock(side_effect=OSError("unavailable"))
    effect = Mock()
    monkeypatch.setattr("chaos.scenarios.scenario_critical_error", effect)
    receiver.process(path)
    receiver.poll()
    effect.assert_not_called()
    assert not path.exists()


def test_disabled_inbox_and_owner_safe_cleanup(receiver, monkeypatch):
    monkeypatch.delenv("INJECTED_ACTION_MIDDLEWARE_ORIGIN", raising=False)
    assert start_test_inbox(Mock()) is None
    ready = receiver.directory / "ready.json"
    ready.write_text(json.dumps({"pid": os.getpid() + 1}))
    receiver.close(Mock(widget=receiver.root))
    assert ready.exists()
