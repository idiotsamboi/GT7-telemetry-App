"""HTTP adapter for the local OBS overlays (domain logic lives in obs.py).

`/obs-api/frame` and the `/obs` page are tokenless and read-only on purpose: an OBS browser source cannot
pair. Everything that changes configuration is under `/api/obs` and needs the paired browser."""
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import ValidationError

from .core.errors import AppError
from .obs import ObsConfig, frame_payload, invalidate, overview, store_for

ROOT = Path(__file__).resolve().parents[2]


def router():
    r = APIRouter()

    def base_url(request: Request) -> str:
        return f"http://{request.headers.get('host') or '127.0.0.1'}"

    def failed(error: AppError) -> JSONResponse:
        return JSONResponse({'detail': error.detail}, error.status_code)

    @r.get('/obs-api/frame')
    def frame(request: Request, graphic: str):
        try:
            return JSONResponse(frame_payload(request.app.state.runtime, graphic), headers={'Cache-Control': 'no-store'})
        except AppError as error:
            return failed(error)

    @r.get('/obs')
    @r.get('/obs/{graphic}')
    def shell(graphic: str = ''):
        return FileResponse(ROOT / 'frontend' / 'dist' / 'index.html')

    @r.get('/api/obs')
    def state(request: Request):
        return overview(request.app.state.runtime, base_url(request))

    @r.put('/api/obs/config')
    async def save(request: Request):
        runtime = request.app.state.runtime
        try:
            config = ObsConfig.model_validate(await request.json())
            store_for(runtime).save(config)
        except ValidationError as error:
            return JSONResponse({'detail': 'Invalid overlay settings: ' + str(error)[:300]}, 422)
        except ValueError:
            return JSONResponse({'detail': 'Invalid JSON'}, 422)
        except AppError as error:
            return failed(error)
        invalidate()
        return overview(runtime, base_url(request))

    @r.post('/api/obs/reset')
    def reset(request: Request):
        runtime = request.app.state.runtime
        store_for(runtime).reset()
        invalidate()
        return overview(runtime, base_url(request))

    return r
