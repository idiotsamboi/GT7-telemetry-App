# 0004. Capability-based permissions with data-driven roles

Status: accepted

## Context
Permission checks in the group service were inline (`principal['kind'] in (...)`, `role != 'spectator'`,
workspace owner/shared lists). Adding a role (steward, commentator, team manager) meant new branches.

## Decision
`core/permissions.py` defines dot-namespaced **capabilities** (`raceControl.setFlag`, `graphics.take`,
`telemetry.viewAll`, ...) and **roles as data** (`ROLES: dict[role, set[capability]]`). A check is
`can(principal, capability, resource)`: role grants first, then an optional per-capability `ScopeRule`
(workspace ownership/sharing, overlay workspace binding). Conditional grants (e.g. drivers see the field
only when the host enabled traffic sharing) are data too. Pending/removed participants hold nothing.

The **server always enforces**; the frontend receives `GET /api/me/capabilities` (and group `/me`) and
uses `can()` only to hide or disable UI.

## Consequences
- A new permission = a capability, a role-map entry and a row in the matrix test
  (`tests/test_permissions_matrix.py`, role × action → allow/deny, written against pre-refactor behaviour).
- Every command declares the capability it needs (`CommandDef.capability`), so `dispatch()` enforces it
  uniformly.
