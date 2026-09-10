import tempfile
from pathlib import Path
import unittest
from eog_automation.executor import Journal, execute_one, ExecutionBlocked
from test_automation_planner import snapshot, action


class FakeAdapter:
    calibrated = True
    def __init__(self, confirmed=True, prepared=True):
        self.clicks = 0
        self.confirmed, self.prepared = confirmed, prepared
    async def prepare_and_verify(self, state, action): return self.prepared
    async def commit(self, action): self.clicks += 1
    async def confirm(self, state, action): return self.confirmed


class ExecutorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'journal.sqlite'
        self.journal = Journal(self.path)
        self.state = snapshot()
        self.action = action('mine', metal=100)
        self.state['actions'] = [self.action]
    def tearDown(self):
        self.journal.close()
        self.tmp.cleanup()

    async def test_success_is_journaled(self):
        adapter = FakeAdapter()
        key = await execute_one(adapter, self.journal, self.state, self.action, {})
        self.assertEqual(adapter.clicks, 1)
        self.assertEqual(self.journal.db.execute('SELECT status FROM actions WHERE id=?', (key,)).fetchone()[0], 'confirmed')

    async def test_uncertain_action_blocks_retry_after_restart(self):
        adapter = FakeAdapter(confirmed=False)
        with self.assertRaises(ExecutionBlocked):
            await execute_one(adapter, self.journal, self.state, self.action, {})
        self.journal.close()
        self.journal = Journal(self.path)
        with self.assertRaises(ExecutionBlocked):
            await execute_one(adapter, self.journal, self.state, self.action, {})
        self.assertEqual(adapter.clicks, 1)

    async def test_import_demo_and_stale_data_cannot_execute(self):
        for source, when in [('demo', self.state['observed_at']), ('import', self.state['observed_at']), ('live', 0)]:
            self.state.update(source=source, observed_at=when)
            adapter = FakeAdapter()
            with self.assertRaises(ExecutionBlocked):
                await execute_one(adapter, self.journal, self.state, self.action, {})
            self.assertEqual(adapter.clicks, 0)

    async def test_mismatch_does_not_click(self):
        adapter = FakeAdapter(prepared=False)
        with self.assertRaises(ExecutionBlocked):
            await execute_one(adapter, self.journal, self.state, self.action, {})
        self.assertEqual(adapter.clicks, 0)

    async def test_pause_before_commit(self):
        adapter = FakeAdapter()
        with self.assertRaises(ExecutionBlocked):
            await execute_one(adapter, self.journal, self.state, self.action, {}, stopped=lambda: True)
        self.assertEqual(adapter.clicks, 0)

    async def test_premium_and_reserves_block(self):
        self.action['premium_cost'] = 1
        adapter = FakeAdapter()
        with self.assertRaises(ExecutionBlocked):
            await execute_one(adapter, self.journal, self.state, self.action, {})
        self.action.pop('premium_cost')
        with self.assertRaises(ExecutionBlocked):
            await execute_one(adapter, self.journal, self.state, self.action, {'reserves': {'metal': 950}})
        self.assertEqual(adapter.clicks, 0)
