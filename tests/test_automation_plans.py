import copy
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch, Mock
from eog_automation.model import validate, preset, timestamp
from eog_automation.service import Service, AccountLock, reserved_accounts
from eog_automation.engine import PlanController
from eog_automation.executor import ExecutionBlocked
from eog_automation.storage import atomic_json

def profile():
    return validate({'name':'Economy','account':'ExampleAccount','coordinate':'1:25:10','mode':'plan',
      'steps':[{'kind':'building','name':'Solar Plant','value':5}]})
def balance(value=100000000):
    return {'observed_at':time.time(),'stock':{r:{'low':value,'high':value} for r in ('metal','crystal','gas')},'energy':{'low':100,'high':100}}

class ModelTests(unittest.TestCase):
    def test_defaults_contain_no_credentials(self):
        p=profile();p['password']='private';p['token']='private'
        self.assertNotIn('password',validate(p));self.assertNotIn('token',validate(p))
    def test_preset_strips_identity_schedule(self):
        p=profile();p.update(startAt='2026-09-09T22:00:00-04:00',endAt='2026-09-10T22:00:00-04:00')
        v=preset(p,'Repeat')['settings']
        self.assertTrue({'account','coordinate','id','startAt','endAt'}.isdisjoint(v))
        self.assertEqual(v['steps'],p['steps'])
    def test_bad_schedule(self):
        p=profile();p.update(startAt='2026-09-10T12:00:00+00:00',endAt='2026-09-09T12:00:00+00:00')
        with self.assertRaises(ValueError):validate(p)
        with self.assertRaises(ValueError):timestamp('2026-09-10 12:00')
    def test_nonfinite_and_bad_coordinates(self):
        for key,value in [('interval',float('nan')),('max_upgrade_cost',-1),('coordinate','1:500:10'),('coordinate','1:1:21')]:
            p=profile();p[key]=value
            with self.assertRaises(ValueError):validate(p)
    def test_uncalibrated_action_rejected(self):
        p=profile();p['rules']=[{'metric':'safe_runs','op':'<=','value':0,'action':'gamma'}]
        with self.assertRaises(ValueError):validate(p)
    def test_no_fractional_levels(self):
        p=profile();p['steps'][0]['value']=2.5
        with self.assertRaises(ValueError):validate(p)

class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        atomic_json(self.root/'config.json',{'sweep':{'account_profiles':['ExampleAccount']}})
        self.service=Service(self.root)
    def tearDown(self):self.service.db.close();self.temp.cleanup()
    def test_resume_progress_and_reset_only_changed_plan(self):
        p=self.service.save(profile());path=self.service.path(p)/'progress.json'
        atomic_json(path,{'index':1,'entered':0,'alerts':{}})
        p['name']='Renamed';self.service.save(p)
        self.assertEqual(json.loads(path.read_text())['index'],1)
        p['steps'][0]['value']=6;self.service.save(p)
        self.assertEqual(json.loads(path.read_text())['index'],0)
    def test_active_profile_cannot_edit_or_delete(self):
        p=self.service.save(profile());atomic_json(self.service.claim(p),{'account':p['account'],'profileId':p['id']})
        with self.assertRaises(ValueError):self.service.save(p)
        with self.assertRaises(ValueError):self.service.dispatch({'command':'automation_delete','id':p['id']})
        self.assertEqual(reserved_accounts(self.root/'data'),{'exampleaccount'})
    def test_account_lock_rejects_second_controller(self):
        p=self.service.save(profile());path=self.service.account_path(p)/'worker.lock'
        with AccountLock(path):
            with self.assertRaises(RuntimeError):AccountLock(path)
    def test_pause_dead_worker_releases_claim(self):
        p=self.service.save(profile());atomic_json(self.service.claim(p),{'account':p['account'],'profileId':p['id'],'created':0})
        self.service.pause(p['id']);self.assertFalse(self.service.claim(p).exists())
    def test_future_schedule_does_not_pause_scanning(self):
        p=self.service.save(profile())
        atomic_json(self.service.claim(p,scheduled=True),{'account':p['account'],'profileId':p['id'],'created':0})
        self.assertTrue(self.service.active(p));self.assertEqual(reserved_accounts(self.root/'data'),set())
        self.service.pause(p['id']);self.assertFalse(self.service.active(p))

    def test_public_profile_blank_account_rejected(self):
        p=profile();p['account']=''
        with self.assertRaises(ValueError):self.service.save(p)

class EngineTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name);self.p=profile()
        self.c=PlanController(None,None,self.path,'ExampleAccount',self.p,Mock(),lambda:None,{},progress_path=self.path/'progress.json')
        self.c.home=AsyncMock(return_value=balance());self.c.verify_colony=AsyncMock();self.c.purchase=AsyncMock()
        self.action={'name':'Solar Plant','level':4,'busy':False,'cost':{r:{'low':10,'high':10} for r in ('metal','crystal','gas')}}
        self.c.acquire_upgrade=AsyncMock(return_value=(self.action,lambda lines:{}))
    def tearDown(self):self.c.close();self.temp.cleanup()
    async def test_queueing_does_not_advance_plan(self):
        await self.c.run_step(balance());self.c.purchase.assert_awaited_once();self.assertEqual(self.c.progress['index'],0)
    async def test_completion_advances_exactly_one(self):
        self.action['level']=5;await self.c.run_step(balance());self.assertEqual(self.c.progress['index'],1);self.c.purchase.assert_not_awaited()
    async def test_busy_waits(self):
        self.action['busy']=True;await self.c.run_step(balance());self.assertEqual(self.c.progress['index'],0);self.c.purchase.assert_not_awaited()
    async def test_short_resources_wait_without_error(self):
        await self.c.run_step(balance(5));self.assertEqual(self.c.progress['index'],0);self.c.purchase.assert_not_awaited()
    async def test_reserves_prevent_purchase(self):
        self.p['reserves']['metal']=100000000;await self.c.run_step(balance());self.c.purchase.assert_not_awaited()
    async def test_watch_mode_never_executes(self):
        self.p['mode']='watch';await self.c.cycle();self.c.acquire_upgrade.assert_not_awaited();self.c.purchase.assert_not_awaited()
    async def test_wait_resumes_from_saved_time(self):
        self.p['steps']=[{'kind':'wait','name':'Wait','value':10}]
        self.c.progress['entered']=time.time()-11;self.c.save_progress();await self.c.run_step(balance());self.assertEqual(self.c.progress['index'],1)
    async def test_resource_step_requires_conservative_balance(self):
        self.p['steps']=[{'kind':'resource','name':'metal','value':100}];await self.c.run_step(balance(99));self.assertEqual(self.c.progress['index'],0)
        await self.c.run_step(balance(100));self.assertEqual(self.c.progress['index'],1)
    async def test_unresolved_intent_blocks_cycle(self):
        self.c.journal.begin({'account':'ExampleAccount','universe':'EV-T ORION 1'},self.action)
        with self.assertRaises(ExecutionBlocked):await self.c.cycle()
        self.c.verify_colony.assert_not_awaited()
    def test_watch_rule_cooldown(self):
        self.p['rules']=[{'metric':'metal','op':'>=','value':1,'cooldown':300,'action':'alert'}]
        self.c.record=Mock();self.c.watch(balance());self.c.watch(balance());self.c.record.assert_called_once()

class HandoffTests(unittest.TestCase):
    def test_reserved_worker_retains_galaxy_and_does_not_launch(self):
        from isolated_supervisor import Slot
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);slot=Slot(0,{'sweep':{'account_profiles':['ExampleAccount']}},root)
            slot.galaxy=3;slot.process=Mock();slot.close=Mock(side_effect=lambda:setattr(slot,'process',None));slot.start=Mock()
            atomic_json(root/'automation'/'reservations'/'claim.json',{'account':'ExampleAccount'})
            slot.service([],499)
            slot.close.assert_called_once();slot.start.assert_not_called();self.assertEqual(slot.galaxy,3);self.assertEqual(slot.state,'managing')

class LoginLayoutTests(unittest.IsolatedAsyncioTestCase):
    async def test_offscreen_registration_inputs_are_excluded(self):
        from eog_automation.worker import onscreen
        fields=[Mock(),Mock(),Mock()]
        for f in fields:f.evaluate=AsyncMock(return_value=True)
        fields[0].bounding_box=AsyncMock(return_value={'x':76,'y':548,'width':318,'height':48})
        fields[1].bounding_box=AsyncMock(return_value={'x':546,'y':494,'width':318,'height':48})
        fields[2].bounding_box=AsyncMock(return_value=None)
        page=Mock();page.locator.return_value.element_handles=AsyncMock(return_value=fields)
        self.assertEqual(await onscreen(page,'input'),[fields[0]])

    async def test_covered_form_controls_are_not_used(self):
        from eog_automation.worker import onscreen
        field=Mock();field.bounding_box=AsyncMock(return_value={'x':76,'y':548,'width':318,'height':48})
        field.evaluate=AsyncMock(side_effect=[True,False])
        page=Mock();page.locator.return_value.element_handles=AsyncMock(return_value=[field])
        self.assertEqual(await onscreen(page,'input'),[])

class ResourceHeaderTests(unittest.IsolatedAsyncioTestCase):
    async def test_rendered_header_preserves_negative_energy(self):
        from eog_automation.live import Controller
        from eog_automation.evo_screen import home
        from eog_automation.vision import TextLine
        with tempfile.TemporaryDirectory() as folder:
            page=Mock();page.url='https://eternal-void.online/'
            page.locator.return_value.count=AsyncMock(return_value=0);page.screenshot=AsyncMock(return_value=b'preview')
            ocr=Mock();ocr.read.return_value=[TextLine('Planets Fleet Alliance',1,200,860),TextLine('502',1,276,77)]
            lines=[TextLine(t,1,x,77) for t,x in [('437M',60),('438M',135),('473M',210),('-502',276)]]
            c=Controller(page,ocr,Path(folder),'ExampleAccount',profile(),Mock(),lambda:None,{})
            try:
                with patch('ev_assistant.rendered_text.read_rendered_text',AsyncMock(return_value=(1,lines))):
                    value=home(await c.read());self.assertEqual(value['energy']['low'],-502)
            finally:c.close()

class RenderedControlsTests(unittest.IsolatedAsyncioTestCase):
    async def test_controls_survive_wrapped_prose_and_outline_duplicates(self):
        from eog_automation.rendered import read_controls
        page=Mock();page.evaluate=AsyncMock(return_value={'frame':12,'rows':[
            {'text':'Solar Plant','x':235,'y':32},{'text':'Solar Plant','x':236,'y':33},
            {'text':'Descriptive\nprose','x':235,'y':550},{'text':'Upgrade','x':354,'y':828}]})
        lines=await read_controls(page)
        self.assertEqual([line.text for line in lines],['Solar Plant','Upgrade'])
