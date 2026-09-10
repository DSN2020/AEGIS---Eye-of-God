"""EVO canvas readers calibrated on the EVO colony interface, 2026-09-09.

470x912 viewport, fresh game load. No game state or network interception.
"""
from decimal import Decimal
import re
from .vision import UncertainScreen

BUILDINGS = {'Solar Plant': (110, 184), 'Gas Storage': (263, 350), 'Research Lab': (199, 535)}
RESOURCES = ('metal', 'crystal', 'gas')


def text(lines):
    return ' '.join(x.text for x in lines if x.confidence >= .90)


def region(lines, x1, y1, x2, y2):
    return [x for x in lines if x1 <= x.x <= x2 and y1 <= x.y <= y2 and x.confidence >= .90]


def amount(raw):
    raw = raw.strip()
    if not re.fullmatch(r'-?(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?[KMB]?',raw,re.I):
        raise UncertainScreen('Resource amount is not unambiguous')
    raw = raw.replace(',', '')
    match = re.fullmatch(r'(-?\d+(?:\.\d+)?)([KMB]?)', raw, re.I)
    if not match:
        raise UncertainScreen('Resource amount is not unambiguous')
    value, suffix = match.groups()
    factor = {'': 1, 'K': 1000, 'M': 1000000, 'B': 1000000000}[suffix.upper()]
    n = Decimal(value) * factor
    # Abbreviated values may be rounded or truncated. Use one full display
    # increment on each side, so affordability never relies on rounding up.
    step = Decimal(10) ** (-len(value.split('.')[1]) if '.' in value else 0) * factor if suffix else Decimal(0)
    return {'value': float(n), 'low': float(n-step), 'high': float(n+step), 'display': raw}


def numeric(lines, signed=False):
    found = []
    for line in lines:
        raw = line.text.strip()
        if re.fullmatch(r'-?\d[\d,]*(?:\.\d+)?[KMB]?', raw, re.I):
            found.append(amount(raw))
    if len(found) != 1 or (not signed and found[0]['low'] < 0):
        raise UncertainScreen('Expected one confidently read numeric value')
    return found[0]


def duration(raw):
    raw = raw.strip().lower()
    if not re.fullmatch(r'(?:\d+\s*[dhms]\s*)+', raw):
        raise UncertainScreen('Duration not fully readable')
    matches = re.findall(r'(\d+)\s*([dhms])', raw)
    if not matches:
        raise UncertainScreen('Duration not readable')
    units = [u for _, u in matches]
    if len(units) != len(set(units)):
        raise UncertainScreen('Ambiguous duration')
    return sum(int(n) * {'d':86400,'h':3600,'m':60,'s':1}[u] for n, u in matches)


def home(lines):
    labels = text(region(lines, 80, 815, 465, 911)).lower()
    if not all(word in labels for word in ('planets', 'fleet', 'alliance')):
        raise UncertainScreen('Not the colony home screen')
    boxes = {'metal': (35, 58, 90, 98), 'crystal': (105, 58, 163, 98),
             'gas': (178, 58, 241, 98), 'energy': (253, 58, 297, 98)}
    values = {key: numeric(region(lines, *box), signed=key == 'energy') for key, box in boxes.items()}
    return {'stock': {r: values[r] for r in RESOURCES}, 'energy': values['energy']}


def planet_identity(lines, account, coordinate):
    page = text(lines)
    if 'Planet Info' not in page:
        raise UncertainScreen('Planet identity popup is not open')
    found = re.search(r'\[?(\d+):(\d+):(\d+)\]?', text(region(lines, 180, 495, 350, 551)))
    if not found or ':'.join(found.groups()) != coordinate:
        raise UncertainScreen('Colony coordinate differs from the configured colony')
    # Account identity is checked independently on EVO's visible saved-login
    # screen. Planet names are not accepted as account identity evidence.
    return coordinate


def building(lines, expected):
    title = text(region(lines, 100, 10, 375, 58))
    if re.sub(r'\s+','',expected).casefold() != re.sub(r'\s+','',title).casefold():
        raise UncertainScreen(f'Expected {expected}; building title did not match')
    level_match = re.search(r'Level\s*:\s*(\d+)', text(region(lines, 35, 120, 205, 175)), re.I)
    if not level_match:
        raise UncertainScreen('Building level is unreadable')
    level = int(level_match.group(1))
    body = text(region(lines, 25, 285, 445, 770))
    buttons = text(region(lines, 20, 795, 445, 861))
    upgrading = re.search(r'Upgrading to level\s*(\d+)', body, re.I)
    if upgrading:
        if int(upgrading.group(1)) != level + 1 or 'Speed Up' not in buttons:
            raise UncertainScreen('Construction queue presentation is ambiguous')
        return {'name': expected, 'level': level, 'busy': True, 'to_level': level + 1}
    if expected == 'Research Lab' and 'Upgrade' not in buttons and 'Research Tech' in text(lines):
        return {'name': expected, 'level': level, 'busy': True, 'research_busy': True}
    target = [x for x in lines if x.confidence >= .9 and re.search(r'Required for upgrade to Level\s*\d+', x.text, re.I)]
    if len(target) != 1:
        raise UncertainScreen('Upgrade requirement heading is unreadable')
    next_level = int(re.search(r'Level\s*(\d+)', target[0].text, re.I).group(1))
    if next_level != level + 1 or not re.search(r'\bUpgrade\b', buttons) or re.search(r'Speed Up|Cancel', buttons, re.I):
        raise UncertainScreen('Upgrade button or target level did not match')
    y = target[0].y
    # Three cost columns remain in fixed order, but long labels make their
    # numeric positions vary within their column.
    ranges = [(65, 137), (175, 248), (291, 390)]
    cost = {r: numeric(region(lines, xa, y + 30, xb, y + 80)) for r, (xa, xb) in zip(RESOURCES, ranges)}
    seconds = duration(text(region(lines, 195, y + 72, 390, y + 125)))
    return {'name': expected, 'level': level, 'to_level': next_level, 'busy': False,
            'cost': cost, 'seconds': seconds, 'button': [354, 828]}


TECHS = {'Basic': ['Energy Tech','Laser Tech','Ion Tech','Hyperspace Tech'],
         'Advanced': ['Computer Tech','Espionage Tech','Astrophysics Tech','Combustion Drive']}


def tech_card(lines, tab, name):
    if name not in TECHS.get(tab, []):
        raise UncertainScreen('Research item has no calibrated row')
    titles = [line for line in region(lines,165,160,402,805)
              if re.sub(r'\s+','',line.text).casefold() == re.sub(r'\s+','',name).casefold()]
    if len(titles) != 1:
        raise UncertainScreen('Research row title did not match')
    top = titles[0].y - 21.4
    if top + 153 > 872:
        raise UncertainScreen('Scroll the research row fully into view')
    level = re.search(r'Lv\.?\s*(\d+)', text(region(lines, 60, top + 128, 137, top + 165)), re.I)
    if not level:
        raise UncertainScreen('Research level is unreadable')
    card = text(region(lines, 160, top + 20, 449, top + 162))
    busy = 'Cancel' in card and 'Speed Up' in card
    result = {'name': name, 'level': int(level.group(1)), 'busy': busy, 'button': [414, top + 135],
            'top': top, 'seconds': duration(text(region(lines, 195, top + 59, 370, top + 92)))}
    if not busy:
        currencies = {'Energy Tech': ('crystal','gas'), 'Laser Tech': ('metal','crystal'),
            'Ion Tech': RESOURCES, 'Hyperspace Tech': RESOURCES,
            'Computer Tech': ('crystal','gas'), 'Espionage Tech': RESOURCES,
            'Astrophysics Tech': RESOURCES, 'Combustion Drive': ('metal','crystal')}[name]
        cells = sorted(region(lines, 195, top + 32, 410, top + 58), key=lambda x: x.x)
        numbers = [amount(x.text) for x in cells if re.fullmatch(r'\d[\d,]*(?:\.\d+)?[KMB]?', x.text.strip(), re.I)]
        if len(numbers) != len(currencies):
            raise UncertainScreen('Research cost columns are not confidently readable')
        result['cost'] = {r: amount('0') for r in RESOURCES}
        result['cost'].update(dict(zip(currencies, numbers)))
    return result


def nebula(lines, coordinate):
    expected=[int(x) for x in coordinate.split(':')[:2]]+[21]
    for x,value in zip((89,235,381),expected):
        shown=numeric(region(lines,x-35,15,x+35,44))
        if shown['value']!=value:raise UncertainScreen('Nebula map coordinate differs from the profile')
    heading=re.sub(r'\s+','',text(region(lines,60,340,410,375)))
    if heading!='MysteriousNebula':raise UncertainScreen('Nebula details are not open')
    label=re.sub(r'\s+','',text(region(lines,60,380,410,411)))
    found=re.fullmatch(r'SafeExplorations:(\d+)/(\d+)',label)
    if not found:raise UncertainScreen('Safe exploration counter is unreadable')
    available,limit=map(int,found.groups())
    if not 0<=available<=limit or limit==0:raise UncertainScreen('Safe exploration counter is ambiguous')
    return {'available':available,'limit':limit}


def gamma_store(lines):
    if text(region(lines,100,10,375,58))!='Store':raise UncertainScreen('Store is not open')
    if text(region(lines,130,350,340,382))!='Gamma Detector':raise UncertainScreen('Gamma store row did not match')
    label=text(region(lines,190,432,340,460))
    found=re.fullmatch(r'Owned:\s*(\d+)',label)
    if not found:raise UncertainScreen('Owned Gamma count is unreadable')
    if text(region(lines,370,422,445,448))!='Use':raise UncertainScreen('Gamma Use button did not match')
    return {'owned':int(found[1]),'button':[404,436]}


def gamma_quantity(lines):
    if text(region(lines,95,320,385,360))!='Use Gamma Detector':raise UncertainScreen('Gamma quantity dialog did not match')
    count=numeric(region(lines,310,438,385,476))
    if count['value']!=1:raise UncertainScreen('Gamma quantity must be exactly one')
    return {'quantity':1,'button':[148,565]}


def gamma_confirmation(lines):
    # Background inventory labels overlap this region: require the unique exact
    # confirmation line rather than concatenating them with the modal message.
    matches=[l for l in region(lines,105,430,370,470) if l.text=='Use Gamma Detector x1?']
    if len(matches)!=1:raise UncertainScreen('Exact one-Gamma confirmation did not match')
    return {'quantity':1,'button':[148,565]}


def colony_return(lines, coordinate):
    if text(region(lines,100,10,375,58))!='Planets':raise UncertainScreen('Owned planet list is not open')
    matches=[l for l in region(lines,345,100,460,760) if l.text.strip('[] ')==coordinate]
    if len(matches)!=1:raise UncertainScreen('Configured colony is not visible in the owned planet list')
    y=matches[0].y
    label=re.sub(r'\s+','',text(region(lines,370,y+73,458,y+96)))
    if label!='Gohere':raise UncertainScreen('Colony Go here button did not match')
    return {'coordinate':coordinate,'button':[419,y+55]}
