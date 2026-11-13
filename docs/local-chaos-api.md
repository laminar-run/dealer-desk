# Local chaos API

DealerDesk starts its local testing listener with `python main.py` and the usual Windows shortcut.
It uses pywin32 for Windows controls and an embedded FastAPI/Uvicorn listener, with no platform service registration.
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

## Requests and acceptance

Send one POST with `Content-Type: application/json`.
Every body requires integer `timeoutMs` from 1 through 30000 and rejects booleans and unexpected fields.
Routes use lowercase paths without slash redirects or query-based action fields.

| Route | Additional fields | Scheduled effect |
| --- | --- | --- |
| `/window/move` | Signed 32-bit integer `x`, `y` | Restore and move the primary window to outer screen coordinates. |
| `/window/minimize` | None | Minimize the primary window. |
| `/input/ignore-next-click` | None | Arm one left press and release suppression. |
| `/dms/critical-error` | None | Show the existing critical-error dialog. |
| `/dms/scenario` | `scenario`: one of `random_dialog`, `fake_freeze`, `session_timeout`, `unexpected_save`, `critical_error`, `field_corruption`, `save_failure`, `wrong_patient`, `bsod_overlay`, `slow_progress`. Optional integer `durationMs` from 1 through `DEALERDESK_FREEZE_MAX_MS` (default 60000), only with `fake_freeze`. | Start the scenario as the Settings "Fire Now" button does. The freeze blocks the UI thread: nothing responds or redraws, Windows can mark the window "Not Responding", and input and other admitted actions wait until it ends. Without `durationMs`, it lasts a random 3 to 10 seconds. |

HTTP 202 with `{"status":"accepted"}` means the engine admitted the callback to its one pending slot.
The callback runs on the Tk thread even when random chaos is disabled.
Acceptance does not confirm execution or the resulting UI state.
The engine drops a callback if its deadline has passed before execution starts.
A started callback runs without a completion deadline.
Failed callbacks are logged, and polling continues.
There is no completion wait, result store, or subsequent result endpoint.

Shared controls target the explicit current login, second-factor, or dashboard Toplevel.
Window state changes use Tk's window manager so minimize and restore preserve its client geometry.
The login's own grab is eligible; another modal prevents shared controls until dismissed.
Click suppression runs before widget and class bindings, including dynamically mapped widgets.
A second arm fails while armed or consuming.
The following fresh click works, including when the consumed release escaped the app.
This affects primary Tk client controls only, excluding titlebars, native dialogs, UIA Invoke, and other processes.
Unavailable targets and failed effects are asynchronous failures logged by the engine.

Authentication failures return HTTP 401 with `{"detail":"unauthorized"}` before reading the body, including for unknown routes and unsupported methods.
Authenticated requests receive HTTP 422 for invalid request bodies and FastAPI's own 404 and 405 bodies for unknown routes and unsupported methods.
HTTP 503 with `{"status":"rejected","code":"busy"}` or `"shutting_down"` means admission failed.
Uvicorn owns HTTP framing and parser rejections and supports persistent connections and chunked bodies.
The API adds no body-size limit or body-read deadline.
Incomplete clients do not block other requests, and server shutdown cancels remaining requests.

`timeoutMs` begins after complete request validation and uses a monotonic clock.
Shutdown closes admission, drops pending callbacks, and stops the embedded server before removing discovery.
Use a socket timeout of `timeoutMs / 1000 + 3` seconds within a longer ordinary RPA step timeout.
A transport timeout has unknown outcome and does not cancel a request accepted later.
Send no automatic retries.
There are no receipts, IDs, deduplication, job callbacks, or immediate job-stop coupling.
Enclosing job and recovery retries are unchanged.
The verification job must observe the expected dialog or window state before continuing.

## Extend actions

Define strict request fields in `chaos/actions.py` by extending `ActionRequest`.
Add a typed FastAPI route in `chaos/receiver.py` and pass its Tk callback to `_accept`.
The existing engine checks the deadline immediately before calling the handler on Tk.
Handlers perform the effect or raise an exception; they do not return HTTP results or confirm effects.
Update the request table when exposing or changing an action.

## Verification

Run `python -m unittest discover -s tests` for HTTP acceptance, validation, expiry, callback failures, and Tk click regressions.
Tk checks run on Windows, require a graphical display, and report a skip when unavailable.
Windows acceptance must also exercise login/TFA/dashboard targeting, restored multi-monitor movement, minimization, critical-dialog visibility, and physical clicks on new widgets.
Inspect directory/file ACLs and prove a different standard user cannot read discovery.
Check duplicate startup, stale credentials after restart, and publication cleanup.
Run an ordinary saved RPA job with normal work before and after injection, observe recovery in its replay, and independently confirm customer C10000's resulting record.
These Windows and job checks are separate from portable regression results.
