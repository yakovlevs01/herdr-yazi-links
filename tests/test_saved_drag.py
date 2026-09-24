import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('saved_drag', ROOT/'scripts/saved-drag.py')
saved = importlib.util.module_from_spec(spec)
spec.loader.exec_module(saved)

class SavedReceivers(unittest.TestCase):
    def child(self):
        return Mock(stdout=io.BytesIO(b'READY\n'), poll=Mock(return_value=None))

    def test_profiles_disabled_deduplicated_and_invalid_rejected(self):
        row = dict(enabled=True, target='ssh://user@host:2222', session='default')
        self.assertEqual(saved.targets([row, row, dict(row, enabled=False)]), {(row['target'],'default')})
        with self.assertRaises(ValueError): saved.targets([dict(row, target='-unsafe')])
        with self.assertRaises(ValueError): saved.targets({})

    def test_independent_receivers_removal_and_session_change(self):
        a, b, c = self.child(), self.child(), self.child()
        manager = saved.Receivers('/python', {}, io.StringIO())
        keys = {('mac','one'), ('iw','two')}
        with patch.object(saved.subprocess, 'Popen', side_effect=[a,b,c]) as spawn, patch.object(saved.select, 'select', side_effect=lambda streams,*args:(streams,[],[])):
            manager.reconcile(keys, 0)
            manager.reconcile(keys, 1)
            self.assertTrue(all(row['ready'] for row in manager.status()))
            retained = manager.children[('iw','two')]['process']
            removed = manager.children[('mac','one')]['process']
            manager.reconcile({('iw','two'),('mac','new')}, 2)
            removed.terminate.assert_called_once()
            retained.terminate.assert_not_called()
            self.assertEqual(spawn.call_count,3)
            manager.close()

    def test_failed_connection_retries_without_restarting_other_host(self):
        a,b,c = self.child(),self.child(),self.child()
        manager=saved.Receivers('/python',{},io.StringIO())
        keys={('mac','one'),('iw','two')}
        with patch.object(saved.subprocess,'Popen',side_effect=[a,b,c]) as spawn, patch.object(saved.select,'select',return_value=([],[],[])):
            manager.reconcile(keys,0)
            failed=manager.children[('mac','one')]['process']
            healthy=manager.children[('iw','two')]['process']
            failed.poll.return_value=1
            manager.reconcile(keys,1)
            manager.reconcile(keys,2)
            self.assertEqual(spawn.call_count,2)
            manager.reconcile(keys,4)
            self.assertEqual(spawn.call_count,3)
            healthy.terminate.assert_not_called()
            manager.close()

if __name__=='__main__': unittest.main()
