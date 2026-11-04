import json
import threading
from unittest.mock import Mock

import pytest

from action_control.receiver import ACTION, Receiver, install


@pytest.fixture
def receiver(tmp_path, monkeypatch):
    monkeypatch.setenv("PROGRAMDATA", str(tmp_path))
    monkeypatch.setenv("ProgramW6432", str(tmp_path))
    sdk = tmp_path / "MinicorDesktopService" / "sdk"
    sdk.mkdir(parents=True)
    (sdk / "injected_actions.py").write_text("from unittest.mock import Mock\nclaim_request = Mock()\nreport = Mock()\n")
    registration = json.loads(install("Robot", "desk", "v1").read_text())
    assert "inbox" not in registration
    return Receiver(Mock(), registration)


def request(receiver):
    return {"requestId": "one", "target": receiver.registration["target"], "actionId": ACTION["id"],
            "actionVersion": 1, "parameters": {}}


def test_claim_and_report_through_sdk(receiver, monkeypatch):
    claimed = request(receiver)
    receiver.client.claim_request.return_value = {"request": claimed}
    reported = threading.Event()
    receiver.client.report.side_effect = lambda *args: reported.set() or {"ok": True}
    effect = Mock()
    monkeypatch.setattr("chaos.scenarios.scenario_critical_error", effect)
    receiver.poll()
    result = receiver.results.get(timeout=2)
    receiver.client.claim_request.assert_called_once_with(claimed["target"])
    effect.assert_not_called()
    receiver.results.put(result)
    receiver.poll()
    assert reported.wait(2)
    receiver.client.report.assert_called_once_with(claimed["target"], "one", {"kind": "completed"})
    effect.assert_called_once_with(receiver.root, immediate=True)


def test_invalid_parameters_and_handler_failure(receiver, monkeypatch):
    effect = Mock(side_effect=RuntimeError("failure"))
    monkeypatch.setattr("chaos.scenarios.scenario_critical_error", effect)
    invalid = {**request(receiver), "parameters": {"extra": True}}
    assert receiver.execute(invalid)["outcome"]["kind"] == "rejected"
    effect.assert_not_called()
    assert receiver.execute(request(receiver))["outcome"] == {"kind": "failed", "reason": "failure"}


def test_failed_claim_keeps_polling(receiver):
    receiver.client.claim_request.side_effect = TimeoutError("unavailable")
    receiver.poll()
    result = receiver.results.get(timeout=2)
    receiver.results.put(result)
    receiver.poll()
    receiver.root.after.assert_called_with(1000, receiver.poll)
    receiver.poll()
    assert isinstance(receiver.results.get(timeout=2)[2], TimeoutError)
    assert receiver.client.claim_request.call_count == 2
