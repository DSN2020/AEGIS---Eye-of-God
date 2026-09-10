"""Explicit checks of required positions; excluded slots get no fake receipts."""
import asyncio
import logging
import re
import time
from .store import Planet
from .coverage import sweep_positions
from .rendered_text import read_rendered_text
from .vision import UncertainScreen, compact, join_rows

REVISION = 'explicit-slots-v1'
LOG = logging.getLogger('eternal-void')

def parse_alliance(lines):
    rows = join_rows([x for x in lines if 230 <= x.y <= 360 and 25 <= x.x <= 445
                      and x.confidence >= .82])
    match = re.search(r'(?:^|\n)Alliance[ \t]*[:\uff1a]([^\n]*)', rows, re.I)
    return match[1].strip() if match else None

def parse_slot(lines, expected, allow_nebula=False):
    panel = [x for x in lines if 230 <= x.y <= 680 and 25 <= x.x <= 445
             and x.confidence >= .82]
    text = join_rows(panel)
    normalized = compact(text)
    # Slot 21's observed exploration panel has no detail coordinate label.
    # Its caller must additionally verify all three coordinate editor values.
    if (allow_nebula and expected[2] == 21 and 'player' not in normalized
            and all(x in normalized for x in ('mysteriousnebula', 'safeexplorations',
                                               'navigationrelays', 'explore'))):
        return ('npc', None)
    matches = list(re.finditer(r'Coordinates\s*[:\uff1a]\s*(?:\[\s*)*(\d+)\s*[:\uff1a]\s*(\d+)\s*[:\uff1a]\s*(\d+)\s*\]?', text, re.I))
    if len(matches) != 1 or tuple(map(int, matches[0].groups())) != tuple(expected):
        return None
    owners = list(re.finditer(r'(?:^|\n)Player[ \t]*[:\uff1a][ \t]*([^\n]+)', text, re.I))
    if len(owners) > 1:
        return None
    owner = owners[0] if owners else None
    if owner:
        name = re.sub(r'\s*\[you\]\s*$', '', owner[1], flags=re.I).strip()
        if name:
            return ('owned', name)
    # Never classify a partly unreadable Player field as empty or NPC.
    if 'player' in compact(text):
        return None
    normalized = compact(text)
    if 'colonize' in normalized:
        return ('empty', None)
    if any(x in normalized for x in ('hostilepirates', 'desolateplanet',
                                     'mysteriousnebula', 'safeexplorations')):
        return ('npc', None)
    return None

async def verify_slot(reader, page, galaxy, system, position, data):
    expected = (galaxy, system, position)
    efficient = reader.config.get('sweep',{}).get('efficient_slots',True)
    await reader.set_coordinate(page, 381, position)
    await page.mouse.click(296, 85)
    # The live benchmark showed .15s repeatedly captured the previous detail,
    # adding an expensive third OCR pass. Allow the observed UI transition.
    await asyncio.sleep(1)
    previous = None
    previous_alliance = None
    previous_source = None
    previous_frame = None
    deadline = time.monotonic()+15
    for attempt in range(20 if efficient else 8):
        if time.monotonic()>deadline:
            break
        clip = {'x':25, 'y':230, 'width':420, 'height':450}
        source, frame = 'ocr', None
        rendered = None
        if efficient and reader.config.get('sweep', {}).get('rendered_text', False):
            rendered = await read_rendered_text(page, clip)
        if rendered and parse_slot(rendered[1], expected, allow_nebula=(position == 21)):
            frame, lines = rendered
            source = 'rendered'
            timings = getattr(reader, 'timings', None)
            if isinstance(timings, dict):
                timings['rendered_text_reads'] = timings.get('rendered_text_reads', 0) + 1
        else:
            # Unsupported, incomplete or stale scene text keeps the OCR path.
            if efficient and reader.config.get('sweep', {}).get('detail_ocr', True):
                lines, _ = await reader.observe(page, clip, detail=(attempt == 0 or previous is not None))
            else:
                lines, _ = await reader.observe(page, clip)
        if time.monotonic() - getattr(reader, '_last_live_frame', 0) >= 5:
            try:
                temporary = data / 'live-frame.tmp'
                temporary.write_bytes(await page.screenshot())
                temporary.replace(data / 'live-frame.png')
                reader._last_live_frame = time.monotonic()
            except OSError:
                pass
        result = parse_slot(lines, expected, allow_nebula=(position == 21))
        alliance = parse_alliance(lines) if result and result[0] == 'owned' else None
        if (result and result == previous and source == previous_source
                and (source == 'ocr' or frame != previous_frame)):
            if position == 21:
                actual = tuple([await reader.read_coordinate(page, x) for x in (89,235,381)])
                if actual != expected:
                    raise UncertainScreen(f'Nebula coordinate editors mismatch: {actual} != {expected}')
            if not efficient or position == 21:
                await reader.dismiss_popup(page)
            return (*result, alliance if alliance == previous_alliance else None)
        previous = result
        previous_alliance = alliance
        previous_source, previous_frame = source, frame
        await asyncio.sleep(.05 if efficient else .35)
    path = data / f'unverified-slot-{galaxy}-{system}-{position}.png'
    path.write_bytes(await page.screenshot())
    raise UncertainScreen(f'Cannot verify exact slot {galaxy}:{system}:{position}; {path}')

async def verify_system(reader, page, galaxy, system, store, data):
    universe = reader.config['universe']
    positions = sweep_positions(reader.config)
    checked = store.checked_slots(REVISION, universe, galaxy, system)
    started = time.perf_counter()
    pending_count = len(set(positions) - set(checked))
    timings = getattr(reader, 'timings', {})
    timings = timings if isinstance(timings, dict) else {}
    before = dict(timings)
    errors = []
    for position in positions:
        if position in checked:
            continue
        reader.check_stop()
        try:
            result = await verify_slot(reader, page, galaxy, system, position, data)
            kind, owner = result[:2]
            alliance = result[2] if len(result) > 2 else None
        except UncertainScreen as exc:
            errors.append(position)
            LOG.warning('Worker 1 unresolved slot %s:%s:%s: %s', galaxy, system, position, exc)
            await reader.dismiss_popup(page)
            continue
        if kind == 'owned' and not re.match(r'^bot_', owner, re.I):
            store.record_sighting(universe, galaxy, system, Planet(position, owner, ''))
            store.record_alliance(universe, owner, alliance)
        store.record_slot_check(REVISION, universe, galaxy, system, position, kind, owner)
        LOG.info('Worker 1 verified slot %s:%s:%s (%s)', galaxy, system, position, kind)
    checked = store.checked_slots(REVISION, universe, galaxy, system)
    if not set(positions).issubset(checked):
        raise UncertainScreen(f'Incomplete {len(positions)}-slot verification at {galaxy}:{system}; unresolved {errors}')
    if pending_count:
        LOG.info('Read performance %s:%s: %s new slots in %.1fs; %s OCR calls, %s identical-frame reuses, %s rendered-text reads',
                 galaxy, system, pending_count, time.perf_counter()-started,
                 int(timings.get('ocr_calls',0)-before.get('ocr_calls',0)),
                 int(timings.get('ocr_cache_hits',0)-before.get('ocr_cache_hits',0)),
                 int(timings.get('rendered_text_reads',0)-before.get('rendered_text_reads',0)))
    return {(galaxy, system, p) for p, row in checked.items()
            if p in positions and row['kind'] == 'owned'}
