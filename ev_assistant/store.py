"""Resumable, concurrent scan queue. No guessed game endpoints or mechanics.

Each worker receives a lease token. Expired workers cannot overwrite a newer
scan. A system's current records change only after a complete verified read.
"""
import csv
import sqlite3
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ScanLease:
    universe: str
    galaxy: int
    system: int
    token: str


@dataclass(frozen=True)
class Planet:
    position: int
    player: str
    name: str


class Store:
    def __init__(self, path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript('''
                CREATE TABLE IF NOT EXISTS scans (
                    universe TEXT NOT NULL, galaxy INTEGER NOT NULL,
                    system INTEGER NOT NULL, due REAL NOT NULL DEFAULT 0,
                    token TEXT, lease_until REAL, failures INTEGER NOT NULL DEFAULT 0,
                    last_complete REAL,
                    PRIMARY KEY (universe, galaxy, system)
                );
                CREATE TABLE IF NOT EXISTS planets (
                    universe TEXT NOT NULL, galaxy INTEGER NOT NULL,
                    system INTEGER NOT NULL, position INTEGER NOT NULL,
                    player TEXT NOT NULL, name TEXT NOT NULL, observed REAL NOT NULL,
                    PRIMARY KEY (universe, galaxy, system, position)
                );
                CREATE TABLE IF NOT EXISTS sightings (
                    universe TEXT NOT NULL, galaxy INTEGER NOT NULL,
                    system INTEGER NOT NULL, position INTEGER NOT NULL,
                    player TEXT NOT NULL, name TEXT NOT NULL, observed REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS slot_checks (
                    revision TEXT NOT NULL, universe TEXT NOT NULL,
                    galaxy INTEGER NOT NULL, system INTEGER NOT NULL,
                    position INTEGER NOT NULL, kind TEXT NOT NULL, owner TEXT,
                    observed REAL NOT NULL,
                    PRIMARY KEY (revision, universe, galaxy, system, position)
                );
                CREATE TABLE IF NOT EXISTS player_profiles (
                    universe TEXT NOT NULL, player TEXT COLLATE NOCASE NOT NULL,
                    alliance TEXT NOT NULL, observed REAL NOT NULL,
                    PRIMARY KEY (universe,player)
                );
            ''')

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def seed(self, universe, galaxies, systems):
        """Idempotently add an explicitly configured coordinate range."""
        galaxies, systems = list(galaxies), list(systems)
        if not universe.strip() or not galaxies or not systems:
            raise ValueError('Universe, galaxies, and systems are required')
        if any(type(n) is not int or n < 1 for n in galaxies + systems):
            raise ValueError('Coordinates must be positive integers')
        with self.connection() as db:
            db.executemany(
                'INSERT OR IGNORE INTO scans(universe,galaxy,system) VALUES (?,?,?)',
                [(universe, g, s) for g in galaxies for s in systems])

    def claim(self, universe, lease_seconds=60, now=None):
        if lease_seconds <= 0:
            raise ValueError('Lease duration must be positive')
        now = time.time() if now is None else now
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('''SELECT * FROM scans WHERE universe=? AND due<=?
                AND (token IS NULL OR lease_until<=?)
                ORDER BY due,galaxy,system LIMIT 1''', (universe, now, now)).fetchone()
            if row is None:
                return None
            token = uuid.uuid4().hex
            db.execute('''UPDATE scans SET token=?,lease_until=?
                WHERE universe=? AND galaxy=? AND system=?''',
                (token, now + lease_seconds, universe, row['galaxy'], row['system']))
            return ScanLease(universe, row['galaxy'], row['system'], token)

    def _check_lease(self, db, lease, now):
        row = db.execute('''SELECT * FROM scans WHERE universe=? AND galaxy=?
            AND system=? AND token=? AND lease_until>?''',
            (lease.universe, lease.galaxy, lease.system, lease.token, now)).fetchone()
        if row is None:
            raise ValueError('Scan lease expired or was replaced; discard this result')
        return row

    def complete(self, lease, planets, *, fully_read, rescan_seconds=3600, now=None):
        """Commit only a fully read system, including a verified empty system.

        The game adapter must verify navigation, loading completion, coordinate
        identity, and every row before setting fully_read=True.
        """
        if fully_read is not True or rescan_seconds <= 0:
            raise ValueError('A complete read and positive rescan interval are required')
        planets = list(planets)
        if any(type(p.position) is not int or p.position < 1 or not p.player.strip()
               for p in planets):
            raise ValueError('Invalid planet observation')
        if len({p.position for p in planets}) != len(planets):
            raise ValueError('Duplicate positions in system read')
        now = time.time() if now is None else now
        key = (lease.universe, lease.galaxy, lease.system)
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            self._check_lease(db, lease, now)
            db.execute('DELETE FROM planets WHERE universe=? AND galaxy=? AND system=?', key)
            values = [key + (p.position, p.player, p.name, now) for p in planets]
            db.executemany('INSERT INTO planets VALUES (?,?,?,?,?,?,?)', values)
            db.executemany('INSERT INTO sightings VALUES (?,?,?,?,?,?,?)', values)
            db.execute('''UPDATE scans SET token=NULL,lease_until=NULL,failures=0,
                last_complete=?,due=? WHERE universe=? AND galaxy=? AND system=?''',
                (now, now + rescan_seconds) + key)

    def fail(self, lease, now=None):
        """Preserve prior observations and back off after an unreadable page."""
        now = time.time() if now is None else now
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row = self._check_lease(db, lease, now)
            delay = min(3600, 10 * 2 ** min(row['failures'], 9))
            db.execute('''UPDATE scans SET token=NULL,lease_until=NULL,
                failures=failures+1,due=? WHERE universe=? AND galaxy=? AND system=?''',
                (now + delay, lease.universe, lease.galaxy, lease.system))

    def finish_pass(self, lease, rescan_seconds=3600, now=None):
        """Finish a configured subset; do not claim full-system coverage."""
        if rescan_seconds <= 0:
            raise ValueError('Rescan interval must be positive')
        now = time.time() if now is None else now
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            self._check_lease(db, lease, now)
            db.execute('''UPDATE scans SET token=NULL,lease_until=NULL,failures=0,
                due=? WHERE universe=? AND galaxy=? AND system=?''',
                (now + rescan_seconds, lease.universe, lease.galaxy, lease.system))

    def renew(self, lease, lease_seconds=600):
        now = time.time()
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            self._check_lease(db, lease, now)
            db.execute('UPDATE scans SET lease_until=? WHERE token=?',
                       (now + lease_seconds, lease.token))

    def search(self, player=None):
        with self.connection() as db:
            sql = 'SELECT * FROM planets'
            args = ()
            if player is not None:
                sql += ' WHERE player=? COLLATE NOCASE'
                args = (player,)
            sql += ' ORDER BY universe,galaxy,system,position'
            return [dict(r) for r in db.execute(sql, args)]

    def record_sighting(self, universe, galaxy, system, planet, now=None, lease=None):
        """Store one verified occupied slot without treating the system as complete."""
        if not universe.strip() or any(type(x) is not int or x < 1
                for x in (galaxy, system, planet.position)) or not planet.player.strip():
            raise ValueError('Invalid sighting')
        now = time.time() if now is None else now
        values = (universe, galaxy, system, planet.position, planet.player, planet.name, now)
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            if lease is not None:
                if (universe, galaxy, system) != (lease.universe, lease.galaxy, lease.system):
                    raise ValueError('Sighting does not belong to this lease')
                self._check_lease(db, lease, now)
            db.execute('INSERT OR REPLACE INTO planets VALUES (?,?,?,?,?,?,?)', values)
            db.execute('INSERT INTO sightings VALUES (?,?,?,?,?,?,?)', values)

    def export_csv(self, path):
        """Export observed game coordinates; escape spreadsheet formula prefixes."""
        columns = ['universe', 'galaxy', 'system', 'position', 'player', 'name', 'observed']
        with open(path, 'w', newline='', encoding='utf-8-sig') as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            for row in self.search():
                for key, value in row.items():
                    if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@')):
                        row[key] = "'" + value
                writer.writerow(row)

    def checked_slots(self, revision, universe, galaxy, system):
        with self.connection() as db:
            return {r['position']: dict(r) for r in db.execute(
                'SELECT * FROM slot_checks WHERE revision=? AND universe=? AND galaxy=? AND system=?',
                (revision, universe, galaxy, system))}

    def record_slot_check(self, revision, universe, galaxy, system, position, kind, owner=None):
        if position not in range(1, 22) or kind not in ('owned', 'npc', 'empty'):
            raise ValueError('Invalid slot verification')
        if kind == 'owned' and not owner:
            raise ValueError('Owned slot requires an owner')
        with self.connection() as db:
            db.execute('INSERT OR REPLACE INTO slot_checks VALUES (?,?,?,?,?,?,?,?)',
                (revision, universe, galaxy, system, position, kind, owner, time.time()))

    def checked_slot_count(self, revision):
        with self.connection() as db:
            return db.execute('SELECT count(*) FROM slot_checks WHERE revision=?', (revision,)).fetchone()[0]

    def checked_system_count(self, revision):
        with self.connection() as db:
            return db.execute('''SELECT count(*) FROM (
                SELECT universe,galaxy,system FROM slot_checks WHERE revision=?
                GROUP BY universe,galaxy,system HAVING count(*)=21)''', (revision,)).fetchone()[0]

    def record_alliance(self, universe, player, alliance, now=None):
        if alliance is None:
            return
        with self.connection() as db:
            db.execute('INSERT OR REPLACE INTO player_profiles VALUES (?,?,?,?)',
                (universe,player,alliance.strip(),time.time() if now is None else now))

    def profiles(self):
        with self.connection() as db:
            return [dict(r) for r in db.execute('SELECT * FROM player_profiles')]
