"""Single source for version numbers. Packaging, /api/health, the protocol hello and diagnostics read this."""
APP_VERSION = '0.3.0-beta'
PROTOCOL_VERSION = 2            # group envelope (group/protocol.py); v1 accepted for one release
PROTOCOL_SUPPORTED = (1, 2)
SETTINGS_SCHEMA_VERSION = 2     # core/config_migrations.py
DB_SCHEMA_VERSION = 8           # backend/migrations
ANALYSIS_VERSION = 1            # bump when analysis output changes (AnalysisCache key)


def versions(parser: str = '') -> dict:
    """`parser` is passed in by the caller: core depends on nothing in the app."""
    return {'app': APP_VERSION, 'parser': parser, 'protocol': PROTOCOL_VERSION,
            'settings_schema': SETTINGS_SCHEMA_VERSION, 'db_schema': DB_SCHEMA_VERSION,
            'analysis': ANALYSIS_VERSION}
