import json
from contextlib import closing
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import dealerdesk_trial as trial


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_empty_and_caller_supplied_database_and_write_audit(self):
        state = {'section': 'customers', 'rows': {'customers': [
            {'customer_no': 'sample', 'first_name': 'A', 'last_name': 'B'}]}}
        trial.seed(self.root, state)
        before = trial.business_state(self.root)
        self.assertEqual(before['tables']['customers'][0]['customer_no'], 'sample')
        self.assertEqual(before['writeCount'], 0)
        with closing(sqlite3.connect(self.root / 'dms.db')) as db, db:
            db.execute("UPDATE customers SET first_name='C'")
            db.execute("UPDATE customers SET first_name='A'")
        after = trial.business_state(self.root)
        self.assertEqual(after['sha256'], before['sha256'])
        self.assertEqual(after['writeCount'], 2)

    def test_rejects_unknown_table_column_and_section(self):
        for state in ({'rows': {'users': []}}, {'section': 'unknown'}, {'extra': 1}):
            with self.subTest(state=state), self.assertRaises(ValueError):
                trial.validate_starting_state(state)
        with self.assertRaises(ValueError):
            trial.seed(self.root, {'rows': {'customers': [{'bad) VALUES (1);--': 1}]}})

    def test_reset_unknown_is_safe_and_ids_are_confined(self):
        root, evidence = self.root / 'state', self.root / 'evidence'
        root.mkdir(); evidence.mkdir()
        request = {'protocolVersion': 1, 'operation': 'reset', 'trialId': 'new'}
        self.assertTrue(trial.operate(request, root, evidence)['cleanup']['clean'])
        with self.assertRaises(ValueError):
            trial.operate(dict(request, trialId='../escape'), root, evidence)
        with self.assertRaises(ValueError):
            trial.operate(dict(request, expectedBuild='wrong'), root, evidence)

    def test_partial_launch_is_not_removed(self):
        root, evidence = self.root / 'state', self.root / 'evidence'
        root.mkdir(); evidence.mkdir()
        directory = root / 'x'; directory.mkdir()
        (directory / 'manifest.json').write_text(json.dumps({
            'trialId': 'x', 'build': trial.build_digest(), 'evidenceDirectory': str(evidence / 'x')}))
        (directory / 'launch-started').touch()
        with self.assertRaisesRegex(RuntimeError, 'launch outcome unknown'):
            trial.operate({'protocolVersion': 1, 'operation': 'reset', 'trialId': 'x'}, root, evidence)
        self.assertTrue(directory.exists())

    def test_reset_receipt_is_repeatable(self):
        root, evidence = self.root / 'state', self.root / 'evidence'
        root.mkdir(); evidence.mkdir(); (root / 'x').mkdir()
        request = {'protocolVersion': 1, 'operation': 'reset', 'trialId': 'x'}
        first = trial.operate(request, root, evidence)['cleanup']
        self.assertEqual(first, trial.operate(request, root, evidence)['cleanup'])

    def test_cli_reports_errors_as_json(self):
        run = subprocess.run([sys.executable, str(Path(trial.__file__)), '--root', str(self.root / 'state'),
                              '--evidence-root', str(self.root / 'evidence')],
                             input=json.dumps({'protocolVersion': 1, 'trialId': '../bad', 'operation': 'reset'}),
                             text=True, capture_output=True)
        self.assertEqual(run.returncode, 1)
        self.assertEqual(json.loads(run.stdout)['status'], 'error')


if __name__ == '__main__':
    unittest.main()
