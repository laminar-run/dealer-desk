"""Windows session discovery, protected before any key is written."""

import json
import os
from pathlib import Path


class Publication:
    def __init__(self):
        import win32api
        import win32con
        import win32event
        import win32process
        import win32security

        self.mutex = win32event.CreateMutex(
            None, False, r"Local\Minicor.DealerDesk.Chaos"
        )
        if win32api.GetLastError() == 183:
            self.mutex.Close()
            raise RuntimeError(
                "DealerDesk local testing is already running in this session"
            )
        self.path = None
        try:
            session = win32process.ProcessIdToSessionId(os.getpid())
            directory = (
                Path(os.environ["LOCALAPPDATA"])
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
                    win32con.FILE_ALL_ACCESS,
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
