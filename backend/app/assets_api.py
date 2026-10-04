"""HTTP adapter: user-chosen image pack folder.

`/cars|brands|tracks/<id>.<ext>` first looks in Settings -> image_pack_dir (`<folder>/cars/2159.png`, `brands/`,
`tracks/`; a car image may also sit directly in the folder; png, webp, jpg or svg), then falls back to the bundled
catalogue image. `/api/pick-folder` opens the OS folder dialog on this PC (the app is
local-first and the browser cannot reveal absolute paths); it needs the paired browser like every /api call."""
import asyncio
import re
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse

ROOT = Path(__file__).resolve().parents[2]
NAME = re.compile(r'^([0-9A-Za-z_-]{1,64})\.(png|webp|jpg|svg)$')
KINDS = ('cars', 'brands', 'tracks')
TYPES = {'.png': 'image/png', '.webp': 'image/webp', '.jpg': 'image/jpeg', '.svg': 'image/svg+xml'}


def _ask_folder(initial: str) -> str:
    import tkinter
    from tkinter import filedialog
    root = tkinter.Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    try:
        return filedialog.askdirectory(title='Choose image pack folder', initialdir=initial or None, mustexist=True) or ''
    finally:
        root.destroy()


def user_image(folder: str, kind: str, stem: str) -> Path | None:
    if not folder:
        return None
    root = Path(folder)
    for base in ([root / kind] + ([root] if kind == 'cars' else [])):
        for ext in TYPES:
            candidate = base / (stem + ext)
            try:
                if candidate.is_file() and candidate.resolve().parent == base.resolve():
                    return candidate
            except OSError:
                continue
    return None


def router():
    r = APIRouter()

    def serve(kind: str, name: str, request: Request):
        match = NAME.match(name)
        if not match:
            return JSONResponse({'detail': 'Not found'}, 404)
        found = user_image(request.app.state.runtime.settings.image_pack_dir, kind, match.group(1))
        if found:
            return FileResponse(found, media_type=TYPES[found.suffix.lower()], headers={'Cache-Control': 'no-cache'})
        bundled = ROOT / 'frontend' / 'dist' / kind / name
        if bundled.is_file():
            return FileResponse(bundled)
        return JSONResponse({'detail': 'Not found'}, 404)

    def handler_for(kind: str):
        def handler(name: str, request: Request):
            return serve(kind, name, request)
        return handler

    for kind in KINDS:
        r.add_api_route('/' + kind + '/{name}', handler_for(kind), methods=['GET'])

    @r.post('/api/pick-folder')
    async def pick_folder(request: Request):
        current = request.app.state.runtime.settings.image_pack_dir
        try:
            path = await asyncio.to_thread(_ask_folder, current)
        except Exception:
            return JSONResponse({'detail': 'No folder dialog is available here. Type the folder path instead.'}, 501)
        return {'path': path}

    return r
