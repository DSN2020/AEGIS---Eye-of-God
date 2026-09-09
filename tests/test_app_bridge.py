import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from app_bridge import ApplicationBridge, recent_activity, startup_progress
from ev_assistant.store import Planet
from ev_assistant.slot_verifier import parse_alliance
from ev_assistant.vision import TextLine

class AllianceTests(unittest.TestCase):
    def test_alliance_is_its_own_row_and_preserves_unicode(self):
        self.assertEqual(parse_alliance([TextLine('Alliance: pop',.99,140,324)]),'pop')
        self.assertEqual(parse_alliance([TextLine('Alliance\uff1a\u661f\u7a7a',.99,140,324)]),'\u661f\u7a7a')
        self.assertEqual(parse_alliance([TextLine('Alliance:',.99,140,324),
            TextLine('Transport',.99,140,360)]),'')
        self.assertIsNone(parse_alliance([TextLine('Alliance: uncertain',.60,140,324)]))

class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        (self.root/'config.json').write_text(json.dumps({'sweep':{'workers':1,
            'account_profiles':['alpha','beta']}}))
        self.bridge=ApplicationBridge(self.root)
        self.patcher=patch('app_bridge.load_passwords',return_value=['test-only-marker'])
        self.patcher.start();self.addCleanup(self.patcher.stop)

    def test_validation_rejects_duplicate_accounts_and_empty_active_slots(self):
        for accounts in ([{'username':'same'},{'username':'SAME'}],
                         [{'username':'first'},{'username':''}]):
            with self.assertRaises(ValueError):
                self.bridge.validate_settings({'workerCount':2,'accounts':accounts})

    def test_snapshot_groups_coordinates_and_preserves_unknown_alliance(self):
        s=self.bridge.store
        s.record_sighting('test',9,57,Planet(14,'Nazim','Renamed'))
        s.record_sighting('test',9,58,Planet(5,'Nazim','Other'))
        s.record_sighting('test',1,1,Planet(5,'Other','Other'))
        s.record_sighting('test',1,2,Planet(5,'bot_1_2_5','Bot'))
        s.record_alliance('test','Nazim','pop')
        s.record_alliance('test','Nazim',None)
        with patch.object(self.bridge,'running',return_value=False):
            snapshot=self.bridge.snapshot()
        self.assertEqual(snapshot['playerCount'],2)
        self.assertEqual(snapshot['coordinateCount'],3)
        player=next(x for x in snapshot['players'] if x['name']=='Nazim')
        self.assertEqual(player['coordinates'],['9:57:14','9:58:5'])
        self.assertEqual(player['alliance'],'pop')
        self.assertIsNone(next(x for x in snapshot['players'] if x['name']=='Other')['alliance'])
        self.assertNotIn('test-only-marker',json.dumps(snapshot))

    def test_saving_keeps_passwords_out_of_config_and_binds_new_profile_to_account(self):
        request={'workerCount':1,'accounts':[{'username':'newuser','password':'private-test-value'},
                                             {'username':'beta','password':''}]}
        with patch('app_bridge.save_passwords') as save:
            self.bridge.save_settings(request)
        config=json.loads((self.root/'config.json').read_text())
        self.assertNotIn('private-test-value',json.dumps(config))
        self.assertTrue(config['browser_profiles']['newuser'].startswith('browser-account-'))
        self.assertEqual(config['browser_profiles']['alpha'],'browser-profile')
        save.assert_called_once_with(self.bridge.data,'newuser',['private-test-value'])

    def test_invalid_apply_does_not_stop_current_scan(self):
        with patch.object(self.bridge,'stop') as stop:
            with self.assertRaises(ValueError):
                self.bridge.dispatch({'command':'apply','workerCount':7,'accounts':[]})
            stop.assert_not_called()

    def test_restart_request_targets_one_agent(self):
        with patch.object(self.bridge,'running',return_value=True):
            self.bridge.dispatch({'command':'restart_worker','index':1})
        self.assertEqual(json.loads((self.bridge.data/'worker-command.json').read_text()),
                         {'action':'restart','index':1})

    def test_activity_is_merged_by_time_and_ids_survive_polling(self):
        data=self.root/'data'
        (data/'sweep-status.json').write_text(json.dumps({'workers':{
            '1':{'account':'alpha'},'2':{'account':'beta'}}}))
        (data/'worker-1.log').write_text('2026-09-09 12:00:01,000 INFO older\n2026-09-09 12:00:03,000 ERROR newest\n  diagnostic continuation\n')
        (data/'worker-2.log').write_text('2026-09-09 12:00:02,000 INFO middle\n')
        with patch.object(self.bridge,'running',return_value=False):
            first=self.bridge.snapshot()['activity']
            second=self.bridge.snapshot()['activity']
        self.assertEqual([e['account'] for e in first],['alpha','beta','alpha'])
        self.assertIn('diagnostic continuation',first[0]['text'])
        self.assertEqual([e['id'] for e in first],[e['id'] for e in second])

    def test_player_directory_uses_latest_observation_not_name(self):
        with patch('ev_assistant.store.time.time',return_value=100):
            self.bridge.store.record_sighting('test',1,1,Planet(1,'Alpha',''))
        with patch('ev_assistant.store.time.time',return_value=200):
            self.bridge.store.record_sighting('test',1,1,Planet(2,'Zulu',''))
        with patch.object(self.bridge,'running',return_value=False):
            self.assertEqual([p['name'] for p in self.bridge.snapshot()['players']],['Zulu','Alpha'])

    def test_startup_phase_ignores_login_from_previous_launch(self):
        events=[{'timestamp':100,'text':'START account=test'},
                {'timestamp':110,'text':'INFO Scanner animation limit: 20 FPS'},
                {'timestamp':200,'text':'START account=test'}]
        worker={'state':'starting'}
        self.assertEqual(startup_progress(worker,events,now=230),200)
        self.assertEqual(worker['detail'],'Loading game and signing in · 30s since launch')
        events.append({'timestamp':225,'text':'INFO Scanner animation limit: 20 FPS'})
        startup_progress(worker,events,now=235)
        self.assertEqual(worker['detail'],'Signed in; opening the galaxy map · 35s since launch')
        worker={'state':'active','detail':'verified slot 6:1:1 (npc)'}
        startup_progress(worker,events,now=240)
        self.assertEqual(worker['detail'],'verified slot 6:1:1 (npc)')
