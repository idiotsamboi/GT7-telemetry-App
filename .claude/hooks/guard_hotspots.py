import json, os, sys
BLOCK = ("backend/app/telemetry/parser.py", "backend/app/telemetry/bus.py", "backend/app/storage/store.py")
WARN = ("backend/app/runtime.py", "backend/app/api.py", "backend/app/group/service.py", "frontend/src/main.tsx")
try:
    path = (json.load(sys.stdin).get("tool_input") or {}).get("file_path", "").replace("\\", "/")
except Exception:
    sys.exit(0)
if any(path.endswith(b) for b in BLOCK) and os.environ.get("GT7_ALLOW_HOTSPOT") != "1":
    print(f"BLOCKED hotspot {path}: telemetry receive/parse/record path. Set GT7_ALLOW_HOTSPOT=1 and benchmark (scripts/bench_ingest.py).", file=sys.stderr)
    sys.exit(2)
if any(path.endswith(w) for w in WARN):
    print(f"hotspot {path}: keep the edit minimal; put logic in a new module.", file=sys.stderr)
sys.exit(0)
