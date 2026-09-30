"""Capabilities and roles. Roles are data; the server always enforces, UI hiding is only cosmetic.

A check takes (principal, capability, resource). Resource-level rules (ownership, sharing) are
small `ScopeRule` callables registered per capability.
"""
from dataclasses import dataclass, field
from typing import Any, Callable

from .registry import Registry


@dataclass(frozen=True)
class Capability:
    id: str
    area: str
    description: str


CAPABILITIES: Registry[Capability] = Registry('capabilities')
for _area, _items in {
    'local': [('local.admin', 'Paired local operator: everything in the local API'),
              ('settings.write', 'Change settings'), ('sessions.manage', 'Edit/protect/archive sessions'),
              ('sessions.purge', 'Permanently delete archived sessions')],
    'telemetry': [('telemetry.viewOwn', 'See own telemetry'), ('telemetry.viewAll', 'See shared traffic of all drivers'),
                  ('telemetry.publishOwn', 'Publish own telemetry to a group')],
    'raceControl': [('raceControl.setFlag', 'Set/cancel flags'), ('raceControl.message', 'Send a message to one driver'),
                    ('raceControl.messageAll', 'Send a message to everyone'), ('raceControl.steward', 'Issue steward decisions'),
                    ('raceControl.session', 'Start/end/finalize the group session'), ('raceControl.zones', 'Edit zones'),
                    ('raceControl.admit', 'Admit/remove participants')],
    'graphics': [('graphics.view', 'View graphics workspaces'), ('graphics.edit', 'Edit a graphics draft'),
                 ('graphics.take', 'Take a draft to program'), ('graphics.issueOutput', 'Issue overlay credentials')],
    'league': [('league.configure', 'Configure the league/group'), ('branding.edit', 'Edit league branding')],
    'driver': [('driver.respond', 'Respond to race control (acknowledge, pit intent)')],
    'overlay': [('overlay.read', 'Read one workspace program')],
}.items():
    for _id, _desc in _items:
        CAPABILITIES.register(Capability(_id, _area, _desc))

_GROUP_HOST = tuple(c.id for c in CAPABILITIES if c.area in ('raceControl', 'graphics', 'league', 'telemetry'))

# role -> capabilities. `host` is the local operator running the group; future roles (steward,
# commentator, team manager) are new entries here, not new branches in service code.
ROLES: dict[str, frozenset[str]] = {
    'host': frozenset(c.id for c in CAPABILITIES),
    'driver': frozenset({'telemetry.publishOwn', 'telemetry.viewOwn', 'driver.respond'}),
    'spectator': frozenset({'graphics.view', 'graphics.edit', 'graphics.take', 'graphics.issueOutput'}),
    'overlay': frozenset({'overlay.read'}),
    # The paired local browser: everything except group-only driver/overlay capabilities.
    'local': frozenset(c.id for c in CAPABILITIES if c.area not in ('driver', 'overlay')),
}
# Optional grants a host can switch on for a role (e.g. traffic sharing lets drivers see the field).
CONDITIONAL_GRANTS: dict[tuple[str, str], str] = {('driver', 'telemetry.viewAll'): 'share_traffic_with_drivers'}


@dataclass(slots=True)
class Principal:
    kind: str                       # 'local' | 'host' | 'driver' | 'spectator' | 'overlay'
    subject: str = ''               # participant/workspace id
    group_id: str | None = None
    status: str = 'admitted'        # participants may be 'pending' or 'removed'
    flags: dict = field(default_factory=dict)   # e.g. {'share_traffic_with_drivers': True}
    scope: dict = field(default_factory=dict)   # e.g. {'workspace_id': ...} for overlays

    @property
    def role(self) -> str:
        return self.kind


ScopeRule = Callable[[Principal, Any], bool]
SCOPE_RULES: dict[str, ScopeRule] = {}


def scope_rule(capability: str):
    def deco(fn: ScopeRule) -> ScopeRule:
        if capability in SCOPE_RULES:
            raise ValueError(f'duplicate scope rule for {capability}')
        SCOPE_RULES[capability] = fn
        return fn
    return deco


def _owns_or_shared(p: Principal, resource) -> bool:
    """Workspace scoping: resource is a workspace dict (owner/shared_with) or None (no resource-level check)."""
    if resource is None or p.kind in ('host', 'local'):
        return True
    return p.subject == resource.get('owner') or p.subject in (resource.get('shared_with') or [])


for _cap in ('graphics.view', 'graphics.edit', 'graphics.take', 'graphics.issueOutput'):
    scope_rule(_cap)(_owns_or_shared)


@scope_rule('overlay.read')
def _overlay_scope(p: Principal, resource) -> bool:
    return resource is None or p.scope.get('workspace_id') == (resource.get('id') if isinstance(resource, dict) else resource)


def capabilities_for(p: Principal) -> frozenset[str]:
    if p.status not in ('admitted',) and p.kind in ('driver', 'spectator'):
        return frozenset()          # pending/removed participants hold no capability
    caps = set(ROLES.get(p.kind, frozenset()))
    for (role, cap), flag in CONDITIONAL_GRANTS.items():
        if role == p.kind and p.flags.get(flag):
            caps.add(cap)
    return frozenset(caps)


def can(p: Principal, capability: str, resource: Any = None) -> bool:
    if capability not in CAPABILITIES:
        raise KeyError(f'unknown capability {capability!r}')
    if capability not in capabilities_for(p):
        return False
    rule = SCOPE_RULES.get(capability)
    return rule(p, resource) if rule else True


def matrix() -> dict[str, list[str]]:
    """role -> sorted capabilities (used by contract generation and the matrix test)."""
    return {role: sorted(caps) for role, caps in ROLES.items()}
