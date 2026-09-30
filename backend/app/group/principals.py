"""Bridge from the credential dicts the group service authenticates to `core.permissions.Principal`."""
from typing import Any

from ..core.permissions import Principal, can

# Group config keys that switch on conditional grants (see core.permissions.CONDITIONAL_GRANTS).
FLAG_KEYS = ('share_traffic_with_drivers',)


def principal_from_dict(d: dict[str, Any], member: dict | None = None, group: dict | None = None) -> Principal:
    """Build a Principal from an authenticated credential dict.

    `member` is the participant record (its `status` decides whether a driver/spectator holds any
    capability; omitted means "admitted", for callers that only need role scoping). `group` supplies
    the config flags for conditional grants.
    """
    kind = d['kind']
    flags = {key: bool((group or {}).get(key)) for key in FLAG_KEYS}
    scope = {'workspace_id': d['subject']} if kind == 'overlay' else {}
    return Principal(kind=kind, subject=d.get('subject', ''), group_id=d.get('group_id'),
                     status=(member or {}).get('status', 'admitted'), flags=flags, scope=scope)


def allowed(d: dict[str, Any], capability: str, resource: Any = None,
            member: dict | None = None, group: dict | None = None) -> bool:
    """`can()` for a credential dict."""
    return can(principal_from_dict(d, member, group), capability, resource)
