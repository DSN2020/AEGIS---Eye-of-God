"""Validated, credential-free profile and preset definitions."""
import copy
import math
import re
import uuid
from datetime import datetime
from .evo_screen import BUILDINGS, TECHS

METRICS = ['metal', 'crystal', 'gas', 'energy', 'safe_runs']

def number(value, name, minimum=0, maximum=1e15):
    if isinstance(value, bool): raise ValueError(f'{name} must be a number')
    try: value=float(value)
    except (ValueError, TypeError): raise ValueError(f'{name} must be a number')
    if not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError(f'{name} must be between {minimum:g} and {maximum:g}')
    return value

def timestamp(value):
    if value in (None, ''): return None
    try:
        result=datetime.fromisoformat(str(value))
        if result.tzinfo is None: raise ValueError()
        return result.timestamp()
    except ValueError: raise ValueError('Schedule times must include a time zone')

def validate(raw):
    p=copy.deepcopy(raw)
    # Whitelist public fields: passwords and unrecognized keys are never persisted.
    result={k:p.get(k) for k in ('id','name','account','coordinate','mode','startAt','endAt')}
    result['id']=str(result['id'] or uuid.uuid4().hex)
    if not re.fullmatch(r'[a-f0-9]{32}',result['id']): raise ValueError('Invalid profile ID')
    for key in ('name','account','coordinate'):
        result[key]=str(result[key] or '').strip()
        if not result[key] or len(result[key])>100: raise ValueError(f'{key.title()} is required (100 characters maximum)')
    m=re.fullmatch(r'([1-9]):([1-9][0-9]{0,2}):([1-9][0-9]?)',result['coordinate'])
    if not m or not 1<=int(m[2])<=499 or not 1<=int(m[3])<=20:
        raise ValueError('Enter a colony coordinate such as 1:25:10 (positions 1–20)')
    if result['mode'] not in ('watch','plan','auto'): raise ValueError('Choose Watch, Plan or Auto')
    result['universe']='EV-T ORION 1'
    result['interval']=number(p.get('interval',30),'Check interval',10,86400)
    result['reserves']={r:number(p.get('reserves',{}).get(r,0),r+' reserve') for r in ('metal','crystal','gas')}
    result['max_upgrade_cost']=number(p.get('max_upgrade_cost',10000000),'Per-resource cost limit',1)
    result['energy_margin']=number(p.get('energy_margin',100),'Energy target',0,1000000000)
    result['solar_level_limit']=int(number(p.get('solar_level_limit',20),'Solar level limit',1,100))
    result['restore_energy']=True
    limit=number(p.get('gamma_limit',1),'Gamma limit per 24 hours',1,100)
    if limit!=int(limit): raise ValueError('Gamma limit must be a whole number')
    result['gamma_limit']=int(limit)
    result['research_goals']=[]
    start,end=timestamp(result['startAt']),timestamp(result['endAt'])
    if start is not None and end is not None and end<=start: raise ValueError('End time must be after start time')
    steps=p.get('steps',[])
    if not isinstance(steps,list) or len(steps)>100: raise ValueError('Use at most 100 plan steps')
    result['steps']=[]
    for step in steps:
        kind=step.get('kind'); name=str(step.get('name',''))
        if kind=='building' and name not in BUILDINGS: raise ValueError('Building is not calibrated: '+name)
        if kind=='research' and not any(name in names for names in TECHS.values()): raise ValueError('Research is not calibrated: '+name)
        if kind=='resource' and name not in ('metal','crystal','gas'): raise ValueError('Choose metal, crystal or gas')
        if kind not in ('building','research','wait','resource'): raise ValueError('Unknown plan step')
        value=number(step.get('value'), 'Step target',1,86400*30 if kind=='wait' else 1e15)
        if kind in ('building','research') and (value!=int(value) or value>100): raise ValueError('Upgrade targets must be whole levels from 1 to 100')
        result['steps'].append({'kind':kind,'name':name,'value':value})
    if result['mode']=='plan' and not result['steps']: raise ValueError('Add at least one plan step')
    result['rules']=[]
    for rule in p.get('rules',[]):
        if len(result['rules'])>=50: raise ValueError('Use at most 50 watch rules')
        if rule.get('metric') not in METRICS: raise ValueError('This watch metric is not calibrated yet')
        if rule.get('op') not in ('<=','>='): raise ValueError('Choose <= or >=')
        action=rule.get('action','alert')
        if action not in ('alert','use_gamma'): raise ValueError('Only alerts or owned Gamma activation are supported; purchases are disabled')
        if action=='use_gamma' and (rule['metric']!='safe_runs' or rule['op']!='<=' or rule.get('value')!=0):
            raise ValueError('Choose Safe nebula runs <= 0 for owned Gamma activation')
        result['rules'].append({'metric':rule['metric'],'op':rule['op'],'value':number(rule.get('value'),'Watch threshold',-1e15),
            'action':action,'cooldown':number(rule.get('cooldown',300),'Alert cooldown',10,86400*30)})
    return result

def preset(profile, name):
    if not name.strip() or len(name)>100: raise ValueError('Enter a preset name (100 characters maximum)')
    return {'name':name.strip(), 'settings':{k:copy.deepcopy(v) for k,v in profile.items()
        if k not in ('id','name','account','coordinate','startAt','endAt')}}
