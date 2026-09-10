import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock,Mock,patch
from eog_automation import evo_screen as screen
from eog_automation.engine import PlanController
from eog_automation.executor import ExecutionBlocked
from eog_automation.model import validate
from eog_automation.nebula import use_gamma
from eog_automation.vision import TextLine,UncertainScreen

def profile(mode='plan'):
    return validate({'name':'Nebula','account':'ExampleAccount','coordinate':'1:25:10','mode':mode,
        'steps':[{'kind':'wait','name':'Wait','value':1}],
        'rules':[{'metric':'safe_runs','op':'<=','value':0,'action':'use_gamma','cooldown':300}]})

class NebulaScreens(unittest.TestCase):
    def setUp(self):
        raw=json.loads((Path(__file__).parent/'fixtures'/'automation_nebula_controls.json').read_text())
        self.frames={k:[TextLine(**r) for r in rows] for k,rows in raw.items()}
    def test_captured_dialogs_and_safe_counter(self):
        self.assertEqual(screen.nebula(self.frames['Nebula Controls'],'1:25:10')['available'],24)
        self.assertEqual(screen.gamma_store(self.frames['Verified Store'])['owned'],13)
        self.assertEqual(screen.gamma_quantity(self.frames['Gamma Use'])['quantity'],1)
        self.assertEqual(screen.gamma_confirmation(self.frames['Gamma Confirm'])['quantity'],1)
        self.assertEqual(screen.colony_return(self.frames['Map Return'],'1:25:10')['coordinate'],'1:25:10')
    def test_wrong_coordinate_or_quantity_rejected(self):
        with self.assertRaises(UncertainScreen):screen.nebula(self.frames['Nebula Controls'],'1:26:10')
        lines=[TextLine('2' if l.text=='1' else l.text,l.confidence,l.x,l.y) for l in self.frames['Gamma Use']]
        with self.assertRaises(UncertainScreen):screen.gamma_quantity(lines)
        lines=[TextLine(l.text.replace('x1?','x2?'),l.confidence,l.x,l.y) for l in self.frames['Gamma Confirm']]
        with self.assertRaises(UncertainScreen):screen.gamma_confirmation(lines)
    def test_buy_confirmation_never_accepted(self):
        lines=[TextLine(l.text.replace('Use Gamma','Buy Gamma'),l.confidence,l.x,l.y) for l in self.frames['Gamma Confirm']]
        with self.assertRaises(UncertainScreen):screen.gamma_confirmation(lines)
    def test_activation_only_for_exhausted_safe_runs(self):
        p=profile()
        for field,value in [('metric','metal'),('value',1),('op','>='),('action','buy_gamma')]:
            p=profile();p['rules'][0][field]=value
            with self.assertRaises(ValueError):validate(p)

class OwnedGammaTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();path=Path(self.temp.name)
        self.c=PlanController(None,None,path,'ExampleAccount',profile(),Mock(),lambda:None,{},progress_path=path/'progress.json')
        self.c.home=AsyncMock();self.c.click=AsyncMock();self.c.record=Mock()
        self.observed={'available':0,'limit':24,'observed_at':time.time()}
    def tearDown(self):self.c.close();self.temp.cleanup()
    async def test_watch_mode_reports_without_using(self):
        self.c.profile['mode']='watch'
        with patch('eog_automation.nebula.safe_runs',AsyncMock(return_value=self.observed)),patch('eog_automation.nebula.use_gamma',AsyncMock()) as use:
            await self.c.watch_nebula();await self.c.watch_nebula();use.assert_not_awaited()
        self.c.record.assert_called_once()
    async def test_account_journal_enforces_24_hour_limit(self):
        key=self.c.journal.begin({'account':'EXAMPLEACCOUNT','universe':self.c.profile['universe']},{'kind':'use_gamma'})
        self.c.journal.finish(key,'confirmed')
        with patch('eog_automation.nebula.safe_runs',AsyncMock(return_value=self.observed)),patch('eog_automation.nebula.use_gamma',AsyncMock()) as use:
            await self.c.watch_nebula();use.assert_not_awaited()
    async def test_confirmed_use_requires_inventory_and_restored_runs(self):
        self.c.stable=AsyncMock(side_effect=[{'quantity':1},{'owned':12}])
        with patch('eog_automation.nebula.prepare_gamma',AsyncMock(return_value=({'owned':13},{'button':[148,565]}))),patch('eog_automation.nebula.safe_runs',AsyncMock(return_value={'available':20})):
            self.assertTrue(await use_gamma(self.c,self.observed))
        self.assertIsNone(self.c.journal.unresolved(self.c.account,self.c.profile['universe']))
        self.assertEqual(self.c.journal.count_recent(self.c.account,self.c.profile['universe'],'use_gamma'),1)
        self.c.click.assert_awaited_once()
    async def test_uncertain_use_remains_blocked(self):
        self.c.stable=AsyncMock(side_effect=[{'quantity':1},{'owned':13}])
        with patch('eog_automation.nebula.prepare_gamma',AsyncMock(return_value=({'owned':13},{'button':[148,565]}))):
            with self.assertRaises(ExecutionBlocked):await use_gamma(self.c,self.observed)
        self.assertIsNotNone(self.c.journal.unresolved(self.c.account,self.c.profile['universe']))
        self.c.click.assert_awaited_once()
    async def test_stale_counter_never_opens_store(self):
        self.observed['observed_at']=time.time()-91
        with patch('eog_automation.nebula.prepare_gamma',AsyncMock()) as prepare:
            with self.assertRaises(ExecutionBlocked):await use_gamma(self.c,self.observed)
            prepare.assert_not_awaited()
