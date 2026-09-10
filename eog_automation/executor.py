"""Verified action transaction; a crash after intent never causes a blind retry."""
import json
import sqlite3
import time
from .planner import validate


class ExecutionBlocked(RuntimeError):
    pass


class Journal:
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.execute('CREATE TABLE IF NOT EXISTS actions (id TEXT PRIMARY KEY, account TEXT, universe TEXT, action TEXT, status TEXT, created REAL)')
        self.db.commit()

    def unresolved(self, account, universe):
        return self.db.execute("SELECT id FROM actions WHERE account=? AND universe=? AND status IN ('intent','uncertain')", (account.casefold(), universe)).fetchone()

    def begin(self, state, action):
        import uuid
        key = uuid.uuid4().hex
        # Persistent account lease prevents two processes issuing simultaneous actions.
        self.db.execute('BEGIN IMMEDIATE')
        try:
            if self.unresolved(state['account'], state['universe']):
                raise ExecutionBlocked('An earlier action needs reconciliation in the game')
            self.db.execute('INSERT INTO actions VALUES (?,?,?,?,?,?)', (key, state['account'].casefold(), state['universe'], json.dumps(action), 'intent', time.time()))
            self.db.commit()
            return key
        except BaseException:
            self.db.rollback()
            raise

    def finish(self, key, status):
        self.db.execute('UPDATE actions SET status=? WHERE id=?', (status, key))
        self.db.commit()

    def count_recent(self, account, universe, kind, seconds=86400):
        rows=self.db.execute("SELECT action FROM actions WHERE account=? AND universe=? AND created>=? AND status IN ('intent','uncertain','confirmed')",(account.casefold(),universe,time.time()-seconds))
        return sum(json.loads(row[0]).get('kind')==kind for row in rows)

    def close(self):
        self.db.close()


async def execute_one(adapter, journal, state, action, preferences, stopped=lambda: False):
    validate(state)
    if stopped():
        raise ExecutionBlocked('Paused')
    if not adapter.calibrated or state.get('source') != 'live':
        raise ExecutionBlocked('Only calibrated live observations can execute')
    if not any(candidate == action for candidate in state['actions']):
        raise ExecutionBlocked('Action does not match the observed upgrade catalog')
    if time.time() - state['observed_at'] > 30 or state['observed_at'] > time.time() + 2:
        raise ExecutionBlocked('Observation is stale or its timestamp is invalid')
    if action.get('premium_cost', 0):
        raise ExecutionBlocked('Premium currency spending is not enabled')
    if state['levels'].get(action['level_key'], 0) != action['from_level']:
        raise ExecutionBlocked('Upgrade level changed')
    planet = state['planets'][action['planet']]
    for r, amount in action['cost'].items():
        if amount + preferences.get('reserves', {}).get(r, 0) > planet['stock'][r]:
            raise ExecutionBlocked('Insufficient resources after reserves')
    # Adapter reopens the exact upgrade and verifies identity, level, cost,
    # queue availability and prerequisites immediately before a single click.
    if not await adapter.prepare_and_verify(state, action):
        raise ExecutionBlocked('Upgrade screen did not match the planned action')
    if stopped():
        raise ExecutionBlocked('Paused')
    key = journal.begin(state, action)
    try:
        if stopped():
            journal.finish(key, 'cancelled')
            raise ExecutionBlocked('Paused')
        await adapter.commit(action)
        if not await adapter.confirm(state, action):
            raise ExecutionBlocked('Action result is uncertain; inspect the game before resuming')
        journal.finish(key, 'confirmed')
    except BaseException:
        # Includes cancellation, browser loss and timeouts. Never retry a click
        # whose server-side outcome is unknown.
        if journal.db.execute('SELECT status FROM actions WHERE id=?', (key,)).fetchone()[0] == 'intent':
            journal.finish(key, 'uncertain')
        raise
    return key
