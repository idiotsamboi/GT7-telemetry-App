import pathlib
p = pathlib.Path(".agent-state/current-state.md")
if p.exists():
    print("\n".join(p.read_text(encoding="utf-8").splitlines()[:80]))
