import time
import unittest
from eog_automation.planner import plan


def snapshot():
    return {'account': 'test', 'universe': 'test', 'source': 'live', 'observed_at': time.time(),
        'resource_names': ['metal', 'crystal'], 'planets': {'A': {
            'stock': {'metal': 1000, 'crystal': 1000}, 'production': {'metal': 100, 'crystal': 100},
            'capacity': {'metal': 100000, 'crystal': 100000}, 'energy_free': 100}},
        'levels': {}, 'queues': [], 'actions': []}


def action(key, metal=0, crystal=0, production=0, hours=1, **kwargs):
    return dict(id=key, name=key, kind=kwargs.pop('kind', 'building'), planet=kwargs.pop('planet', 'A'),
        level_key=key, from_level=0, cost={'metal': metal, 'crystal': crystal}, duration_hours=hours,
        production_delta={'metal': production}, **kwargs)


class PlannerTests(unittest.TestCase):
    def test_better_than_cheapest_first(self):
        s = snapshot()
        s['actions'] = [action('cheap', metal=100, production=1), action('valuable', metal=900, production=200)]
        result = plan(s, {'horizon_hours': 12})
        self.assertEqual(result['steps'][0]['id'], 'valuable')
        self.assertGreater(result['gain'], 0)

    def test_resources_cannot_substitute(self):
        s = snapshot()
        s['planets']['A']['stock']['crystal'] = 0
        s['planets']['A']['production']['crystal'] = 0
        s['actions'] = [action('blocked', crystal=1, production=10000)]
        self.assertEqual(plan(s)['steps'], [])

    def test_wait_for_affordability(self):
        s = snapshot()
        s['actions'] = [action('mine', metal=2000, production=500)]
        result = plan(s, {'horizon_hours': 24})
        self.assertAlmostEqual(result['steps'][0]['start_hours'], 10)

    def test_reserves_are_not_spent(self):
        s = snapshot()
        s['actions'] = [action('mine', metal=1000, production=1000)]
        result = plan(s, {'horizon_hours': 24, 'reserves': {'metal': 500}})
        self.assertAlmostEqual(result['steps'][0]['start_hours'], 5)

    def test_storage_must_expand_before_large_purchase(self):
        s = snapshot()
        s['planets']['A']['capacity']['metal'] = 1500
        s['actions'] = [action('store', metal=200, capacity_delta={'metal': 5000}),
                        action('mine', metal=2000, production=1000)]
        result = plan(s, {'horizon_hours': 24})
        self.assertEqual([a['id'] for a in result['steps']], ['store', 'mine'])

    def test_prerequisite_chain_survives_negative_first_step(self):
        s = snapshot()
        s['actions'] = [action('lab', metal=500), action('tech', metal=100, production=1000,
                        kind='research', requires={'lab': 1})]
        result = plan(s, {'horizon_hours': 12})
        self.assertEqual([a['id'] for a in result['steps']], ['lab', 'tech'])
        self.assertEqual(result['steps'][1]['start_hours'], 1)

    def test_research_queue_is_account_wide(self):
        from copy import deepcopy
        s = snapshot()
        s['planets']['B'] = deepcopy(s['planets']['A'])
        s['actions'] = [action('techA', kind='research', production=500, hours=3),
                        action('techB', kind='research', planet='B', production=500, hours=3)]
        result = plan(s, {'horizon_hours': 12})
        self.assertEqual(sorted(a['start_hours'] for a in result['steps']), [0, 3])

    def test_building_and_research_can_run_together(self):
        s = snapshot()
        s['actions'] = [action('mine', production=500), action('research', production=500, kind='research')]
        self.assertEqual([a['start_hours'] for a in plan(s)['steps']], [0, 0])

    def test_energy_prerequisite(self):
        s = snapshot()
        s['planets']['A']['energy_free'] = 0
        s['actions'] = [action('power', metal=200, energy_delta=100),
                        action('mine', metal=100, production=500, energy_delta=-50)]
        self.assertEqual([a['id'] for a in plan(s)['steps']], ['power', 'mine'])

    def test_upgrade_not_repeated_without_observed_next_level(self):
        s = snapshot()
        s['actions'] = [action('mine', production=1000)]
        self.assertEqual(len(plan(s)['steps']), 1)

    def test_active_queue_cost_is_not_paid_twice(self):
        s = snapshot()
        s['actions'] = [action('mine', metal=1000, production=1000)]
        s['queues'] = [{'action_id': 'mine', 'remaining_hours': 1}]
        result = plan(s, {'horizon_hours': 2})
        self.assertEqual(result['steps'], [])
        self.assertEqual(result['projected_planets']['A']['stock']['metal'], 2200)

    def test_unknown_numeric_data_is_rejected(self):
        for invalid in (-1, float('nan'), float('inf'), None, True):
            s = snapshot()
            s['planets']['A']['stock']['metal'] = invalid
            with self.assertRaises(ValueError):
                plan(s)

    def test_over_cap_stock_not_destroyed(self):
        s = snapshot()
        s['planets']['A']['capacity']['metal'] = 500
        self.assertEqual(plan(s)['projected_planets']['A']['stock']['metal'], 1000)

    def test_short_horizon_does_not_buy_unprofitable_upgrade(self):
        s = snapshot()
        s['actions'] = [action('mine', metal=1000, production=10)]
        self.assertEqual(plan(s, {'horizon_hours': 2})['steps'], [])


if __name__ == '__main__':
    unittest.main()
