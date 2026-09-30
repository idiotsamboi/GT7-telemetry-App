"""Lightweight module registry. A feature is a module file plus one line in the composition root.

Not a public plugin API: nothing here loads third-party code.
"""
from dataclasses import dataclass, field
from typing import Any, Callable

from .registry import Registry


@dataclass(frozen=True)
class ModuleDef:
    id: str
    name: str
    description: str = ''
    services: tuple[str, ...] = ()               # ids of services this module contributes (see runtime composition)
    commands: tuple[str, ...] = ()               # command ids (registered in core.commands.COMMANDS)
    capabilities: tuple[str, ...] = ()
    channels: tuple[str, ...] = ()               # telemetry channel ids the module owns
    rules: tuple[str, ...] = ()                  # engineer alert-rule ids
    routes: Callable[[Any, Any], None] | None = None     # adapter layer registers HTTP (router, ctx)
    diagnostics: Callable[[], dict] | None = None
    feature_flag: str | None = None
    settings_fields: tuple[str, ...] = ()        # namespaced Settings fields the module owns


MODULES: Registry[ModuleDef] = Registry('modules', public=lambda m: {
    'id': m.id, 'name': m.name, 'description': m.description, 'services': list(m.services),
    'commands': list(m.commands), 'capabilities': list(m.capabilities), 'channels': list(m.channels),
    'rules': list(m.rules), 'feature_flag': m.feature_flag, 'settings_fields': list(m.settings_fields)})
