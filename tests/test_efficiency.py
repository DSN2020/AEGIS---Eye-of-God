import tempfile
import asyncio
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from ev_assistant.slot_verifier import verify_slot
from ev_assistant.vision import TextLine, OCR, UncertainScreen
from ev_assistant.__main__ import Reader


def owned(position=14, owner='XXxxNAZIMxxXX'):
    return ([TextLine(f'Coordinates: [9:57:{position}]', .99, 160, 277),
             TextLine(f'Player: {owner}', .99, 180, 300),
             TextLine('Alliance: ABC', .99, 150, 324)], b'frame')


class EfficientSlotTests(unittest.IsolatedAsyncioTestCase):
    def reader(self, observations):
        reader = Mock(config={'sweep': {'efficient_slots': True}})
        reader._last_live_frame = time.monotonic()
        reader.set_coordinate = AsyncMock()
        reader.read_coordinate = AsyncMock()
        reader.dismiss_popup = AsyncMock()
        reader.observe = AsyncMock(side_effect=observations)
        return reader

    async def test_requires_two_matching_owner_reads_without_extra_close_ocr(self):
        reader = self.reader([owned(), owned()])
        page = Mock(); page.mouse.click = AsyncMock()
        with patch('ev_assistant.slot_verifier.asyncio.sleep', new=AsyncMock()):
            result = await verify_slot(reader, page, 9, 57, 14, Path('.'))
        self.assertEqual(result, ('owned', 'XXxxNAZIMxxXX', 'ABC'))
        self.assertEqual(reader.observe.await_count, 2)
        reader.dismiss_popup.assert_not_awaited()

    async def test_wrong_coordinate_and_changing_owner_cannot_confirm(self):
        reader = self.reader([owned(13), owned(), owned(owner='Other'), owned(), owned()])
        page = Mock(); page.mouse.click = AsyncMock()
        with patch('ev_assistant.slot_verifier.asyncio.sleep', new=AsyncMock()):
            result = await verify_slot(reader, page, 9, 57, 14, Path('.'))
        self.assertEqual(result[1], 'XXxxNAZIMxxXX')
        self.assertEqual(reader.observe.await_count, 5)

    async def test_uncertain_selected_rows_fall_back_to_full_ocr(self):
        reader = self.reader([([],b''), owned(), owned()])
        page = Mock(); page.mouse.click = AsyncMock()
        with patch('ev_assistant.slot_verifier.asyncio.sleep', new=AsyncMock()):
            await verify_slot(reader,page,9,57,14,Path('.'))
        self.assertEqual([c.kwargs['detail'] for c in reader.observe.await_args_list],
                         [True,False,True])

    async def test_stale_detail_never_becomes_a_receipt(self):
        reader = self.reader([owned(13)] * 20)
        page = Mock(); page.mouse.click = AsyncMock()
        page.screenshot = AsyncMock(return_value=b'diagnostic')
        with tempfile.TemporaryDirectory() as directory:
            with patch('ev_assistant.slot_verifier.asyncio.sleep', new=AsyncMock()):
                with self.assertRaises(UncertainScreen):
                    await verify_slot(reader, page, 9, 57, 14, Path(directory))

    async def test_nebula_still_verifies_all_header_fields(self):
        lines = [TextLine(text,.99,200,y) for text,y in [
            ('Mysterious Nebula',360),('Safe Explorations: 28',398),
            ('Navigation Relays: 2007',446),('Explore',547)]]
        reader = self.reader([(lines,b'')] * 2)
        reader.read_coordinate.side_effect = [9,57,20]
        page = Mock(); page.mouse.click = AsyncMock()
        with patch('ev_assistant.slot_verifier.asyncio.sleep', new=AsyncMock()):
            with self.assertRaisesRegex(UncertainScreen, 'editors mismatch'):
                await verify_slot(reader,page,9,57,21,Path('.'))

    def test_opencv_pool_is_bounded_per_worker(self):
        with patch('cv2.setNumThreads') as pool, patch('rapidocr_onnxruntime.RapidOCR'):
            OCR()
        pool.assert_called_once_with(1)

    async def test_identical_new_capture_reuses_ocr_but_changed_capture_is_read(self):
        reader = Reader.__new__(Reader)
        reader.check_stop = Mock()
        reader.ocr_lock = asyncio.Lock()
        reader.ocr_cache = {}
        reader.ocr = Mock()
        reader.ocr.read.return_value = [TextLine('Player: A', .99, 100, 70)]
        page = Mock(url='https://eternal-void.online/')
        page.screenshot = AsyncMock(side_effect=[b'first',b'first',b'changed'])
        for _ in range(3):
            await reader.observe(page)
        self.assertEqual(page.screenshot.await_count,3)
        self.assertEqual(reader.ocr.read.call_count,2)
        self.assertEqual([c.args[0] for c in reader.ocr.read.call_args_list],[b'first',b'changed'])
