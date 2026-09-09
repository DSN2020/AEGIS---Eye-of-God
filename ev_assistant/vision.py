"""Conservative OCR parsing for the observed Eternal Void canvas interface."""
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class TextLine:
    text: str
    confidence: float
    x: float
    y: float


class UncertainScreen(RuntimeError):
    pass


def compact(text):
    return re.sub(r'\s+', '', text).casefold().replace('\uff1a', ':')


def popup_kind(lines):
    text = compact(' '.join(line.text for line in lines
                           if 230 <= line.y <= 680 and line.confidence >= .80))
    if any(name in text for name in ('hostilepirates', 'desolateplanet',
                                     'mysteriousnebula', 'safeexplorations')):
        return 'npc'
    if any(label in text for label in ('coordinates:', 'player:', 'colonize')):
        return 'detail'
    return None


def map_header_readable(lines):
    text = compact(' '.join(line.text for line in lines
                           if line.y < 105 and line.confidence >= .82))
    return all(word in text for word in ('galaxy', 'solarsystem', 'planet', 'bookmark'))


def join_rows(lines):
    """Join adjacent OCR boxes on the same visual line (split coordinate labels)."""
    rows = []
    for line in sorted(lines, key=lambda item: (item.y, item.x)):
        row = next((row for row in rows if abs(row[0].y - line.y) <= 7), None)
        if row is None:
            rows.append([line])
        else:
            row.append(line)
    return '\n'.join(' '.join(item.text.strip() for item in sorted(row, key=lambda x: x.x))
                     for row in rows)


def read_owner(lines, expected, threshold=0.90):
    """Require a coordinate explicitly labeled in the detail popup, plus owner.

    Header coordinate fields alone are insufficient: they change before the
    server has loaded the requested planet. Never autocorrect OCR digits.
    """
    # Observed popup occupies y=260..650 at our fixed 470x912 viewport.
    popup = [line for line in lines if 260 <= line.y <= 650 and 60 <= line.x <= 410]
    good = [line.text.strip() for line in popup if line.confidence >= threshold]
    joined = '\n'.join(good)
    match = re.search(r'Coordinates\s*[:\uff1a]\s*\[?\s*(\d+)\s*[:\uff1a]\s*(\d+)\s*[:\uff1a]\s*(\d+)\s*\]?', joined, re.I)
    if not match or tuple(map(int, match.groups())) != tuple(expected):
        raise UncertainScreen('Detail coordinates missing, uncertain, or do not match request')
    owner = re.search(r'(?:^|\n)Player\s*[:\uff1a]\s*([^\n]+)', joined, re.I)
    if not owner or not owner.group(1).strip():
        raise UncertainScreen('Owner not confidently readable; do not assume empty')
    if owner.group(1).strip().lower() in ('-', 'none', 'unknown', 'unoccupied', 'empty'):
        raise UncertainScreen('Unowned-slot presentation has not been calibrated')
    return owner.group(1).strip()


class OCR:
    def __init__(self):
        import cv2
        from rapidocr_onnxruntime import RapidOCR
        # Each browser worker owns an OCR process. OpenCV's default pool uses
        # every logical CPU per process and competes with all other workers.
        cv2.setNumThreads(1)
        self.engine = RapidOCR(intra_op_num_threads=1, inter_op_num_threads=1)

    def read(self, image_bytes):
        # The legacy ONNX distribution bundles its models and returns box,text,score.
        # This fixed-orientation game UI is always upright. The angle classifier
        # can wrongly flip short numeric coordinates by 180 degrees.
        result, _ = self.engine(image_bytes, use_cls=False)
        return [TextLine(text, float(score), float(sum(p[0] for p in box) / 4),
                         float(sum(p[1] for p in box) / 4))
                for box, text, score in (result or [])]

    def read_detail(self, image_bytes):
        """Recognize relevant rows in the calibrated 420x450 detail capture.

        Detect text afresh at the normal resolution on every screenshot. Only
        recognition of action labels and item levels is omitted. The caller
        falls back to a full read if these rows cannot verify an exact slot.
        """
        import numpy as np
        boxes, _ = self.engine(image_bytes, use_cls=False, use_rec=False)
        if boxes is None or len(boxes) == 0:
            return []
        boxes = [np.asarray(box, dtype=np.float32) for box in boxes]
        upper = [box for box in boxes if 25 <= box[:, 1].mean() <= 110]
        selected = upper if upper else [box for box in boxes
            if 115 <= box[:, 1].mean() <= 230 or 290 <= box[:, 1].mean() <= 330]
        if not selected:
            return []
        image = self.engine.load_img(image_bytes)
        crops = self.engine.get_crop_img_list(image, selected)
        results, _ = self.engine.text_rec(crops)
        return [TextLine(text, float(score), float(box[:, 0].mean()),
                         float(box[:, 1].mean()))
                for box, (text, score) in zip(selected, results)]
