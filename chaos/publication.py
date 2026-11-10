import json
import os
from pathlib import Path
import re


def trial_local_appdata(namespace):
    if not isinstance(namespace, str) or not re.fullmatch(r'[0-9a-f]{32}', namespace):
        raise ValueError('trial publication namespace must be 32 lowercase hex characters')
    return Path(os.environ['LOCALAPPDATA']) / 'Minicor/DealerDesk/trial-publications' / namespace


class Publication:
    def __init__(self, *, trial_namespace=None):
        local_appdata = (trial_local_appdata(trial_namespace) if trial_namespace is not None
                         else Path(os.environ['LOCALAPPDATA']))
        mutex_name = r"Local\Minicor.DealerDesk.Chaos"
        if trial_namespace is not None:
            mutex_name += '.Trial.' + trial_namespace
        import ntsecuritycon
        import win32api
        import win32con
        import win32event
        import win32security
        import win32ts

        self.mutex = win32event.CreateMutex(
            None, False, mutex_name
        )
        if win32api.GetLastError() == 183:
            self.mutex.Close()
            raise RuntimeError(
                "DealerDesk local testing is already running in this session"
            )
        self.path = None
        try:
            session = win32ts.ProcessIdToSessionId(os.getpid())
            directory = (
                local_appdata
                / "Minicor/DealerDesk/chaos"
                / str(session)
            )
            directory.mkdir(parents=True, exist_ok=True)
            token = win32security.OpenProcessToken(
                win32api.GetCurrentProcess(), win32con.TOKEN_QUERY
            )
            try:
                user = win32security.GetTokenInformation(
                    token, win32security.TokenUser
                )[0]
            finally:
                token.Close()
            acl = win32security.ACL()
            inheritance = win32con.OBJECT_INHERIT_ACE | win32con.CONTAINER_INHERIT_ACE
            for sid in (
                user,
                win32security.CreateWellKnownSid(
                    win32security.WinBuiltinAdministratorsSid
                ),
                win32security.CreateWellKnownSid(win32security.WinLocalSystemSid),
            ):
                acl.AddAccessAllowedAceEx(
                    win32security.ACL_REVISION,
                    inheritance,
                    ntsecuritycon.FILE_ALL_ACCESS,
                    sid,
                )
            win32security.SetNamedSecurityInfo(
                str(directory),
                win32security.SE_FILE_OBJECT,
                win32security.DACL_SECURITY_INFORMATION
                | win32security.PROTECTED_DACL_SECURITY_INFORMATION,
                None,
                None,
                acl,
                None,
            )
            self.path = directory / "connection.json"
        except Exception:
            self.mutex.Close()
            raise

    def publish(self, port, key):
        temporary = self.path.with_suffix(".tmp")
        try:
            with temporary.open("w", encoding="utf-8") as output:
                json.dump({"port": port, "key": key}, output)
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def close(self):
        try:
            self.path.unlink(missing_ok=True)
        finally:
            self.mutex.Close()
