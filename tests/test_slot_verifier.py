import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch
from ev_assistant.slot_verifier import parse_slot, verify_system, REVISION
from ev_assistant.store import Store
from ev_assistant.vision import TextLine, UncertainScreen

def line(text, y=300, confidence=.99):
    return TextLine(text, confidence, 230, y)

class ParseTests(unittest.TestCase):
    def test_nebula_requires_explicit_special_case_and_slot_21(self):
        lines = [line('Mysterious Nebula',360),line('Safe Explorations:28/120',398),
                 line('Navigation Relays:2007',446),line('Explore',547)]
        self.assertIsNone(parse_slot(lines,(9,57,21)))
        self.assertIsNone(parse_slot(lines,(9,57,14),allow_nebula=True))
        self.assertEqual(parse_slot(lines,(9,57,21),allow_nebula=True),('npc',None))

    def test_known_missing_owner(self):
        self.assertEqual(parse_slot([line('Coordinates: [9:57:14]', 277),
            line('Player: XXxxNAZIMxxXX')], (9,57,14)), ('owned','XXxxNAZIMxxXX'))

    def test_header_or_different_planet_cannot_count(self):
        self.assertIsNone(parse_slot([line('9:57:14', 30), line('Desolate Planet',360)], (9,57,14)))
        self.assertIsNone(parse_slot([line('Coordinates: [9:57:13]',398),
            line('Desolate Planet',360)], (9,57,14)))

    def test_owner_takes_priority_over_npc_words(self):
        self.assertEqual(parse_slot([line('Coordinates: [9:57:14]',277),
            line('Player: Desolate Planet'), line('Colonize',530)], (9,57,14)),
            ('owned','Desolate Planet'))

    def test_unreadable_owner_never_counts_as_empty(self):
        self.assertIsNone(parse_slot([line('Coordinates: [9:57:14]',277),
            line('Player:'), line('Colonize',530)], (9,57,14)))

    def test_npc_requires_matching_detail_coordinates(self):
        self.assertEqual(parse_slot([line('Coordinates: [9:57:1]',398),
            line('Hostile Pirates',360)], (9,57,1)), ('npc',None))

class CoverageTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_21_slots_required_and_failed_slot_alone_retried(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory)/'test.sqlite')
            reader = Mock(config={'universe':'test'})
            reader.dismiss_popup = AsyncMock()
            results = [('npc',None)]*21
            results[13] = UncertainScreen('unreadable')
            with patch('ev_assistant.slot_verifier.verify_slot', new=AsyncMock(side_effect=results)) as verify:
                with self.assertRaises(UncertainScreen):
                    await verify_system(reader, Mock(), 9,57,store,Path(directory))
                self.assertEqual([c.args[4] for c in verify.await_args_list], list(range(1,22)))
            self.assertEqual(store.checked_slot_count(REVISION),20)
            self.assertEqual(store.checked_system_count(REVISION),0)
            with patch('ev_assistant.slot_verifier.verify_slot', new=AsyncMock(return_value=('owned','Nazim'))) as verify:
                seen = await verify_system(reader, Mock(),9,57,store,Path(directory))
                self.assertEqual(verify.await_count,1)
                self.assertEqual(verify.await_args.args[4],14)
                self.assertEqual(seen,{(9,57,14)})
            self.assertEqual(store.checked_slot_count(REVISION),21)
            self.assertEqual(store.checked_system_count(REVISION),1)
            self.assertEqual(store.search()[0]['player'],'Nazim')

    async def test_legacy_sightings_are_not_verification_receipts(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory)/'test.sqlite')
            self.assertEqual(store.checked_slots(REVISION,'test',9,57),{})
