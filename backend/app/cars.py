"""Offline, attributed car identity lookup. Unknown IDs never guess a brand."""
import json
from pathlib import Path
try:CATALOG=json.loads((Path(__file__).parent/'data/cars.json').read_text(encoding='utf-8'))
except FileNotFoundError:CATALOG={}
def identify(car_id):return CATALOG.get(str(car_id),{'name':f'Car {car_id}' if car_id is not None else 'Awaiting car','manufacturer':'Unknown manufacturer','logo':None})
