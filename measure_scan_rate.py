"""Bounded read-only throughput sample; excludes startup and worker restarts."""
import json
import argparse
import sqlite3
import time
from pathlib import Path

root = Path(__file__).resolve().parent
parser = argparse.ArgumentParser()
parser.add_argument('--workers',type=int,choices=(4,6),default=4)
args = parser.parse_args()
def snapshot():
    status = json.loads((root/'data/sweep-status.json').read_text())
    with sqlite3.connect(f'file:{(root/"data/observations.sqlite").as_posix()}?mode=ro',uri=True) as db:
        count = db.execute("SELECT count(*) FROM slot_checks WHERE revision='explicit-slots-v1'").fetchone()[0]
    return {'time':time.time(),'count':count,'workers':status['workers'],
            'active':status['activeWorkers'],'expected':status['expectedWorkers']}

deadline = time.monotonic()+300
while True:
    start = snapshot()
    if start['active'] == start['expected'] == args.workers:
        break
    if time.monotonic()>deadline:
        raise RuntimeError('Workers did not all become active within five minutes')
    time.sleep(5)
print(json.dumps({'event':'sample_started','verified_slots':start['count']}),flush=True)
samples = [start]
for _ in range(18):
    time.sleep(5)
    samples.append(snapshot())
end = samples[-1]
assert all(s['expected']==args.workers and {k:v['pid'] for k,v in s['workers'].items()} ==
           {k:v['pid'] for k,v in start['workers'].items()} for s in samples), 'Worker configuration changed'
seconds = end['time']-start['time']
report = {'seconds':seconds,'new_verified_slots':end['count']-start['count'],
          'slots_per_minute':(end['count']-start['count'])*60/seconds,
          'accounts':[w['account'] for w in end['workers'].values()],
          'samples':samples}
name = 'four' if args.workers == 4 else 'six'
(root/f'data/efficiency-benchmark/{name}-worker-rate.json').write_text(json.dumps(report,indent=2))
print(json.dumps({k:v for k,v in report.items() if k!='samples'}),flush=True)
