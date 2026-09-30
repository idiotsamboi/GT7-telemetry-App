---
paths:
  - "backend/**/*.py"
---
# backend
- core/ imports nothing from the app; tests/test_architecture.py enforces layering. Services raise AppError, not HTTPException.
- Commands go through core.commands.dispatch; new command => commands_catalog.py + module ownership in modules.py.
