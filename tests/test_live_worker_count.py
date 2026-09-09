import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app_bridge import ApplicationBridge
from isolated_supervisor import reconcile_slots, Slot


class ResizeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.data=Path(self.temp.name)
        self.config={'sweep':{'workers':2,'account_profiles':['one','two','three']}}
        self.slots=[Slot(i,self.config,self.data) for i in range(2)]
        for i,slot in enumerate(self.slots):
            slot.galaxy=i+1;slot.process=Mock(pid=100+i);slot.close=Mock()

    def test_add_remove_preserves_existing_workers_and_returns_galaxy(self):
        pending=[3,4,5]
        original=list(self.slots)
        config=copy.deepcopy(self.config);config['sweep']['workers']=3
        reconcile_slots(self.slots,pending,config,self.data)
        self.assertEqual(len(self.slots),3)
        self.assertEqual(self.slots[:2],original)
        for slot in original: slot.close.assert_not_called()
        extra=self.slots[2];extra.galaxy=pending.pop(0);extra.close=Mock()
        reconcile_slots(self.slots,pending,self.config,self.data)
        extra.close.assert_called_once()
        self.assertEqual(pending,[3,4,5])
        for slot in original: slot.close.assert_not_called()

    def test_account_replacement_only_closes_affected_slot(self):
        config=copy.deepcopy(self.config);config['sweep']['account_profiles'][1]='replacement'
        first,second=self.slots
        reconcile_slots(self.slots,[3],config,self.data)
        self.assertIs(self.slots[0],first)
        first.close.assert_not_called();second.close.assert_called_once()
        self.assertEqual(self.slots[1].galaxy,2)
        self.assertEqual(self.slots[1].account,'replacement')

    def test_invalid_count_does_not_stop_any_worker(self):
        config=copy.deepcopy(self.config);config['sweep']['workers']=6
        with self.assertRaises(ValueError):reconcile_slots(self.slots,[3],config,self.data)
        self.assertEqual(len(self.slots),2)
        for slot in self.slots:slot.close.assert_not_called()

    def test_count_command_saves_target_without_stopping_supervisor(self):
        (self.data/'config.json').write_text(json.dumps(self.config))
        bridge=ApplicationBridge(self.data)
        with patch('app_bridge.load_passwords',return_value=['test']),patch.object(bridge,'running',return_value=True),patch.object(bridge,'stop') as stop,patch.object(bridge,'start') as start:
            bridge.dispatch({'command':'set_worker_count','workerCount':3})
            stop.assert_not_called();start.assert_not_called()
        self.assertEqual(json.loads((self.data/'config.json').read_text())['sweep']['workers'],3)

    def test_missing_saved_credentials_leave_target_unchanged(self):
        (self.data/'config.json').write_text(json.dumps(self.config))
        bridge=ApplicationBridge(self.data)
        with patch('app_bridge.load_passwords',side_effect=lambda _,name: [] if name=='three' else ['test']):
            with self.assertRaisesRegex(ValueError,'agent 3'):
                bridge.dispatch({'command':'set_worker_count','workerCount':3})
        self.assertEqual(json.loads((self.data/'config.json').read_text())['sweep']['workers'],2)

    def test_snapshot_distinguishes_requested_count_from_current_pool(self):
        config=copy.deepcopy(self.config);config['sweep']['workers']=3
        (self.data/'config.json').write_text(json.dumps(config))
        bridge=ApplicationBridge(self.data)
        (bridge.data/'sweep-status.json').write_text(json.dumps({'state':'running','expectedWorkers':2,'activeWorkers':2,'workers':{}}))
        with patch('app_bridge.load_passwords',return_value=['test']),patch.object(bridge,'running',return_value=True):
            status=bridge.snapshot()['status']
        self.assertEqual(status['requestedWorkers'],3)
        self.assertEqual(status['activeWorkers'],2)
        self.assertTrue(status['workerCountPending'])
