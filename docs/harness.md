# Native evaluation harness

The controller runs an isolated SQLite database and a native DealerDesk window in an attended Windows session.
It does not acquire the shared desktop claim; the caller must hold that claim and serialize desktop operations.
The controller lock prevents overlapping calls for the same root, and stale locks require reconciliation.

Install `requirements-trial.txt` in a Windows Python environment with Tk.
Run `python dealerdesk_trial.py --root ABSOLUTE_ROOT --evidence-root ABSOLUTE_EVIDENCE_ROOT` for each operation.
The roots must be separate and neither may contain the other.
Send one JSON object on stdin and receive one JSON object on stdout; errors exit 1.
Each request has `protocolVersion: 1`, a safe `trialId`, and `operation` (`prepare`, `observe`, or `reset`).
An optional `expectedBuild` must match the packaged `nativeBuildSha256`.

`prepare` accepts `taskDigest`, optional `observationId`, and optional `startingState`.
The starting state has an optional `section` (home, customers, inventory, deals, repair_orders, appointments, reports, or settings) and `rows`, a mapping from business table names to lists of column-value objects.
Rows are inserted in dependency order with foreign keys enforced; omitted state opens Home with empty business tables.
Use synthetic test data, because evidence includes the state.
Retries must supply the same starting state and task digest.
`observe` requires a unique safe `observationId` and optionally a `boundary`.
`reset` settles only the attested process and its private publication, removes disposable state, and retains evidence and a repeatable receipt.
A launch whose ownership cannot be established is retained for reconciliation.
Never reuse a trial ID after reset.

Observations bind the native process and Windows session to a stable, fresh screenshot and UI sample.
The runtime includes process identity, active section, native windows, customer controls, and read-only business tables, digest, and audited write count.
The audit counts writes even when reverted.
The evidence root retains snapshots, screenshots, process receipts, and logs.
No observation endpoint is exposed to the evaluated agent.
Portable tests cannot prove Windows window ownership, screenshots, or desktop interactions; validate those in an unlocked interactive session.

Build a reproducible archive from a committed revision with `python tools/package_trial.py --checkout PATH --ref REVISION --output ARCHIVE.zip`.
The output includes the commit, archive digest, and native build digest.
