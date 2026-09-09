"""Archive invalid legacy coverage after stopping the supervisor; preserve findings."""
import json
import shutil
import socket
import sqlite3
from datetime import datetime
from ev_assistant.__main__ import ROOT
from ev_assistant.store import Store
from ev_assistant.slot_verifier import REVISION
from isolated_supervisor import atomic_json

data = ROOT / 'data'
store = Store(data / 'observations.sqlite')
checks = store.checked_slots(REVISION, 'eternal-void', 9, 57)
assert set(checks) == set(range(1,22)), 'Live 21-slot calibration has not passed'
assert checks[14]['owner'] == 'XXxxNAZIMxxXX', 'Missing-player regression did not pass'
assert (data / 'STOP').exists(), 'Stop the legacy supervisor before migration'
guard = socket.socket()
guard.bind(('127.0.0.1',47682))
archive = data / ('legacy-coverage-' + datetime.now().strftime('%Y%m%d-%H%M%S'))
archive.mkdir()
shutil.copy2(ROOT / 'config.json', archive / 'config.json')
for name in ('sweep-status.json','sweep-progress.json','sweep-retries.json','players.txt','players.csv'):
    if (data / name).exists():
        shutil.copy2(data / name, archive / name)
with sqlite3.connect(data / 'observations.sqlite') as source:
    with sqlite3.connect(archive / 'observations.sqlite') as target:
        source.backup(target)
for galaxy in range(1,10):
    job = data / 'galaxies' / str(galaxy)
    saved = archive / 'galaxies' / str(galaxy)
    saved.mkdir(parents=True)
    for name in ('coverage.json','sweep-progress.json','sweep-retries.json'):
        if (job / name).exists():
            shutil.copy2(job / name, saved / name)
    assert atomic_json(job / 'coverage.json', {'progress': {str(galaxy):0}, 'retry_holes':[]})
    assert atomic_json(job / 'sweep-progress.json', {str(galaxy):0})
    assert atomic_json(job / 'sweep-retries.json', {'systems':[]})
config = json.loads((ROOT / 'config.json').read_text(encoding='utf-8-sig'))
config['sweep']['verification_mode'] = REVISION
assert atomic_json(ROOT / 'config.json', config)
assert atomic_json(data / 'sweep-progress.json', {str(g):0 for g in range(1,10)})
assert atomic_json(data / 'sweep-retries.json', {'systems':[]})
assert atomic_json(data / 'coverage-correction.json', {
    'reason':'Three-view sweep skipped planets; previous coverage was not complete.',
    'example':{'coordinate':'9:57:14','owner':'XXxxNAZIMxxXX'},
    'archive':str(archive), 'verificationMode':REVISION,
    'note':'Player observations preserved. All systems require 21-slot verification.'})
assert atomic_json(data / 'sweep-status.json', {
    'state':'restarting', 'verificationMode':REVISION, 'completedSystems':0,
    'totalSystems':4491, 'verifiedPlanetSlots':store.checked_slot_count(REVISION),
    'totalPlanetSlots':94311, 'activeWorkers':0, 'expectedWorkers':4})
guard.close()
print(str(archive))
