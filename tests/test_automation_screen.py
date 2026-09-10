DEFAULT_PROFILE={'universe':'EV-T ORION 1','coordinate':'1:25:10','reserves':dict.fromkeys(('metal','crystal','gas'),50000000),'max_upgrade_cost':10000000}
import unittest
from eog_automation.vision import TextLine, UncertainScreen
from eog_automation.evo_screen import amount, duration, home, building, tech_card
from eog_automation.live import affordable
from eog_automation.executor import ExecutionBlocked


def line(value, x, y, confidence=.99):
    return TextLine(value,confidence,x,y)


def solar():
    return [line('Solar Plant',235,32),line('Level: 4',90,153),line('Produces',86,195),line('190',72,220),
        line('Required for upgrade to Level 5',195,331),line('380',92,387),line('152',218,387),line('0',326,387),
        line('Upgrade requires:',110,429),line('19s',228,429),line('Teardown',117,828),line('Upgrade',353,828)]


def tech():
    return [line('Computer Tech',239,188),line('51.2K',219,218),line('76.8K',289,218),
            line('25m 5s',224,247),line('Lv.7',95,312)]


class ScreenTests(unittest.TestCase):
    def test_abbreviated_resources_are_intervals(self):
        self.assertEqual(amount('437.1M')['low'],437000000)
        self.assertEqual(amount('147.8K')['high'],147900)
        self.assertEqual(amount('113')['high'],113)
        self.assertEqual(amount('-1.1K')['low'],-1200)

    def test_ambiguous_digits_are_not_repaired(self):
        for value in ['l13','1O0','unknown','','1,2','1 13']:
            with self.assertRaises(UncertainScreen): amount(value)

    def test_duration_combinations(self):
        self.assertEqual(duration('1h 6m 22s'),3982)
        self.assertEqual(duration('5s'),5)
        with self.assertRaises(UncertainScreen): duration('5m 7m')
        for raw in ('25m 55', '50m105', 'Time: 5m', '1h ?m'):
            with self.assertRaises(UncertainScreen): duration(raw)

    def test_real_layout_solar_upgrade(self):
        value = building(solar(),'Solar Plant')
        self.assertEqual((value['level'],value['to_level'],value['seconds']),(4,5,19))
        self.assertEqual(value['cost']['metal']['value'],380)

    def test_low_confidence_cost_rejected(self):
        fixture = solar()
        fixture[5] = line('380',92,387,.6)
        with self.assertRaises(UncertainScreen): building(fixture,'Solar Plant')

    def test_speed_up_is_never_an_upgrade(self):
        fixture = solar()[:-1]+[line('Speed Up',353,828)]
        with self.assertRaises(UncertainScreen): building(fixture,'Solar Plant')

    def test_actual_queue_layout(self):
        fixture = [line('Solar Plant',235,32),line('Level: 3',90,153),line('Upgrading to level 4',140,331),
                   line('Time Left:',90,429),line('8s',230,429),line('Cancel',117,828),line('Speed Up',353,828)]
        value = building(fixture,'Solar Plant')
        self.assertTrue(value['busy'])
        self.assertNotIn('button',value)

    def test_wrong_building_rejected(self):
        with self.assertRaises(UncertainScreen): building(solar(),'Research Lab')

    def test_research_sparse_currencies(self):
        value = tech_card(tech(),'Advanced','Computer Tech')
        self.assertEqual(value['cost']['metal']['value'],0)
        self.assertEqual(value['cost']['crystal']['value'],51200)
        self.assertEqual(value['cost']['gas']['value'],76800)
        self.assertEqual(value['seconds'],1505)

    def test_wrong_research_row_rejected(self):
        with self.assertRaises(UncertainScreen): tech_card(tech(),'Basic','Energy Tech')

    def test_current_home_resource_positions(self):
        fixture = [line('Planets',128,885),line('Fleet',198,885),line('Alliance',414,885),
            line('437.1M',61,77),line('438.5M',132,77),line('473.77M',210,77),line('-931',275,77)]
        value = home(fixture)
        self.assertEqual(value['stock']['metal']['low'],437000000)
        self.assertEqual(value['energy']['value'],-931)

    def test_affordability_uses_worst_case_rounding(self):
        action = building(solar(),'Solar Plant')
        balance = {'stock': {r: amount('50M') for r in ('metal','crystal','gas')}}
        with self.assertRaises(ExecutionBlocked): affordable(action,balance,DEFAULT_PROFILE)

    def test_per_resource_cost_limit(self):
        action = building(solar(),'Solar Plant')
        action['cost']['metal'] = amount('11M')
        balance = {'stock': {r: amount('400M') for r in ('metal','crystal','gas')}}
        with self.assertRaises(ExecutionBlocked): affordable(action,balance,DEFAULT_PROFILE)

class CapturedBuildingControlsTests(unittest.TestCase):
    def test_actual_visible_control_layouts(self):
        import json
        from pathlib import Path
        frames=json.loads((Path(__file__).parent/'fixtures'/'automation_building_controls.json').read_text())
        for name,rows in frames.items():
            result=building([TextLine(row['text'],1,row['x'],row['y']) for row in rows],name)
            self.assertEqual(result['name'],name)
            self.assertEqual(result['to_level'],result['level']+1)
            self.assertEqual(result['button'],[354,828])
            self.assertTrue(all(c['high']>=c['low']>=0 for c in result['cost'].values()))


class CapturedResearchControlsTests(unittest.TestCase):
    def test_all_eight_visible_research_rows(self):
        import json
        from pathlib import Path
        from eog_automation.evo_screen import TECHS
        frames=json.loads((Path(__file__).parent/'fixtures'/'automation_research_controls.json').read_text())
        for tab,rows in frames.items():
            for name in TECHS[tab][:3]:
                result=tech_card([TextLine(row['text'],1,row['x'],row['y']) for row in rows],tab,name)
                self.assertEqual(result['name'],name)
                self.assertGreater(result['seconds'],0)
                self.assertGreaterEqual(result['level'],0)

    def test_scrolled_bottom_rows_are_visible(self):
        import json
        from pathlib import Path
        from eog_automation.evo_screen import TECHS
        frames=json.loads((Path(__file__).parent/'fixtures'/'automation_scrolled_research.json').read_text())
        for tab,rows in frames.items():
            result=tech_card([TextLine(**row) for row in rows],tab,TECHS[tab][3])
            self.assertEqual(result['level'],6)
            self.assertTrue(250<result['button'][1]<700)
