"""Per-document schema versions for group documents.

Every stored document may carry an integer `schema`. Documents written before this existed have
none and count as schema 1. `upgrade()` runs when a document is loaded (group/repository.py) and
brings it to the current schema in memory; it is written back lazily by the next commit of that
document, so old databases need no bulk rewrite.

Adding a change: bump CURRENT_SCHEMA[doc_type] and register `UPGRADES[(doc_type, old)] = fn`,
where `fn(doc) -> doc` upgrades one step and must be idempotent and never drop data.
"""
import logging
import uuid
from typing import Callable

log = logging.getLogger('storage')

CURRENT_SCHEMA: dict[str, int] = {
    'league': 2,            # 2: branding.teams[].team_id
    'league_revision': 2,   # same shape as league
    'group': 2,             # 2: team_id inside branding_snapshot / branding override
    'group_session': 2,     # a saved group document
    'asset': 2,             # 2: kind, name, license_note, created_by
    'workspace': 1,
}
ASSET_KINDS = ('logo', 'sponsor', 'team', 'driver_photo', 'background')

_TEAM_NAMESPACE = uuid.UUID('6f1d3b52-7d1a-4c55-9a53-6c6f7de5a1a1')


class MissingUpgrade(RuntimeError):
    pass


def team_id_for(league_id: str, name: str, index: int = 0) -> str:
    """Deterministic id: an in-memory upgrade yields the same id every time, before and after write-back."""
    return uuid.uuid5(_TEAM_NAMESPACE, f'{league_id}:{str(name).casefold()}:{index}').hex


def ensure_team_ids(teams, league_id: str = '') -> list:
    """Give every team row a stable `team_id`, keeping name-keyed lookups and existing ids working.

    A row that already has `team_id` keeps it; else the frontend's existing `id` is reused so both
    keys agree; else a deterministic id is derived from league + name.
    """
    if not isinstance(teams, list):
        return teams
    used = {t['team_id'] for t in teams if isinstance(t, dict) and t.get('team_id')}
    for position, team in enumerate(teams):
        if not isinstance(team, dict) or team.get('team_id'):
            continue
        candidate = team.get('id') if isinstance(team.get('id'), str) and team.get('id') else team_id_for(league_id, team.get('name', ''))
        if candidate in used:
            candidate = team_id_for(league_id, team.get('name', ''), position + 1)
        team['team_id'] = candidate
        used.add(candidate)
    return teams


def _branding_teams(branding, league_id: str) -> None:
    if isinstance(branding, dict) and 'teams' in branding:
        ensure_team_ids(branding['teams'], league_id)


def _league_1_to_2(doc: dict) -> dict:
    _branding_teams(doc.get('branding'), doc.get('id', ''))
    return doc


def _group_1_to_2(doc: dict) -> dict:
    snapshot = doc.get('branding_snapshot')
    league_id = doc.get('league_id') or (snapshot or {}).get('id', '')
    if isinstance(snapshot, dict):
        _branding_teams(snapshot.get('branding'), snapshot.get('id') or league_id)
    _branding_teams(doc.get('branding'), league_id)      # per-event override
    return doc


def _asset_1_to_2(doc: dict) -> dict:
    doc.setdefault('kind', 'logo')
    doc.setdefault('name', '')
    doc.setdefault('license_note', '')
    doc.setdefault('created_by', 'host')
    return doc


UPGRADES: dict[tuple[str, int], Callable[[dict], dict]] = {
    ('league', 1): _league_1_to_2,
    ('league_revision', 1): _league_1_to_2,
    ('group', 1): _group_1_to_2,
    ('group_session', 1): _group_1_to_2,
    ('asset', 1): _asset_1_to_2,
}


def schema_of(doc: dict) -> int:
    version = doc.get('schema', 1)
    return version if isinstance(version, int) and version >= 1 else 1


def upgrade(doc_type: str, doc):
    """Bring `doc` to the current schema for its type (in place). Unknown types and non-dicts pass through.

    A document from a newer app (schema above current) is returned untouched rather than guessed at.
    """
    target = CURRENT_SCHEMA.get(doc_type)
    if target is None or not isinstance(doc, dict):
        return doc
    version = schema_of(doc)
    if version > target:
        log.warning('group document is newer than this app', extra={'event': 'group_schema_newer', 'details': {
            'doc_type': doc_type, 'schema': version, 'supported': target}})
        return doc
    while version < target:
        step = UPGRADES.get((doc_type, version))
        if step is None:
            raise MissingUpgrade(f'no upgrade for {doc_type} schema {version}')
        doc = step(doc)
        version += 1
        doc['schema'] = version
    doc.setdefault('schema', target)
    return doc


def stamp(doc_type: str, doc):
    """Mark a document about to be written as current (new documents and lazy write-back)."""
    target = CURRENT_SCHEMA.get(doc_type)
    if target is not None and isinstance(doc, dict) and schema_of(doc) <= target:
        doc['schema'] = target
    return doc
