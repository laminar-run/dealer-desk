import json
import logging
import os
from pathlib import Path
import importlib.util
import threading
import queue

from jsonschema import Draft202012Validator


REQUEST_SCHEMA = {
    "type": "object",
    "properties": {
        "requestId": {"type": "string", "minLength": 1, "maxLength": 128},
        "target": {"type": "object"},
        "actionId": {"type": "string"},
        "actionVersion": {"type": "integer", "minimum": 1},
        "parameters": {"type": "object"},
    },
    "required": ["requestId", "target", "actionId", "actionVersion", "parameters"],
    "additionalProperties": False,
}

ACTION = {
    "id": "dealerdesk.critical-error",
    "version": 1,
    "description": "Show the DealerDesk critical application error dialog.",
    "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
}


def registration_dir(user):
    account = user.split("\\")[-1].lower()
    if not account or account in (".", "..") or any(c in account for c in '/\\:'):
        raise ValueError("Invalid Windows user")
    return Path(os.environ["PROGRAMDATA"]) / "Minicor" / "actions" / "registrations" / account


def install(user, instance, version):
    if not instance or len(instance) > 128 or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for c in instance):
        raise ValueError("Invalid instance ID")
    if not version or len(version) > 128:
        raise ValueError("Installed version is required")
    directory = registration_dir(user)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "dealerdesk.json"
    entry = {"targetUser": user, "target": {"kind": "app", "appId": "dealerdesk", "instanceId": instance},
             "installedVersion": version, "actions": [ACTION]}
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(entry), encoding="utf-8")
    os.replace(temp, path)
    return path


def outcome(request_id, kind, reason=None):
    value = {"kind": kind}
    if reason is not None:
        value["reason"] = reason
    return {"requestId": request_id, "outcome": value}


class Receiver:
    def __init__(self, root, registration):
        self.root = root
        self.registration = registration
        self.results = queue.Queue()
        self.busy = False
        path = Path(os.environ.get('ProgramW6432', os.environ.get('ProgramFiles', r'C:\Program Files'))) / 'MinicorDesktopService' / 'sdk' / 'injected_actions.py'
        spec = importlib.util.spec_from_file_location('injected_actions', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.client = module

    def call(self, message):
        def worker():
            try:
                result = (self.client.claim_request(message['target']) if message['op'] == 'claim_request'
                          else self.client.report(message['target'], message['requestId'], message['outcome']))
                self.results.put((message, result, None))
            except Exception as exc:
                self.results.put((message, None, exc))
        self.busy = True
        threading.Thread(target=worker, daemon=True).start()

    def execute(self, request):
        request_id = request.get("requestId") if isinstance(request, dict) else None
        try:
            Draft202012Validator(REQUEST_SCHEMA).validate(request)
            if request["target"] != self.registration["target"] or request["actionId"] != ACTION["id"] or request["actionVersion"] != ACTION["version"]:
                raise ValueError("Unknown target, action, or version")
            Draft202012Validator(ACTION["inputSchema"]).validate(request["parameters"])
        except Exception as exc:
            return outcome(request_id, "rejected", str(exc))
        try:
            from chaos.scenarios import scenario_critical_error
            scenario_critical_error(self.root, immediate=True)
            return outcome(request_id, "completed")
        except Exception as exc:
            return outcome(request_id, "failed", str(exc) or type(exc).__name__)

    def poll(self):
        try:
            try:
                message, response, error = self.results.get_nowait()
            except queue.Empty:
                pass
            else:
                self.busy = False
                if error:
                    logging.warning("Injected action pipe unavailable: %s", error)
                elif message['op'] == 'claim_request':
                    request = response.get('request')
                    if request is not None:
                        result = self.execute(request)
                        self.call({'op': 'report', 'target': self.registration['target'],
                                   'requestId': result['requestId'], 'outcome': result['outcome']})
                elif response.get('ok') is not True:
                    logging.warning("Injected action report was not accepted")
            if not self.busy:
                self.call({'op': 'claim_request', 'target': self.registration['target']})
        finally:
            self.root.after(100, self.poll)


def start_installed(root):
    user = os.environ.get("USERNAME")
    if not user or "PROGRAMDATA" not in os.environ:
        return
    for path in registration_dir(user).glob("dealerdesk.json"):
        try:
            registration = json.loads(path.read_text(encoding="utf-8"))
            if registration["targetUser"].split("\\")[-1].lower() != user.lower():
                continue
            if registration["target"]["appId"] != "dealerdesk":
                continue
            root.after(100, Receiver(root, registration).poll)
        except (OSError, ValueError, KeyError, TypeError):
            logging.exception("Cannot start action receiver for %s", path)
