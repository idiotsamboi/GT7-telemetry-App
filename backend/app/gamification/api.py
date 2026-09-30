"""Paired local HTTP adapter; evidence/reward events are never accepted from clients."""
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from starlette.concurrency import run_in_threadpool


class ProfileCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    display_name: str = Field(min_length=1, max_length=80)


class CareerSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    enabled: StrictBool


class CareerReset(BaseModel):
    model_config = ConfigDict(extra='forbid')
    confirmation: str
    driver_id: str | None = None


class EngineerFocus(BaseModel):
    model_config = ConfigDict(extra='forbid')
    focus: Literal['pace', 'consistency', 'braking', 'cornering', 'fuel', 'strategy', 'track_learning']


class CareerImport(BaseModel):
    model_config = ConfigDict(extra='forbid')
    bundle: dict


def repository(request: Request):
    return request.app.state.runtime.career_repository


def invoke(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    except (TimeoutError, RuntimeError) as error:
        raise HTTPException(503, 'Driver Career is pending; recording remains available') from error


def router() -> APIRouter:
    api = APIRouter(prefix='/api/gamification', tags=['Driver Career'])

    @api.get('/profiles')
    def profiles(repo=Depends(repository)):
        return invoke(repo.list_profiles)

    @api.post('/profiles')
    def create_profile(body: ProfileCreate, repo=Depends(repository)):
        return invoke(repo.create_profile, body.display_name)

    @api.post('/profiles/{driver_id}/select')
    async def select_profile(driver_id: str, request: Request, repo=Depends(repository)):
        profile = await run_in_threadpool(invoke, repo.select_profile, driver_id)
        # This changes only future sessions; an active session retains its binding.
        request.app.state.runtime.career.active_driver_id = profile['id']
        return profile

    @api.get('/profile')
    def profile(repo=Depends(repository)):
        return invoke(repo.active_profile)

    @api.get('/dashboard')
    def dashboard(driver_id: str | None = None, repo=Depends(repository)):
        return invoke(repo.dashboard, driver_id)

    @api.get('/skills')
    def skills(driver_id: str | None = None, repo=Depends(repository)):
        return invoke(repo.skills, driver_id)

    @api.get('/xp')
    def xp(driver_id: str | None = None, repo=Depends(repository)):
        return invoke(repo.dashboard, driver_id)['level']

    @api.get('/xp/history')
    def xp_history(driver_id: str | None = None, limit: int = Query(50, ge=1, le=200), repo=Depends(repository)):
        return invoke(repo.history, driver_id, limit)

    @api.get('/titles')
    def titles(driver_id: str | None = None, repo=Depends(repository)):
        return invoke(repo.titles, driver_id)

    @api.post('/titles/equip')
    def equip_title(title_name: str, driver_id: str | None = None, repo=Depends(repository)):
        return invoke(repo.equip_title, title_name, driver_id)

    @api.get('/badges')
    def badges(driver_id: str | None = None, repo=Depends(repository)):
        return invoke(repo.badges, driver_id)

    @api.get('/achievements')
    def achievements(driver_id: str | None = None, repo=Depends(repository)):
        return invoke(repo.achievements, driver_id)

    @api.get('/tracks')
    def tracks(driver_id: str | None = None, repo=Depends(repository)):
        return invoke(repo.tracks, driver_id)

    @api.get('/tracks/{track_id}')
    def track(track_id: str, driver_id: str | None = None, repo=Depends(repository)):
        return [item for item in invoke(repo.tracks, driver_id) if item['layout_id'] == track_id]

    @api.get('/corners/{track_id}')
    def corners(track_id: str, driver_id: str | None = None, repo=Depends(repository)):
        return invoke(repo.corners, track_id, driver_id)

    @api.get('/challenges')
    def challenges(driver_id: str | None = None, repo=Depends(repository)):
        return invoke(repo.challenges, driver_id)

    @api.post('/challenges/{challenge_id}/accept')
    def accept_challenge(challenge_id: str, repo=Depends(repository)):
        return invoke(repo.challenge_action, challenge_id, 'accept')

    @api.post('/challenges/{challenge_id}/skip')
    def skip_challenge(challenge_id: str, repo=Depends(repository)):
        return invoke(repo.challenge_action, challenge_id, 'skip')

    @api.get('/settings')
    def settings(repo=Depends(repository)):
        return invoke(repo.settings)

    @api.get('/engineer')
    def engineer(request: Request):
        return invoke(request.app.state.runtime.engineer.career_brief)

    @api.get('/career')
    def career(repo=Depends(repository)):
        return invoke(repo.career)

    @api.get('/streaks')
    def streaks(repo=Depends(repository)):
        return invoke(repo.streaks)

    @api.get('/missions')
    def missions(repo=Depends(repository)):
        return invoke(repo.engineer)['missions']

    @api.post('/missions/{challenge_id}/accept')
    def accept_mission(challenge_id: str, request: Request, repo=Depends(repository)):
        if not request.app.state.runtime.feature('engineer_missions'):
            raise HTTPException(409, 'Engineer missions are disabled')
        return invoke(repo.start_mission, challenge_id)

    @api.put('/engineer/focus')
    def focus(body: EngineerFocus, repo=Depends(repository)):
        return invoke(repo.set_focus, body.focus)

    @api.delete('/engineer/memory')
    def clear_memory(repo=Depends(repository)):
        return invoke(repo.clear_memory)

    @api.put('/settings')
    def update_settings(body: CareerSettingsUpdate, repo=Depends(repository)):
        return invoke(repo.update_settings, body.model_dump())

    @api.get('/diagnostics')
    def diagnostics(request: Request, repo=Depends(repository)):
        return {'processor': request.app.state.runtime.career.health(), 'repository': invoke(repo.diagnostics)}

    @api.get('/export')
    def export(driver_id: str | None = None, repo=Depends(repository)):
        return invoke(repo.export, driver_id)

    @api.post('/import')
    def import_bundle(body: CareerImport, request: Request, repo=Depends(repository)):
        if request.app.state.runtime.sessions.id is not None:
            raise HTTPException(409, 'Finish the recording before importing a career archive')
        return invoke(repo.import_bundle, body.bundle)

    @api.post('/reset')
    def reset(body: CareerReset, repo=Depends(repository)):
        driver_id = body.driver_id or invoke(repo.active_profile)['id']
        return invoke(repo.reset, driver_id, body.confirmation)

    return api
