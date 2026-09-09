import unittest
from ev_assistant.vision import TextLine, UncertainScreen, read_owner


def line(text, confidence=0.99, x=180, y=280):
    return TextLine(text, confidence, x, y)


class VisionTests(unittest.TestCase):
    def test_verified_owner(self):
        lines = [line('Coordinates: [3:220:15]'), line('Player: Zera', y=301)]
        self.assertEqual(read_owner(lines, (3, 220, 15)), 'Zera')

    def test_wrong_coordinate_never_accepted(self):
        lines = [line('Coordinates: [3:220:16]'), line('Player: Zera', y=301)]
        with self.assertRaises(UncertainScreen):
            read_owner(lines, (3, 220, 15))

    def test_weak_digit_read_never_accepted(self):
        lines = [line('Coordinates: [3:220:15]', 0.72), line('Player: Zera', y=301)]
        with self.assertRaises(UncertainScreen):
            read_owner(lines, (3, 220, 15))

    def test_unreadable_owner_is_not_empty_system(self):
        with self.assertRaises(UncertainScreen):
            read_owner([line('Coordinates: [3:220:15]')], (3, 220, 15))

    def test_background_text_cannot_be_used_as_detail(self):
        with self.assertRaises(UncertainScreen):
            read_owner([line('Coordinates: [3:220:15]', y=30),
                        line('Player: Zera', y=750)], (3, 220, 15))
