"""Dependency-direction and hygiene rules (docs/architecture). Parses imports with ast; no imports executed."""
import ast
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / 'backend' / 'app'
ADAPTERS = {'api.py', 'group/admin.py', 'group/public.py', 'gamification/api.py', 'obs_api.py', 'assets_api.py'}   # HTTP adapters only
# Modules under core/ may import only stdlib + pydantic + other core modules.
LAYER_ALLOWED = {
    'core': {'core'},
    'telemetry': {'core', 'telemetry'},
    'domain': {'core', 'domain'},
    'storage': {'core', 'storage', 'domain', 'telemetry'},   # samples are telemetry; units live below storage
}
# Known upward edges that predate the layering (tracked in docs/architecture/TECH_DEBT.md). Shrink, never grow.
LAYER_EXCEPTIONS: dict[str, set[str]] = {
    'domain/insights.py': {'analytics', 'spatial_coaching'},          # adapters over existing analysis output
    'storage/repositories.py': {'analytics'},                          # extrema-preserving downsample reuse
    'storage/exports.py': {'exporting'},
}
# asyncio.Queue / deque without a bound need a justification here.
UNBOUNDED_ALLOWLIST: dict[str, str] = {
    'group/history.py': 'time-window pruned (180 s of 2 Hz ticks); see TECH_DEBT',
    'tyre_heat.py': 'rolling windows pruned by time; see TECH_DEBT',
}
PLATFORM_ALLOWLIST = {'core/platform.py'}
# Pre-existing direct checks, tracked in docs/architecture/TECH_DEBT.md; the list may only shrink.
PLATFORM_DEBT: set[str] = set()


def modules():
    for path in sorted(APP.rglob('*.py')):
        if '__pycache__' in path.parts:
            continue
        yield path, path.relative_to(APP).as_posix()


def imports(path: Path, rel: str):
    """Yield (kind, dotted-name) for each import; relative imports resolved to backend.app.*"""
    tree = ast.parse(path.read_text(encoding='utf-8'))
    package = ['backend', 'app', *rel.split('/')[:-1]]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package[:len(package) - (node.level - 1)]
                name = '.'.join(base + ([node.module] if node.module else []))
                if not node.module:      # from . import x
                    for alias in node.names:
                        yield f'{name}.{alias.name}'
                    continue
                yield name
            elif node.module:
                yield node.module


def app_targets(path: Path, rel: str):
    """Top-level backend.app member (e.g. 'core', 'runtime') each import points at."""
    for name in imports(path, rel):
        if name.startswith('backend.app.'):
            yield name.split('.')[2]
        elif name == 'backend.app':
            yield ''


def test_layering_edges():
    problems = []
    for path, rel in modules():
        layer = rel.split('/')[0] if '/' in rel else None
        if layer not in LAYER_ALLOWED:
            continue
        for target in set(app_targets(path, rel)):
            if target and target not in LAYER_ALLOWED[layer] and target not in LAYER_EXCEPTIONS.get(rel, set()):
                problems.append(f'{rel} -> {target}')
    assert not problems, 'forbidden upward imports:\n' + '\n'.join(problems)


def test_core_imports_no_app_modules_and_no_web_framework():
    for path, rel in modules():
        if not rel.startswith('core/'):
            continue
        for name in imports(path, rel):
            assert not name.startswith('fastapi') and not name.startswith('starlette'), f'{rel} imports {name}'
            if name.startswith('backend.app.'):
                assert name.split('.')[2] == 'core', f'{rel} imports {name}'


def test_only_adapters_import_fastapi():
    offenders = []
    for path, rel in modules():
        if rel in ADAPTERS:
            continue
        for name in imports(path, rel):
            if name.split('.')[0] in ('fastapi', 'starlette'):
                offenders.append(f'{rel}: {name}')
    assert not offenders, offenders


def test_no_import_cycles_among_app_modules():
    graph: dict[str, set[str]] = {}
    known = {rel[:-3].replace('/', '.').removesuffix('.__init__') for _, rel in modules()}
    for path, rel in modules():
        me = rel[:-3].replace('/', '.').removesuffix('.__init__')
        deps = set()
        tree = ast.parse(path.read_text(encoding='utf-8'))
        for node in tree.body:     # module-level imports only: function-level (lazy) imports are the sanctioned cycle breakers
            for name in _top_level_names(node, rel):
                cand = name.removeprefix('backend.app.')
                while cand and cand not in known:
                    cand = cand.rpartition('.')[0]
                if cand and cand != me and name.startswith('backend.app'):
                    deps.add(cand)
        graph[me] = deps
    # collapse package __init__ nodes: importing a package == importing its __init__
    cycle = _find_cycle(graph)
    assert cycle is None, 'import cycle: ' + ' -> '.join(cycle)


def _top_level_names(node, rel):
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        package = ['backend', 'app', *rel.split('/')[:-1]]
        if isinstance(node, ast.Import):
            return [a.name for a in node.names]
        if node.level:
            base = package[:len(package) - (node.level - 1)]
            name = '.'.join(base + ([node.module] if node.module else []))
            if not node.module:
                return [f'{name}.{a.name}' for a in node.names]
            return [name]
        return [node.module] if node.module else []
    if isinstance(node, (ast.If, ast.Try)):
        out = []
        for child in ast.iter_child_nodes(node):
            out += _top_level_names(child, rel)
        return out
    return []


def _find_cycle(graph):
    WHITE, GREY, BLACK = 0, 1, 2
    color = {n: WHITE for n in graph}
    stack: list[str] = []

    def dfs(n):
        color[n] = GREY
        stack.append(n)
        for m in graph.get(n, ()):
            if m not in color:
                continue
            if color[m] == GREY:
                return stack[stack.index(m):] + [m]
            if color[m] == WHITE:
                found = dfs(m)
                if found:
                    return found
        stack.pop()
        color[n] = BLACK
        return None

    for n in graph:
        if color[n] == WHITE:
            found = dfs(n)
            if found:
                return found
    return None


def test_every_queue_and_deque_is_bounded():
    offenders = []
    for path, rel in modules():
        if rel in UNBOUNDED_ALLOWLIST:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = fn.attr if isinstance(fn, ast.Attribute) else fn.id if isinstance(fn, ast.Name) else ''
            if name == 'deque':
                bounded = len(node.args) >= 2 or any(k.arg == 'maxlen' for k in node.keywords)
                # deque(maxlen=None) is unbounded too
                for k in node.keywords:
                    if k.arg == 'maxlen' and isinstance(k.value, ast.Constant) and k.value.value is None:
                        bounded = False
                if not bounded:
                    offenders.append(f'{rel}:{node.lineno} deque without maxlen')
            elif name in ('Queue', 'PriorityQueue', 'LifoQueue') and (isinstance(fn, ast.Attribute) and getattr(fn.value, 'id', '') in ('asyncio', 'queue') or name != 'Queue'):
                bounded = bool(node.args) or any(k.arg == 'maxsize' for k in node.keywords)
                if not bounded:
                    offenders.append(f'{rel}:{node.lineno} {name} without maxsize')
    assert not offenders, 'unbounded buffers (bound them or allowlist with a reason):\n' + '\n'.join(offenders)


def test_platform_checks_only_in_platform_adapter():
    launchers_ok = set()
    offenders = []
    for path, rel in modules():
        if rel in PLATFORM_ALLOWLIST or rel in launchers_ok:
            continue
        src = path.read_text(encoding='utf-8')
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                if (node.value.id, node.attr) in (('sys', 'platform'), ('os', 'name')):
                    offenders.append(f'{rel}:{node.lineno} {node.value.id}.{node.attr}')
    assert not offenders or set(offenders) <= PLATFORM_DEBT, (
        'platform checks outside core/platform.py:\n' + '\n'.join(sorted(set(offenders) - PLATFORM_DEBT)))
