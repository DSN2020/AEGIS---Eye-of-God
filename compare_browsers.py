"""Compare a five-minute mixed-browser sample with the saved Chrome baseline."""
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

data = Path(__file__).resolve().parent / 'data'
lines = (data / 'sweep.background.log').read_text(
    encoding='utf-8', errors='replace').split('SUPERVISOR starting generation')[-1]
events = []
for line in lines.splitlines():
    match = re.match(
        r'(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d+) .*?Worker (\d+) '
        r'(scanning|completed|retrying|queued)\b', line)
    if match:
        events.append((datetime.strptime(match[1], '%Y-%m-%d %H:%M:%S,%f'),
                       int(match[2]), match[3]))
starts = [t for t, w, event in events if event == 'scanning']
if len(starts) < 6:
    print(json.dumps({'state': 'waiting_for_six_workers', 'started': len(starts)}))
else:
    start = max(starts[:6])
    end = start + timedelta(minutes=5)
    now = datetime.now()
    selected = [event for event in events if start <= event[0] < end]
    elapsed = min(300, max(1, (now - start).total_seconds()))
    result = {
        'mode': '4 Chrome + 2 Edge',
        'state': 'complete' if now >= end else 'measuring',
        'start': str(start), 'end': str(end),
        'elapsed_seconds': round(elapsed, 1),
        'completed': sum(event[2] == 'completed' for event in selected),
        'retry_events': sum(event[2] == 'retrying' for event in selected),
        'completed_by_worker': {
            str(worker): sum(event[1] == worker and event[2] == 'completed'
                             for event in selected) for worker in range(1, 7)},
    }
    result['systems_per_minute'] = round(result['completed'] * 60 / elapsed, 2)
    baseline = json.loads((data / 'benchmark-four-chrome.json').read_text())
    result['baseline_systems_per_minute'] = baseline['systems_per_minute']
    result['change_percent'] = round(
        100 * (result['systems_per_minute'] / baseline['systems_per_minute'] - 1), 1)
    (data / 'benchmark-mixed-browsers.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
