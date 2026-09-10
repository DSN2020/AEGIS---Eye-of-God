"""Bounded, event-based planning from observed costs, never borrowed game formulas.

Amounts and hourly rates retain their resource units. User-supplied weights are
used only to compare final outcomes, never to pay one resource with another.
"""
from copy import deepcopy
import math


def number(value, label, minimum=0):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < minimum:
        raise ValueError(f'{label} must be a finite number >= {minimum}')
    return float(value)


def validate(snapshot):
    if not snapshot.get('account') or not snapshot.get('universe'):
        raise ValueError('Account and universe are required')
    number(snapshot.get('observed_at'), 'Observation time')
    resources = snapshot.get('resource_names', [])
    if not resources or len(set(resources)) != len(resources):
        raise ValueError('Resource names must be unique and nonempty')
    planets = snapshot.get('planets', {})
    if not planets:
        raise ValueError('At least one colony is required')
    for name, planet in planets.items():
        for field in ('stock', 'production', 'capacity'):
            if set(planet.get(field, {})) != set(resources):
                raise ValueError(f'{name}: {field} must include every resource')
            for resource, value in planet[field].items():
                number(value, f'{name} {field} {resource}')
        number(planet.get('energy_free', 0), f'{name} energy', -1e15)
    for level in snapshot.get('levels', {}).values():
        if type(level) is not int or level < 0:
            raise ValueError('Levels must be nonnegative integers')
    ids = set()
    for action in snapshot.get('actions', []):
        if not action.get('id') or action['id'] in ids:
            raise ValueError('Upgrade IDs must be nonempty and unique')
        ids.add(action['id'])
        if action.get('kind') not in ('building', 'research') or action.get('planet') not in planets:
            raise ValueError('Upgrade kind or colony is invalid')
        if not action.get('level_key') or type(action.get('from_level')) is not int or action['from_level'] < 0:
            raise ValueError('Upgrade level identity is required')
        number(action.get('duration_hours'), 'Upgrade duration', .000001)
        if set(action.get('cost', {})) != set(resources):
            raise ValueError('Each upgrade cost must include every resource')
        for r, value in action['cost'].items():
            number(value, f'Cost {r}')
        for field in ('production_delta', 'capacity_delta'):
            for r, value in action.get(field, {}).items():
                if r not in resources:
                    raise ValueError('Unknown resource in upgrade effect')
                number(value, field)
        number(action.get('energy_delta', 0), 'Energy delta', -1e15)
        number(action.get('research_value', 0), 'Research goal value')
        for key, level in action.get('requires', {}).items():
            if not key or type(level) is not int or level < 0:
                raise ValueError('Invalid prerequisite')
    for event in snapshot.get('queues', []):
        if event.get('action_id') not in ids:
            raise ValueError('Queued upgrade needs its observed effects in actions')
        number(event.get('remaining_hours'), 'Queue remaining time')
    return snapshot


def lane(action):
    # Research queue is account-wide; construction is per colony.
    return 'research' if action['kind'] == 'research' else 'building:' + action['planet']


def advance(state, target):
    while state['time'] < target or any(e['end'] <= target for e in state['events']):
        next_end = min([e['end'] for e in state['events']] + [target])
        dt = max(0, next_end - state['time'])
        for planet in state['planets'].values():
            for r in planet['stock']:
                # Existing over-cap stock is retained; production stops at cap.
                room = max(0, planet['capacity'][r] - planet['stock'][r])
                planet['stock'][r] += min(room, planet['production'][r] * dt)
        state['time'] = next_end
        completed = [e for e in state['events'] if e['end'] <= next_end + 1e-10]
        for event in completed:
            action = event['action']
            p = state['planets'][action['planet']]
            for field, delta in (('production', 'production_delta'), ('capacity', 'capacity_delta')):
                for r, value in action.get(delta, {}).items():
                    p[field][r] += value
            p['energy_free'] += action.get('energy_delta', 0)
            state['levels'][action['level_key']] = action['from_level'] + 1
            state['research_value'] += action.get('research_value', 0)
            state['events'].remove(event)
        if next_end >= target:
            return


def attempt(parent, action, horizon, reserves):
    state = deepcopy(parent)
    if action['id'] in state['used']:
        return None
    for _ in range(100):
        # Busy lanes and prerequisites can become available after queued completions.
        queue_busy = any(lane(e['action']) == lane(action) for e in state['events'])
        correct_level = state['levels'].get(action['level_key'], 0) == action['from_level']
        prerequisites = all(state['levels'].get(k, 0) >= v for k, v in action.get('requires', {}).items())
        p = state['planets'][action['planet']]
        pending_energy = sum(min(0, e['action'].get('energy_delta', 0)) for e in state['events'] if e['action']['planet'] == action['planet'])
        energy_ok = (action.get('energy_delta', 0) > 0 or
                     p['energy_free'] + pending_energy + min(0, action.get('energy_delta', 0)) >= 0)
        wait = 0.0
        for r, cost in action['cost'].items():
            needed = cost + reserves.get(r, 0) - p['stock'][r]
            if needed > 1e-8:
                if p['production'][r] <= 0 or cost + reserves.get(r, 0) > p['capacity'][r]:
                    wait = math.inf
                else:
                    wait = max(wait, needed / p['production'][r])
        if not queue_busy and correct_level and prerequisites and energy_ok and wait <= 1e-8:
            end = state['time'] + action['duration_hours']
            if end > horizon:
                return None
            for r, cost in action['cost'].items():
                p['stock'][r] -= cost
            state['used'].add(action['id'])
            state['events'].append({'end': end, 'action': action})
            state['steps'].append({'id': action['id'], 'name': action.get('name', action['id']),
                'planet': action['planet'], 'kind': action['kind'], 'start_hours': state['time'],
                'end_hours': end, 'cost': action['cost'], 'from_level': action['from_level'],
                'reason': 'Research milestone' if action.get('research_value') else 'Projected economy benefit'})
            return state
        next_event = min([e['end'] for e in state['events']] + [math.inf])
        candidate_time = state['time'] + wait if not queue_busy and correct_level and prerequisites and energy_ok and wait > 1e-8 else math.inf
        target = min(next_event, candidate_time)
        if not math.isfinite(target) or target >= horizon:
            return None
        advance(state, target)
    return None


def score(state, horizon, weights, research_weight):
    end = deepcopy(state)
    advance(end, horizon)
    wealth = sum(amount * weights.get(r, 1) for p in end['planets'].values() for r, amount in p['stock'].items())
    return wealth + end['research_value'] * research_weight, end


def plan(snapshot, settings=None):
    validate(snapshot)
    settings = settings or {}
    horizon = number(settings.get('horizon_hours', 72), 'Planning horizon', 1)
    if horizon > 720:
        raise ValueError('Planning horizon must be at most 720 hours')
    weights = settings.get('resource_weights', {})
    reserves = settings.get('reserves', {})
    for r, value in {**weights, **reserves}.items():
        if r not in snapshot['resource_names']:
            raise ValueError('Unknown resource in preferences')
        number(value, 'Resource preference')
    research_weight = number(settings.get('research_weight', 1), 'Research weight')
    depth = settings.get('depth', 5)
    width = settings.get('beam_width', 24)
    if type(depth) is not int or not 1 <= depth <= 10 or type(width) is not int or not 1 <= width <= 64:
        raise ValueError('Search depth or width out of range')
    initial = {'time': 0., 'planets': deepcopy(snapshot['planets']), 'levels': deepcopy(snapshot.get('levels', {})),
               'events': [], 'used': set(), 'steps': [], 'research_value': 0.}
    for p in initial['planets'].values():
        p.setdefault('energy_free', 0)
    actions = snapshot.get('actions', [])
    for event in snapshot.get('queues', []):
        a = next(a for a in actions if a['id'] == event['action_id'])
        if a['id'] in initial['used'] or any(lane(e['action']) == lane(a) for e in initial['events']):
            raise ValueError('Duplicate or conflicting active queue')
        initial['events'].append({'end': event['remaining_hours'], 'action': a})
        initial['used'].add(a['id'])
    advance(initial, 0)
    baseline, _ = score(initial, horizon, weights, research_weight)
    best, best_score, frontier, evaluated = initial, baseline, [initial], 1
    for _ in range(depth):
        candidates = []
        for parent in frontier:
            for action in actions:
                child = attempt(parent, action, horizon, reserves)
                if child is None:
                    continue
                value, _ = score(child, horizon, weights, research_weight)
                evaluated += 1
                candidates.append((value, child))
                if value > best_score + 1e-8:
                    best, best_score = child, value
        if not candidates:
            break
        candidates.sort(key=lambda pair: pair[0], reverse=True)
        # Keep paths which may enable a profitable prerequisite chain, even when
        # their first investment temporarily scores below doing nothing.
        frontier = [child for _, child in candidates[:width]]
    _, end = score(best, horizon, weights, research_weight)
    return {'account': snapshot['account'], 'universe': snapshot['universe'],
            'observed_at': snapshot['observed_at'], 'source': snapshot.get('source', 'import'),
            'horizon_hours': horizon, 'steps': best['steps'], 'baseline_score': baseline,
            'projected_score': best_score, 'gain': best_score - baseline, 'evaluated': evaluated,
            'projected_planets': end['planets'],
            'explanation': 'Bounded search using supplied costs and effects; not a proof of global optimality. Research values are explicit goal preferences.'}
