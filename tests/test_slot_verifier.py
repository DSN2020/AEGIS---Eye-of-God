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
    def test_old_retry_holes_only_clear_when_all_selected_positions_have_receipts(self):
        from isolated_supervisor import atomic_json, coverage_for, prune_completed_holes
        with tempfile.TemporaryDirectory() as directory:
            data=Path(directory)
            store=Store(data/'test.sqlite')
            for system in (1,2):
                for position in range(5,21):
                    if system==2 and position==14:
                        continue
                    store.record_slot_check(REVISION,'test',1,system,position,'npc')
            atomic_json(data/'galaxies/1/coverage.json',{'progress':{'1':2},'retry_holes':['1:1','1:2']})
            prune_completed_holes(data,[1],store,{'universe':'test','sweep':{
                'positions':list(range(5,21)), 'verification_mode':REVISION}})
            self.assertEqual(coverage_for(data,1),{'progress':{'1':2},'retry_holes':['1:2']})

    async def test_player_positions_skip_npcs_without_fake_receipts_and_retry_missing_owner(self):
        positions = list(range(5, 21))
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory)/'test.sqlite')
            reader = Mock(config={'universe':'test','sweep':{'positions':positions}})
            reader.dismiss_popup = AsyncMock()
            results = [('npc',None)]*16
            results[9] = UncertainScreen('unreadable owner')
            with patch('ev_assistant.slot_verifier.verify_slot', new=AsyncMock(side_effect=results)) as verify:
                with self.assertRaises(UncertainScreen):
                    await verify_system(reader, Mock(), 9,57,store,Path(directory))
                self.assertEqual([c.args[4] for c in verify.await_args_list], positions)
            self.assertEqual(store.checked_system_count(REVISION,positions),0)
            with patch('ev_assistant.slot_verifier.verify_slot', new=AsyncMock(return_value=('owned','Example'))) as verify:
                self.assertEqual(await verify_system(reader,Mock(),9,57,store,Path(directory)),{(9,57,14)})
                self.assertEqual([c.args[4] for c in verify.await_args_list],[14])
            self.assertEqual(set(store.checked_slots(REVISION,'test',9,57)),set(positions))
            self.assertEqual(store.checked_slot_count(REVISION,positions),16)
            self.assertEqual(store.checked_system_count(REVISION,positions),1)
            self.assertEqual(store.checked_system_count(REVISION),0)

    async def test_prior_full_system_receipts_are_reused_but_excluded_from_scoped_totals(self):
        positions = list(range(5, 21))
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory)/'test.sqlite')
            for position in range(1,22):
                store.record_slot_check(REVISION,'test',1,1,position,'npc')
            reader = Mock(config={'universe':'test','sweep':{'positions':positions}})
            with patch('ev_assistant.slot_verifier.verify_slot',new=AsyncMock()) as verify:
                await verify_system(reader,Mock(),1,1,store,Path(directory))
                verify.assert_not_awaited()
            self.assertEqual(store.checked_slot_count(REVISION),21)
            self.assertEqual(store.checked_slot_count(REVISION,positions),16)
            self.assertEqual(store.checked_system_count(REVISION,positions),1)

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
