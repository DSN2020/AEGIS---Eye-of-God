DEFAULT_PROFILE={'universe':'EV-T ORION 1','coordinate':'1:25:10','reserves':dict.fromkeys(('metal','crystal','gas'),50000000),'max_upgrade_cost':10000000}
from copy import deepcopy
from pathlib import Path
import tempfile
import time
import unittest
from eog_automation.live import Controller
from eog_automation.evo_screen import building, amount
from eog_automation.executor import ExecutionBlocked
from test_automation_screen import solar


class LiveTransactionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.controller = Controller(None,None,Path(self.temp.name),'ExampleAccount',deepcopy(DEFAULT_PROFILE),
            lambda *a,**k:None,lambda:None,{'account':'ExampleAccount','universe':'EV-T ORION 1'})
        self.action = building(solar(),'Solar Plant')
        self.balance = {'observed_at':time.time(),'stock':{r:amount('400M') for r in ('metal','crystal','gas')}}
        self.clicks = 0
        async def stable(parser): return deepcopy(self.action)
        async def click(point): self.clicks += 1
        async def read(): return []
        self.controller.stable = stable
        self.controller.click = click
        self.controller.read = read

    def tearDown(self):
        self.controller.close()
        self.temp.cleanup()

    async def test_queue_confirmation_records_one_click(self):
        parser = lambda lines:{'name':'Solar Plant','level':4,'busy':True,'to_level':5}
        await self.controller.purchase(self.action,self.balance,parser)
        self.assertEqual(self.clicks,1)
        self.assertFalse(self.controller.journal.unresolved('ExampleAccount','EV-T ORION 1'))

    async def test_pending_intent_blocks_second_process(self):
        self.controller.journal.begin({'account':'ExampleAccount','universe':'EV-T ORION 1'},self.action)
        with self.assertRaises(ExecutionBlocked):
            await self.controller.purchase(self.action,self.balance,lambda lines:{})
        self.assertEqual(self.clicks,0)

    async def test_old_stock_snapshot_blocks_click(self):
        self.balance['observed_at'] = 0
        with self.assertRaises(ExecutionBlocked):
            await self.controller.purchase(self.action,self.balance,lambda lines:{})
        self.assertEqual(self.clicks,0)

    async def test_cost_changed_before_click(self):
        original = deepcopy(self.action)
        self.action['cost']['metal'] = amount('400')
        with self.assertRaises(ExecutionBlocked):
            await self.controller.purchase(original,self.balance,lambda lines:{})
        self.assertEqual(self.clicks,0)
