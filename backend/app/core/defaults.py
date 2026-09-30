"""Centralised defaults and magic numbers. Settings validators and services reference these."""
# Network
UDP_PORT = 33740            # GT7 telemetry receive port (local)
REMOTE_PORT = 33739         # PS5 heartbeat target port
HTTP_PORT = 8000
GROUP_PUBLIC_PORT = 8090
LOCAL_AI_PORT = 28380
HEARTBEAT_S = 1.0
STALE_S = 2.0
INTERRUPT_S = 30.0
# Rates
UI_HZ = 12
UI_HZ_LOW_POWER = 8
GROUP_PUBLISH_HZ = 5          # driver -> host publish rate default (the UI may choose 1-10)
GROUP_PUBLISH_HZ_LOW_POWER = 3
TRACK_SERVICE_HZ = 5        # track projection is self-throttled to this rate
LIVE_ANALYSIS_HZ = 5
BATTLE_TICK_HZ = 2
# Buffers (all bounded)
RECORDER_QUEUE = 8192
RECORDER_BATCH = 240
RECORDER_BATCH_WINDOW_S = 0.20
TRACE_LEN = 600
HISTORY_LEN = 600
HISTORY_LEN_LOW_POWER = 300
HISTORY_WINDOW_S = 180
EVENT_LEN = 100
MAP_CAPTURE_POINTS = 4096
CORPUS_MAX_BYTES = 40 * 1024 * 1024
UPLOAD_MAX_BYTES = 5 * 1024 * 1024
REQUEST_MAX_BYTES = 34 * 1024 * 1024
IMPORT_MAX_BYTES = 32 * 1024 * 1024
ANALYSIS_CACHE_MAX_BYTES = 500 * 1024 * 1024
ERROR_RING = 50
# Retention
RETENTION_DAYS = 90
# Logging
LOG_MAX_BYTES = 5 * 1024 * 1024
LOG_BACKUPS = 5
LOG_REPEAT_WINDOW_S = 60.0
