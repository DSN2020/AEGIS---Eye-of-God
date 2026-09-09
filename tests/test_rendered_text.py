import asyncio
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch
from ev_assistant.rendered_text import read_rendered_text
from ev_assistant.slot_verifier import parse_slot, verify_slot
from ev_assistant.vision import TextLine, UncertainScreen

CLIP = {'x':25, 'y':230, 'width':420, 'height':450}

def owner(position=14, name='Example', alliance='ABC'):
    return [TextLine(f'Coordinates: [9:57:{position}]',1,150,277),
            TextLine(f'Player: {name}',1,150,300),
            TextLine(f'Alliance: {alliance}',1,150,324)]

class RenderedTextTests(unittest.IsolatedAsyncioTestCase):
    async def test_outline_duplicates_do_not_duplicate_alliance(self):
        page=Mock(evaluate=AsyncMock(return_value={'frame':7, 'rows':[
            {'text':'Alliance:', 'x':110, 'y':324},
            {'text':'ABC', 'x':157, 'y':324},
            {'text':'ABC', 'x':158, 'y':325}]}))
        frame, lines=await read_rendered_text(page, CLIP)
        self.assertEqual(frame,7)
        self.assertEqual([x.text for x in lines],['Alliance:','ABC'])

    async def test_unsupported_or_malformed_scene_falls_back(self):
        for value in [None,{}, {'frame':0,'rows':[]}, {'frame':2,'rows':[]},
                      {'frame':2,'rows':[{'text':'two\nrows','x':50,'y':280}]},
                      {'frame':2,'rows':[{'text':'label','x':float('nan'),'y':280}]}]:
            self.assertIsNone(await read_rendered_text(Mock(evaluate=AsyncMock(return_value=value)),CLIP))
        self.assertIsNone(await read_rendered_text(Mock(evaluate=AsyncMock(side_effect=RuntimeError('game changed'))),CLIP))

    def make_reader(self):
        r=Mock(config={'sweep':{'efficient_slots':True,'rendered_text':True}})
        r._last_live_frame=time.monotonic();r.timings={}
        r.set_coordinate=AsyncMock();r.read_coordinate=AsyncMock();r.dismiss_popup=AsyncMock()
        r.observe=AsyncMock(return_value=(owner(),b'frame'))
        return r

    async def test_same_render_frame_cannot_confirm_twice(self):
        r=self.make_reader();p=Mock();p.mouse.click=AsyncMock()
        with patch('ev_assistant.slot_verifier.read_rendered_text',new=AsyncMock(side_effect=[(10,owner()),(10,owner()),(11,owner())])) as read, patch('ev_assistant.slot_verifier.asyncio.sleep',new=AsyncMock()):
            self.assertEqual(await verify_slot(r,p,9,57,14,Path('.')),('owned','Example','ABC'))
        self.assertEqual(read.await_count,3);r.observe.assert_not_awaited()
        self.assertEqual(r.timings['rendered_text_reads'],3)

    async def test_stale_rendered_text_falls_back_to_two_ocr_reads(self):
        r=self.make_reader();p=Mock();p.mouse.click=AsyncMock()
        with patch('ev_assistant.slot_verifier.read_rendered_text',new=AsyncMock(return_value=(10,owner(13)))), patch('ev_assistant.slot_verifier.asyncio.sleep',new=AsyncMock()):
            self.assertEqual(await verify_slot(r,p,9,57,14,Path('.')),('owned','Example','ABC'))
        self.assertEqual(r.observe.await_count,2)

    async def test_mixed_sources_need_a_second_confirmation(self):
        r=self.make_reader();p=Mock();p.mouse.click=AsyncMock()
        with patch('ev_assistant.slot_verifier.read_rendered_text',new=AsyncMock(side_effect=[(10,owner()),None,None])), patch('ev_assistant.slot_verifier.asyncio.sleep',new=AsyncMock()):
            await verify_slot(r,p,9,57,14,Path('.'))
        self.assertEqual(r.observe.await_count,2)

    async def test_changed_owner_requires_two_new_matching_frames(self):
        r=self.make_reader();p=Mock();p.mouse.click=AsyncMock()
        with patch('ev_assistant.slot_verifier.read_rendered_text',new=AsyncMock(side_effect=[(10,owner()),(11,owner(name='Other')),(12,owner(name='Other'))])), patch('ev_assistant.slot_verifier.asyncio.sleep',new=AsyncMock()):
            self.assertEqual((await verify_slot(r,p,9,57,14,Path('.')))[1],'Other')
        r.observe.assert_not_awaited()

    async def test_frozen_scene_never_creates_receipt(self):
        r=self.make_reader();p=Mock();p.mouse.click=AsyncMock();p.screenshot=AsyncMock(return_value=b'diagnostic')
        with tempfile.TemporaryDirectory() as folder, patch('ev_assistant.slot_verifier.read_rendered_text',new=AsyncMock(return_value=(10,owner()))), patch('ev_assistant.slot_verifier.asyncio.sleep',new=AsyncMock()):
            with self.assertRaises(UncertainScreen): await verify_slot(r,p,9,57,14,Path(folder))

    def test_ambiguous_detail_labels_are_rejected(self):
        self.assertIsNone(parse_slot(owner()+[TextLine('Coordinates: [9:57:13]',1,150,350)],(9,57,14)))
        self.assertIsNone(parse_slot(owner()+[TextLine('Player: Other',1,150,350)],(9,57,14)))

    def test_own_planet_suffix_preserves_exact_owner(self):
        self.assertEqual(parse_slot(owner(name='Example [you]'),(9,57,14)),('owned','Example'))

    async def test_rendered_nebula_still_requires_exact_header(self):
        r=self.make_reader();r.read_coordinate.side_effect=[9,57,20]
        p=Mock();p.mouse.click=AsyncMock()
        lines=[TextLine(text,1,200,y) for text,y in [('Mysterious Nebula',360),('Safe Explorations: 28',398),('Navigation Relays: 2007',446),('Explore',547)]]
        with patch('ev_assistant.slot_verifier.read_rendered_text',new=AsyncMock(side_effect=[(10,lines),(11,lines)])), patch('ev_assistant.slot_verifier.asyncio.sleep',new=AsyncMock()):
            with self.assertRaisesRegex(UncertainScreen,'editors mismatch'):
                await verify_slot(r,p,9,57,21,Path('.'))
        r.observe.assert_not_awaited()
