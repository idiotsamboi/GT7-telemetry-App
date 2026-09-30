---
paths:
  - "tests/**"
  - "**/*.test.*"
---
# testing
- Order: changed-file tests -> feature tests -> subsystem -> typecheck/arch -> full suite only at phase gates.
- Pytest needs --basetemp (pyproject sets .pytest_tmp). Filter output with tail/grep.
