"""Isolated native DealerDesk lifecycle. One JSON request and response per call."""
import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time

PROTOCOL = 1
HERE = Path(__file__).resolve().parent
CRITICAL = 'DealerDesk 98 - Critical Application Error'
TABLES = ('customers', 'vehicles', 'repair_orders', 'deals', 'appointments')


def build_digest():
    paths = [HERE / 'dealerdesk_trial.py', HERE / 'main.py', HERE / 'tfa.py', HERE / 'db/schema.sql']
    for folder in ('ui', 'db', 'chaos', 'models'):
        paths.extend((HERE / folder).glob('*.py'))
    return hashlib.sha256(b''.join(p.relative_to(HERE).as_posix().encode() + b'\0' + p.read_bytes()
                                   for p in sorted(set(paths)))).hexdigest()


def write_json(path, value):
    descriptor, name = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix='.tmp')
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, sort_keys=True)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def publication_root(manifest):
    from chaos.publication import trial_local_appdata
    source = trial_local_appdata(manifest['publicationNamespace'])
    expected = source.resolve()
    if Path(manifest['publicationLocalAppData']).resolve() != expected or source.is_symlink():
        raise ValueError('trial publication root mismatch')
    return expected


def session_id(pid=None):
    import win32ts
    return win32ts.ProcessIdToSessionId(os.getpid() if pid is None else pid)


def identity(pid):
    import psutil
    process = psutil.Process(pid)
    return {'pid': pid, 'createdAt': process.create_time(), 'executable': process.exe(),
            'commandLine': process.cmdline(), 'sessionId': session_id(pid)}


def canonical(value):
    return os.path.normcase(str(Path(value).resolve()))


def launch_record(directory, manifest):
    receipt = read_json(directory / 'launch.json')
    if receipt['trialId'] != manifest['trialId'] or receipt['build'] != manifest['build']:
        raise RuntimeError('process ownership mismatch: launch trial or build')
    return receipt


def verified_process(saved, receipt, directory, manifest):
    import psutil
    try:
        process = psutil.Process(saved['pid'])
        if not process.is_running() or process.status() == psutil.STATUS_ZOMBIE:
            return None
        current = identity(saved['pid'])
    except psutil.NoSuchProcess:
        return None
    arguments = current['commandLine']
    allowed = {canonical(receipt['executable']), canonical(receipt['baseExecutable'])}
    if (current['createdAt'] != saved['createdAt'] or
            canonical(current['executable']) != canonical(saved['executable']) or
            canonical(current['executable']) not in allowed or
            current['sessionId'] != manifest['sessionId'] or saved['sessionId'] != manifest['sessionId'] or
            len(arguments) != 4 or canonical(arguments[0]) not in allowed or
            canonical(arguments[1]) != canonical(HERE / 'dealerdesk_trial.py') or
            arguments[2] != '--app' or canonical(arguments[3]) != canonical(directory)):
        raise RuntimeError('process ownership mismatch; no desktop action permitted')
    return process


def owned_launcher(directory, manifest):
    receipt = launch_record(directory, manifest)
    return verified_process(receipt, receipt, directory, manifest)


def owned_process(directory, manifest):
    path = directory / 'ui-process.json'
    if not path.exists():
        return None
    return verified_process(read_json(path), launch_record(directory, manifest), directory, manifest)


def attest_ui(directory, manifest):
    path = directory / 'ui-process.json'
    if path.exists():
        return owned_process(directory, manifest)
    receipt = launch_record(directory, manifest)
    launcher = verified_process(receipt, receipt, directory, manifest)
    candidate_path = directory / 'app-process.json'
    if not candidate_path.exists():
        return None
    candidate = read_json(candidate_path)
    if candidate.get('trialId') != manifest['trialId'] or candidate.get('build') != manifest['build']:
        raise RuntimeError('UI handshake trial or build mismatch')
    process = verified_process(candidate, receipt, directory, manifest)
    if not process:
        return None
    if not launcher:
        raise RuntimeError('launcher exited before UI ancestry attestation')
    expected_children = [] if process.pid == launcher.pid else [process.pid]
    if sorted(child.pid for child in launcher.children()) != expected_children or process.pid != launcher.pid and process.children():
        raise RuntimeError('unexpected process in venv redirector chain')
    if process.pid != launcher.pid:
        if (process.ppid() != launcher.pid or candidate['createdAt'] < receipt['createdAt'] or
                canonical(candidate['executable']) != canonical(receipt['baseExecutable']) or
                canonical(receipt['executable']) == canonical(receipt['baseExecutable'])):
            raise RuntimeError('UI process is not the expected venv redirector child')
    write_json(path, candidate)
    write_json(Path(manifest['evidenceDirectory']) / 'ui-process.json', candidate)
    return process


def settle_processes(directory, manifest):
    import psutil
    attest_ui(directory, manifest)
    launcher = owned_launcher(directory, manifest)
    ui_path = directory / 'ui-process.json'
    ui_pid = read_json(ui_path)['pid'] if ui_path.exists() else None
    if launcher and any(child.pid != ui_pid for child in launcher.children()):
        raise RuntimeError('unattested launcher child; retain lane for reconciliation')
    ui = owned_process(directory, manifest)
    if ui and ui.pid != (launcher.pid if launcher else None) and ui.children():
        raise RuntimeError('unexpected UI descendant; retain lane for reconciliation')
    (directory / 'stop').touch()
    for reader in (owned_process, owned_launcher):
        process = reader(directory, manifest)
        if process:
            try:
                process.wait(timeout=8)
            except psutil.TimeoutExpired:
                process = reader(directory, manifest)
                if process:
                    process.terminate()
                    process.wait(timeout=5)
    if owned_process(directory, manifest) or owned_launcher(directory, manifest):
        raise RuntimeError('owned UI and launcher exit not confirmed')


def business_state(directory):
    with closing(sqlite3.connect((directory / 'dms.db').as_uri() + '?mode=ro', uri=True)) as db:
        db.row_factory = sqlite3.Row
        tables = {name: [dict(row) for row in db.execute('SELECT * FROM ' + name + ' ORDER BY id')]
                  for name in TABLES}
        writes = db.execute('SELECT COUNT(*) FROM trial_writes').fetchone()[0]
    digest = hashlib.sha256(json.dumps(tables, sort_keys=True).encode()).hexdigest()
    return {'sha256': digest, 'writeCount': writes, 'tables': tables}


def validate_starting_state(state):
    if not isinstance(state, dict) or set(state) - {'section', 'rows'}:
        raise ValueError('startingState must contain only section and rows')
    section = state.get('section', 'home')
    if section not in ('home', 'customers', 'inventory', 'deals', 'repair_orders',
                       'appointments', 'reports', 'settings'):
        raise ValueError('invalid starting section')
    rows = state.get('rows', {})
    if not isinstance(rows, dict) or set(rows) - set(TABLES):
        raise ValueError('rows must contain only business tables')
    if any(not isinstance(entries, list) or any(not isinstance(row, dict) or not row for row in entries)
           for entries in rows.values()):
        raise ValueError('each table must contain a list of nonempty row objects')
    return {'section': section, 'rows': rows}


def seed(directory, state=None):
    state = validate_starting_state(state if state is not None else {})
    with closing(sqlite3.connect(directory / 'dms.db')) as db, db:
        db.execute('PRAGMA foreign_keys = ON')
        db.executescript((HERE / 'db/schema.sql').read_text())
        db.execute("INSERT INTO users(username,password,role) VALUES('trial','synthetic-unused','admin')")
        for table in TABLES:
            columns = {row[1] for row in db.execute(f'PRAGMA table_info({table})')}
            for row in state['rows'].get(table, []):
                if not set(row) <= columns:
                    raise ValueError(f'unknown column in {table}')
                names = list(row)
                db.execute(f"INSERT INTO {table} ({','.join(names)}) VALUES ({','.join('?' for _ in names)})",
                           [row[name] for name in names])
        db.execute('CREATE TABLE trial_writes(seq INTEGER PRIMARY KEY,table_name TEXT,operation TEXT,at TEXT)')
        for table in TABLES:
            for action in ('INSERT', 'UPDATE', 'DELETE'):
                db.execute(f"""CREATE TRIGGER trial_{table}_{action} AFTER {action} ON {table}
                               BEGIN INSERT INTO trial_writes(table_name,operation,at)
                               VALUES('{table}','{action}',strftime('%Y-%m-%dT%H:%M:%fZ','now')); END""")


def foreground(dashboard):
    import win32api
    import win32con
    import win32gui
    import win32process
    dashboard.update_idletasks()
    hwnd = win32gui.GetAncestor(dashboard.winfo_id(), win32con.GA_ROOT)
    if win32process.GetWindowThreadProcessId(hwnd)[1] != os.getpid():
        raise RuntimeError('foreign dashboard window')
    current = win32api.GetCurrentThreadId()
    for _ in range(20):
        other = win32process.GetWindowThreadProcessId(win32gui.GetForegroundWindow())[0]
        attached = other != current
        if attached:
            win32process.AttachThreadInput(current, other, True)
        try:
            win32gui.ShowWindow(hwnd, win32con.SW_MAXIMIZE)
            win32gui.BringWindowToTop(hwnd)
            win32gui.SetForegroundWindow(hwnd)
            dashboard.focus_force()
        finally:
            if attached:
                win32process.AttachThreadInput(current, other, False)
        dashboard.update()
        if win32process.GetWindowThreadProcessId(win32gui.GetForegroundWindow())[1] == os.getpid():
            return
        time.sleep(.1)
    raise RuntimeError('could not foreground the trial dashboard')


def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)


def native_snapshot(root, dashboard, manifest, directory):
    import tkinter as tk
    import win32gui
    import win32process
    from ui.customer_detail import CustomerDetailWindow
    from ui.customers import CustomerListPanel
    windows = [w for w in descendants(root) if isinstance(w, tk.Toplevel)]
    grab = root.grab_current()
    modal = grab.winfo_toplevel() if grab else None
    blocking = bool(modal and modal != dashboard and modal.winfo_viewable())
    def window_state(window):
        hwnd = win32gui.GetAncestor(window.winfo_id(), 2)
        if win32process.GetWindowThreadProcessId(hwnd)[1] != os.getpid():
            raise RuntimeError('foreign native window; observation refused')
        return {'title': window.title(), 'tkPath': str(window), 'visible': bool(window.winfo_viewable()),
                'hwnd': hwnd, 'pid': os.getpid()}
    details = [dict(window_state(w), customerNo=w._customer['customer_no'],
                    customerId=w._customer['id']) for w in windows if isinstance(w, CustomerDetailWindow)]
    panel = next((w for w in descendants(dashboard) if isinstance(w, CustomerListPanel)), None)
    controls = {}
    for w in descendants(dashboard):
        if w.winfo_name() in ('customer_search', 'btn_search_customers', 'btn_open_customer', 'customer_tree'):
            enabled = str(w.cget('state')) != 'disabled' if 'state' in w.keys() else True
            controls[w.winfo_name()] = {'present': True, 'enabled': enabled,
                                       'visible': bool(w.winfo_viewable()),
                                       'usable': enabled and bool(w.winfo_viewable()) and not blocking}
    for name in ('customer_search', 'btn_search_customers', 'btn_open_customer', 'customer_tree'):
        controls.setdefault(name, {'present': False, 'enabled': False, 'visible': False, 'usable': False})
    return {'trialId': manifest['trialId'], 'build': manifest['build'], 'pid': os.getpid(),
            'processCreatedAt': manifest['processCreatedAt'], 'sessionId': session_id(),
            'capturedAt': time.time(), 'section': dashboard._active_section,
            'dashboard': window_state(dashboard), 'modal': {'known': True, 'present': blocking,
                'blocking': blocking, 'window': window_state(modal) if blocking else None,
                'kind': ('customer-detail' if isinstance(modal, CustomerDetailWindow) else
                         'critical-error' if modal and modal.title() == CRITICAL else 'other') if blocking else None},
            'criticalDialog': {'known': True, 'present': any(w.title() == CRITICAL and w.winfo_viewable() for w in windows)},
            'controls': controls, 'detailWindows': details, 'detailWindowsKnown': True,
            'query': panel._search_var.get() if panel else None,
            'selectedId': panel._selected_id() if panel else None,
            'dashboardUsable': dashboard._active_section == 'customers' and bool(dashboard.winfo_viewable()) and
                               not blocking and all(c['usable'] for c in controls.values()),
            'foregroundOwned': win32process.GetWindowThreadProcessId(win32gui.GetForegroundWindow())[1] == os.getpid(),
            'business': business_state(directory)}


def consume_observation_request(request_path, evidence, capture):
    try:
        request = read_json(request_path)
        request_path.unlink()
    except (PermissionError, FileNotFoundError):
        # Windows can temporarily deny reads or deletion while the writer closes.
        return
    target = evidence / request['observationId']
    if not (target / 'observation.json').exists() and not (target / 'error.json').exists():
        capture(request, target)


def app(directory):
    if os.name != 'nt':
        raise RuntimeError('native trial requires Windows')
    manifest = read_json(directory / 'manifest.json')
    process_identity = identity(os.getpid())
    handshake = dict(process_identity, trialId=manifest['trialId'], build=manifest['build'])
    write_json(directory / 'app-process.json', handshake)
    write_json(Path(manifest['evidenceDirectory']) / 'app-process.json', handshake)
    import tkinter as tk
    from PIL import ImageGrab
    from db import connection
    connection.DB_PATH = str(directory / 'dms.db')
    from ui.dashboard import DashboardWindow
    from chaos.controls import Controls
    from chaos.engine import ChaosEngine
    from chaos.publication import Publication
    from chaos.receiver import Receiver
    manifest['processCreatedAt'] = process_identity['createdAt']
    publication_root(manifest)
    root = tk.Tk()
    root.withdraw()
    controls = Controls(root)
    engine = ChaosEngine(root)
    publication = None
    receiver = None
    try:
        publication = Publication(trial_namespace=manifest['publicationNamespace'])
        key = secrets.token_urlsafe(32)
        receiver = Receiver(engine, key, controls)
        publication.publish(receiver.port, key)
    except Exception:
        engine.close()
        if receiver:
            receiver.close()
        if publication:
            publication.close()
        root.destroy()
        raise
    try:
        dashboard = DashboardWindow(root, {'username': 'trial', 'role': 'admin'}, root.destroy)
        dashboard.navigate(manifest['startingState']['section'])
        controls.set_primary(dashboard)
        foreground(dashboard)
        write_json(directory / 'ready.json', {'trialId': manifest['trialId'], 'build': manifest['build'],
                   'pid': os.getpid(), 'sessionId': session_id(), 'chaosPort': receiver.port,
                   'publicationNamespace': manifest['publicationNamespace'], 'process': process_identity})
        def capture(request, target):
            try:
                start = time.time()
                root.update_idletasks()
                before = native_snapshot(root, dashboard, manifest, directory)
                ImageGrab.grab().save(target / 'screenshot.png')
                after = native_snapshot(root, dashboard, manifest, directory)
                stable = {k: v for k, v in before.items() if k != 'capturedAt'} == {k: v for k, v in after.items() if k != 'capturedAt'}
                result = {'protocolVersion': PROTOCOL, 'observationId': request['observationId'],
                          'boundary': request.get('boundary'), 'requestedAt': request['requestedAt'],
                          'captureStartedAt': start, 'captureFinishedAt': time.time(),
                          'runtime': after, 'captureStable': stable,
                          'screenshot': {'path': str(target / 'screenshot.png'),
                             'sha256': hashlib.sha256((target / 'screenshot.png').read_bytes()).hexdigest()}}
                write_json(target / 'observation.json', result)
            except Exception as exc:
                write_json(target / 'error.json', {'error': str(exc)})

        def tick():
            if (directory / 'stop').exists():
                root.destroy()
                return
            try:
                consume_observation_request(directory / 'observe-request.json', Path(manifest['evidenceDirectory']), capture)
            finally:
                root.after(25, tick)
        tick()
        root.mainloop()
    finally:
        engine.close()
        controls.set_primary(None)
        try:
            receiver.close()
        finally:
            publication.close()


def observe(directory, manifest, request):
    process = owned_process(directory, manifest)
    if not process:
        raise RuntimeError('trial process is absent')
    observation_id = request.get('observationId')
    if not isinstance(observation_id, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,95}', observation_id):
        raise ValueError('observationId must be a unique safe identifier')
    target = Path(manifest['evidenceDirectory']) / observation_id
    target.mkdir()
    requested = time.time()
    write_json(directory / 'observe-request.json', {'observationId': observation_id,
               'boundary': request.get('boundary'), 'requestedAt': requested})
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if (target / 'error.json').exists():
            raise RuntimeError(read_json(target / 'error.json')['error'])
        if (target / 'observation.json').exists():
            result = read_json(target / 'observation.json')
            runtime = result['runtime']
            if (runtime['trialId'] != manifest['trialId'] or runtime['build'] != manifest['build'] or
                    runtime['pid'] != process.pid or runtime['processCreatedAt'] != process.create_time() or
                    runtime['sessionId'] != manifest['sessionId'] or result['requestedAt'] != requested):
                raise RuntimeError('observation identity mismatch')
            if not owned_process(directory, manifest):
                raise RuntimeError('trial exited while observing')
            result.update(trialId=manifest['trialId'], build=manifest['build'], capturedAt=runtime['capturedAt'],
                          runtimeFresh=0 <= time.time() - runtime['capturedAt'] < 3,
                          evidencePath=str(target / 'observation.json'),
                          baselineBusinessSha256=manifest['baselineBusinessSha256'])
            if not result['captureStable'] or not result['runtimeFresh']:
                raise RuntimeError('observation changed during capture or is stale')
            # Persist the exact response too, outside disposable state.
            write_json(target / 'receipt.json', result)
            return result
        if not owned_process(directory, manifest):
            raise RuntimeError('trial process exited before observation')
        time.sleep(.025)
    raise RuntimeError('observation timed out; do not treat missing evidence as absence')


def operate(request, root, evidence_root):
    if request.get('protocolVersion') != PROTOCOL:
        raise ValueError('protocolVersion must be 1')
    trial = request.get('trialId')
    if not isinstance(trial, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,95}', trial):
        raise ValueError('invalid trialId')
    expected = request.get('expectedBuild')
    if expected is not None and expected != build_digest():
        raise ValueError('expectedBuild does not match installed native sources')
    operation = request.get('operation')
    if operation not in ('prepare', 'observe', 'reset'):
        raise ValueError('invalid operation')
    directory = root / trial
    evidence = evidence_root / trial
    if directory.is_symlink() or evidence.is_symlink():
        raise ValueError('trial paths must not be symlinks')
    result = {'protocolVersion': PROTOCOL, 'trialId': trial, 'operation': operation, 'status': 'ok'}
    if operation == 'prepare' and not directory.exists():
        if os.name != 'nt':
            raise RuntimeError('prepare requires Windows and an attended desktop session')
        if evidence.exists():
            raise ValueError('trialId has prior evidence; inspect it and choose a new ID')
        starting_state = validate_starting_state(request.get('startingState', {}))
        directory.mkdir()
        evidence.mkdir()
        manifest = {'protocolVersion': PROTOCOL, 'trialId': trial, 'build': build_digest(),
                    'sessionId': session_id(), 'evidenceDirectory': str(evidence),
                    'startingState': starting_state, 'taskDigest': request.get('taskDigest')}
        from chaos.publication import trial_local_appdata
        manifest['publicationNamespace'] = secrets.token_hex(16)
        manifest['publicationLocalAppData'] = str(trial_local_appdata(manifest['publicationNamespace']).resolve())
        # Persist ownership before creating any disposable trial data.
        write_json(directory / 'manifest.json', manifest)
        seed(directory, starting_state)
        manifest['baselineBusinessSha256'] = business_state(directory)['sha256']
        write_json(directory / 'manifest.json', manifest)
        write_json(evidence / 'manifest.json', manifest)
        # A crash after this marker but before the launch receipt is ambiguous.
        (directory / 'launch-started').touch()
        with (directory / 'app.log').open('ab') as log:
            process = subprocess.Popen([sys.executable, str(HERE / 'dealerdesk_trial.py'), '--app', str(directory)],
                       cwd=HERE, stdin=subprocess.DEVNULL, stdout=log, stderr=log)
        write_json(directory / 'launch.json', dict(identity(process.pid), trialId=trial, build=manifest['build'],
                   baseExecutable=getattr(sys, '_base_executable', sys.executable)))
        shutil.copyfile(directory / 'launch.json', evidence / 'launch.json')
    elif not directory.exists():
        if operation == 'reset':
            if (evidence / 'reset.json').exists():
                return dict(result, cleanup=read_json(evidence / 'reset.json'))
            pending = evidence / 'reset-pending.json'
            if pending.exists():
                receipt = read_json(pending)
                if receipt.get('trialId') != trial or receipt.get('build') != build_digest() or not receipt.get('clean'):
                    raise ValueError('reset receipt ownership or build mismatch')
                write_json(evidence / 'reset.json', receipt)
                return dict(result, cleanup=receipt)
            if not evidence.exists():
                return dict(result, cleanup={'clean': True, 'trialId': trial})
        raise ValueError('unknown trialId')
    if operation == 'reset' and (evidence / 'reset-pending.json').exists():
        receipt = read_json(evidence / 'reset-pending.json')
        if receipt.get('trialId') != trial or receipt.get('build') != build_digest() or not receipt.get('clean'):
            raise ValueError('reset receipt ownership or build mismatch')
        # The pending receipt is written only after processes and publication are settled.
        shutil.rmtree(directory)
        write_json(evidence / 'reset.json', receipt)
        return dict(result, cleanup=receipt)
    if operation == 'reset' and not (directory / 'manifest.json').exists():
        # Only an empty directory proves setup stopped before any possible launch.
        if any(directory.iterdir()):
            raise RuntimeError('partial trial ownership unknown; retain lane for reconciliation')
        evidence.mkdir(parents=True, exist_ok=True)
        cleanup = {'clean': True, 'trialId': trial, 'build': build_digest(), 'resetAt': time.time()}
        write_json(evidence / 'reset-pending.json', cleanup)
        directory.rmdir()
        write_json(evidence / 'reset.json', cleanup)
        return dict(result, cleanup=cleanup)
    manifest = read_json(directory / 'manifest.json')
    if manifest['trialId'] != trial or manifest['build'] != build_digest() or Path(manifest['evidenceDirectory']) != evidence:
        raise ValueError('trial ownership or build mismatch')
    if operation == 'reset':
        if (directory / 'launch.json').exists():
            settle_processes(directory, manifest)
        elif (directory / 'launch-started').exists():
            raise RuntimeError('launch outcome unknown; retain lane for reconciliation')
        private_publication = publication_root(manifest)
        if private_publication.exists():
            shutil.rmtree(private_publication)
        evidence.mkdir(parents=True, exist_ok=True)
        if (directory / 'app.log').exists():
            shutil.copyfile(directory / 'app.log', evidence / 'app.log')
        cleanup = {'clean': True, 'processExited': True, 'publicationRemoved': True, 'launcherExited': True, 'trialId': trial, 'build': build_digest(), 'resetAt': time.time()}
        write_json(evidence / 'reset-pending.json', cleanup)
        shutil.rmtree(directory)
        write_json(evidence / 'reset.json', cleanup)
        return dict(result, cleanup=cleanup)
    if operation == 'prepare':
        if validate_starting_state(request.get('startingState', {})) != manifest['startingState']:
            raise ValueError('trialId starting state mismatch')
        if request.get('taskDigest') != manifest.get('taskDigest'):
            raise ValueError('trialId task digest mismatch')
        deadline = time.monotonic() + 15
        while not (directory / 'ready.json').exists():
            attest_ui(directory, manifest)
            if not owned_launcher(directory, manifest) and not owned_process(directory, manifest):
                raise RuntimeError('trial startup failed; inspect app.log and reset')
            if time.monotonic() >= deadline:
                raise RuntimeError('trial startup timed out; inspect before retry')
            time.sleep(.1)
        process = attest_ui(directory, manifest)
        ready = read_json(directory / 'ready.json')
        if (not process or ready['process'] != identity(process.pid) or ready['pid'] != process.pid or
                ready['trialId'] != manifest['trialId'] or ready['build'] != manifest['build'] or
                ready['sessionId'] != manifest['sessionId']):
            raise RuntimeError('ready UI process handshake mismatch')
        request = dict(request, observationId=request.get('observationId', 'prepared'), boundary='prepared')
    observation = observe(directory, manifest, request)
    return dict(result, observation=observation)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path)
    parser.add_argument('--evidence-root', type=Path)
    parser.add_argument('--app', type=Path)
    args = parser.parse_args()
    if args.app:
        app(args.app.resolve())
        return 0
    lock = None
    request = {}
    try:
        if not args.root or not args.root.is_absolute():
            raise ValueError('--root must be absolute')
        root = args.root.resolve()
        evidence = (args.evidence_root or root.with_name(root.name + '-evidence')).resolve()
        if not evidence.is_absolute() or evidence == root or root in evidence.parents or evidence in root.parents:
            raise ValueError('evidence root must be separate from disposable root')
        root.mkdir(parents=True, exist_ok=True)
        evidence.mkdir(parents=True, exist_ok=True)
        request = json.load(sys.stdin)
        if not isinstance(request, dict):
            request = {}
            raise ValueError('request must be a JSON object')
        lock = root / '.controller.lock'
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(descriptor)
        result = operate(request, root, evidence)
    except Exception as exc:
        result = {'protocolVersion': PROTOCOL, 'trialId': request.get('trialId'),
                  'operation': request.get('operation'), 'status': 'error', 'error': str(exc)}
    finally:
        if lock and 'descriptor' in locals():
            lock.unlink(missing_ok=True)
    print(json.dumps(result))
    return 0 if result['status'] == 'ok' else 1


if __name__ == '__main__':
    sys.exit(main())
