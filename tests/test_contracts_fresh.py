"""Generated contract docs / frontend registries must match the live Python registries."""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_generator():
    spec = importlib.util.spec_from_file_location('gen_contracts', ROOT / 'scripts' / 'gen-contracts.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_generated_contracts_are_fresh():
    gen = load_generator()
    stale = [p.relative_to(ROOT).as_posix() for p, text in gen.outputs().items()
             if not p.exists() or p.read_text(encoding='utf-8') != text]
    assert not stale, f'Stale generated files, run `python scripts/gen-contracts.py`: {stale}'


def test_generation_is_deterministic():
    gen = load_generator()
    assert gen.outputs() == gen.outputs()


def test_contract_content_is_complete():
    gen = load_generator()
    d = gen.collect()
    from backend.app.telemetry.parser import FIELDS, UNSUPPORTED
    ids = {c['id'] for c in d['channels']}
    assert {name for name, *_ in FIELDS} <= ids and set(UNSUPPORTED) <= ids       # every field and every N/A slot is exported
    assert {c['id'] for c in d['commands']} >= {'session.end', 'source.demo', 'settings.update'}
    assert set(d['roles']) == {'host', 'driver', 'spectator', 'overlay', 'local'}
    assert len(d['graphics']) >= 26 and {r['id'] for r in d['rules']} >= {'low_fuel', 'tyre_heat_rate'}
    assert {m['type'] for m in d['messages']} >= {'hello', 'telemetry', 'lap'}
    tsc = json.loads((ROOT / 'frontend' / 'src' / 'domain' / 'channels.generated.ts').read_text(encoding='utf-8')
                     .split('export const CHANNELS:ChannelDef[]=', 1)[1])
    assert any(c['id'] == 'tyre_wear' and c['source'] == 'unavailable' for c in tsc)
