# Local chaos API

DealerDesk starts its local testing listener with `python main.py` and the usual Windows shortcut.
It uses the existing pywin32 dependency and no platform service registration.
One instance per Windows session binds `127.0.0.1` on an OS-assigned ephemeral port.
A second instance fails startup instead of replacing a live instance's discovery.
Non-Windows launches retain the UI without this Windows listener.

Read `%LOCALAPPDATA%/Minicor/DealerDesk/chaos/<WindowsSessionId>/connection.json` from the job's own session.
It contains only `port` and a fresh per-launch `key`.
Construct the loopback host yourself and send `Authorization: Bearer <key>`.
Never save the key in a job or print it.
The session directory has a protected DACL granting full access to the current user, SYSTEM, and administrators before any key is written.
Another standard user must not read it.
Same-user callers and administrators remain trusted.
The session path prevents accidental routing across sessions, not malicious same-user access.
Shutdown removes discovery while holding a session-local named mutex.
A crashed instance leaves stale discovery that the next launch replaces with fresh credentials.

## Requests and results

Send one POST with `Content-Type: application/json` and at most 2048 body bytes.
Every body requires integer `timeoutMs` from 1 through 30000.
Current actions reject booleans and unexpected fields.
Routes are exact and lowercase.

| Route | Additional fields | Completed effect |
| --- | --- | --- |
| `/window/move` | Signed 32-bit integer `x`, `y` | Restore the primary window, then confirm its actual outer position in screen coordinates. |
| `/window/minimize` | None | Confirm the primary window is iconic. |
| `/input/ignore-next-click` | None | Arm one left press and release suppression. |
| `/dms/critical-error` | None | Observe the existing critical-error dialog mapped with its modal grab. |

Shared controls target the explicit current login, second-factor, or dashboard Toplevel.
Window state changes use Tk's window manager so minimize and restore preserve its client geometry; native Win32 observations confirm the resulting state and outer position.
The login's own grab is eligible; another modal prevents shared controls until dismissed.
Click suppression runs before widget and class bindings, including dynamically mapped widgets.
Completed means armed, not consumed.
A second arm is rejected while armed or consuming.
The following fresh click works, including when the consumed release escaped the app.
This affects primary Tk client controls only, excluding titlebars, native dialogs, UIA Invoke, and other processes.

Responses contain `status` and an optional `code`.
HTTP 200 has `status: completed`.
Rejections use 400 `invalid_request`, 401 `unauthorized`, 404 `unknown_route`, 409 `no_eligible_window` or `already_armed`, 413 `body_too_large`, or 503 `busy` or `shutting_down`.
Unsupported HTTP methods return 501 `invalid_request`.
Malformed HTTP requests can use other parser rejection codes.
Pending expiry returns 504 with `status: rejected` and `code: expired`; it cannot execute later.
A started effect unconfirmed at its deadline returns 504 with `status: unknown` and `code: action_running`.
Other execution failures return 500 with `status: unknown` and `code: action_failed` or `effect_unconfirmed`.

`timeoutMs` begins after complete request admission and validation and uses a monotonic clock.
Headers and body must arrive within two seconds of connection handling.
This separate admission limit does not shorten accepted work's `timeoutMs`.
The HTTP worker is serial; unread socket backlog is outside this duration.
Use a socket timeout of `timeoutMs / 1000 + 3` seconds within a longer ordinary RPA step timeout.
A transport timeout has unknown outcome and does not cancel a request accepted later.
Send no automatic retries, including after unknown results.
There are no receipts, IDs, deduplication, job callbacks, or immediate job-stop coupling.
Enclosing job and recovery retries are unchanged.

## Extend actions

Define immutable parameter objects and their parsers in `chaos/actions.py`.
Parsers accept the action fields without `timeoutMs` and raise `ValueError` for invalid keys or values.
Bind each parser to its typed handler in the single `action_definitions` dictionary with `bind_action`.
The receiver parses before queue admission and invokes the prepared handler on the Tk thread only after work starts.
Handlers return the existing HTTP code, status, and optional reason tuple after confirming the effect.
Update the request table when exposing or changing an action.

## Verification

Run `python -m unittest discover -s tests` for HTTP admission, deadline races, and Tk click regressions.
Tk checks run on Windows, require a graphical display, and report a skip when unavailable.
Windows acceptance must also exercise login/TFA/dashboard targeting, restored multi-monitor movement, minimization, critical-dialog visibility, and physical clicks on new widgets.
Inspect directory/file ACLs and prove a different standard user cannot read discovery.
Check duplicate startup, stale credentials after restart, and publication cleanup.
Run an ordinary saved RPA job with normal work before and after injection, observe recovery in its replay, and independently confirm customer C10000's resulting record.
These Windows and job checks are separate from portable regression results.
