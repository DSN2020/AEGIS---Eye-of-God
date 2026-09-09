import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ev_assistant.store import Planet, Store


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / 'test.sqlite')
        self.store.seed('test', [1], range(1, 21))

    def test_concurrent_workers_never_claim_same_system(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            leases = list(pool.map(lambda _: self.store.claim('test', now=100), range(20)))
        self.assertEqual(len({(x.galaxy, x.system) for x in leases}), 20)
        self.assertIsNone(self.store.claim('test', now=100))

    def test_expired_worker_cannot_overwrite_new_owner(self):
        old = self.store.claim('test', now=100)
        new = self.store.claim('test', now=161)
        self.assertEqual(old.system, new.system)
        with self.assertRaises(ValueError):
            self.store.complete(old, [Planet(1, 'old', 'P')], fully_read=True, now=162)
        self.store.complete(new, [Planet(1, 'new', 'P')], fully_read=True, now=162)
        self.assertEqual(self.store.search()[0]['player'], 'new')

    def test_partial_read_preserves_existing_planets(self):
        lease = self.store.claim('test', now=100)
        self.store.complete(lease, [Planet(1, 'alice', 'Home')], fully_read=True, now=101)
        with self.assertRaises(ValueError):
            self.store.complete(lease, [], fully_read=False, now=102)
        self.assertEqual(len(self.store.search('ALICE')), 1)

    def test_failure_backoff_and_restart(self):
        lease = self.store.claim('test', now=100)
        self.store.fail(lease, now=101)
        restarted = Store(self.store.path)
        self.assertEqual(restarted.claim('test', now=102).system, 2)
        with self.store.connection() as db:
            row = db.execute('SELECT due,failures FROM scans WHERE system=1').fetchone()
        self.assertEqual(tuple(row), (111, 1))

    def test_stale_worker_cannot_record_partial_sighting(self):
        lease = self.store.claim('test', now=100)
        with self.assertRaises(ValueError):
            self.store.record_sighting('test', 1, lease.system,
                                      Planet(1, 'stale', ''), now=161, lease=lease)
        self.assertEqual(self.store.search(), [])

    def test_partial_pass_keeps_other_slots_and_does_not_claim_full_coverage(self):
        self.store.record_sighting('test', 1, 1, Planet(9, 'existing', ''), now=99)
        lease = self.store.claim('test', now=100)
        self.store.record_sighting('test', 1, 1, Planet(1, 'new', ''), now=101, lease=lease)
        self.store.finish_pass(lease, rescan_seconds=1000, now=102)
        self.assertEqual(len(self.store.search()), 2)
        with self.store.connection() as db:
            row = db.execute('SELECT due,last_complete,token FROM scans WHERE system=1').fetchone()
        self.assertEqual(tuple(row), (1102, None, None))

    def test_universes_isolated_and_seed_is_idempotent(self):
        self.store.seed('test', [1], range(1, 21))
        self.store.seed('second', [1], [1])
        lease = self.store.claim('second', now=100)
        self.assertEqual(lease.universe, 'second')
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM scans').fetchone()[0], 21)

    def test_complete_empty_scan_removes_current_but_keeps_history(self):
        small = Store(Path(self.tmp.name) / 'small.sqlite')
        small.seed('test', [1], [1])
        lease = small.claim('test', now=100)
        small.complete(lease, [Planet(1, 'alice', 'Home')], fully_read=True,
                       rescan_seconds=10, now=101)
        lease = small.claim('test', now=112)
        small.complete(lease, [], fully_read=True, now=113)
        self.assertEqual(small.search(), [])
        with small.connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM sightings').fetchone()[0], 1)


if __name__ == '__main__':
    unittest.main()
