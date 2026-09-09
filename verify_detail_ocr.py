"""Replay saved confirmed UI captures without changing game or scan data."""
import io
import json
import time
from pathlib import Path
from PIL import Image
from ev_assistant.vision import OCR, TextLine
from ev_assistant.slot_verifier import parse_slot, parse_alliance

root = Path(__file__).resolve().parent
ocr = OCR()
rows = []
baseline = json.loads((root/'data/efficiency-benchmark/baseline/result.json').read_text())
for original in baseline['observations']:
    position = original['position']
    buffer = io.BytesIO()
    Image.open(root/f'data/slot-audit/9-57-{position}.png').crop((25,230,445,680)).save(buffer,format='PNG')
    start = time.perf_counter()
    lines = [TextLine(x.text,x.confidence,x.x+25,x.y+230) for x in ocr.read_detail(buffer.getvalue())]
    result = parse_slot(lines,(9,57,position),allow_nebula=position==21)
    row = {'position':position,'seconds':time.perf_counter()-start,'result':result,
           'matches':list(result or []) == original['result'][:2], 'alliance':parse_alliance(lines)}
    rows.append(row)
    print(json.dumps(row),flush=True)
(root/'data/efficiency-benchmark/detail-replay.json').write_text(json.dumps(rows,indent=2))
assert all(x['matches'] for x in rows), 'Detail OCR differs from confirmed baseline'
