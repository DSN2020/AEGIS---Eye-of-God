"""Bounded 4->5->4 live smoke test, preserving all existing worker processes."""
import json
import time
from app_bridge import ApplicationBridge

bridge=ApplicationBridge()
def wait_for(count):
    deadline=time.monotonic()+100
    while time.monotonic()<deadline:
        if bridge.settings()['workerCount']!=count:
            raise RuntimeError('Count changed externally; leaving the selected count alone')
        status=bridge.read(bridge.data/'sweep-status.json',{})
        workers=status.get('workers',{})
        if status.get('liveWorkerResize') and len(workers)==count and all(w.get('pid') for w in workers.values()):
            return status
        time.sleep(2)
    raise RuntimeError(f'Controller did not report {count} worker processes')

before=wait_for(4)
original={k:w['pid'] for k,w in before['workers'].items()}
print('Testing live addition of one standby agent.',flush=True)
bridge.dispatch({'command':'set_worker_count','workerCount':5})
try:
    expanded=wait_for(5)
    assert all(expanded['workers'][k]['pid']==pid for k,pid in original.items())
finally:
    if bridge.settings()['workerCount']==5:
        bridge.dispatch({'command':'set_worker_count','workerCount':4})
restored=wait_for(4)
assert {k:w['pid'] for k,w in restored['workers'].items()}==original
assert before['supervisorPid']==expanded['supervisorPid']==restored['supervisorPid']
result={'passed':True,'counts':[4,5,4],'originalWorkerPidsPreserved':True,
        'supervisorPidPreserved':True,'workerPids':original,'finished':time.time()}
(bridge.data/'live-resize-verification.json').write_text(json.dumps(result,indent=2))
print(json.dumps(result),flush=True)
