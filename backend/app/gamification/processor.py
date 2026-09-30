"""Bounded lifecycle consumer. Never reads SQLite or evaluates rewards in the receiver.

Only sessions attributed while this processor is running are eligible for recovery.
It does not retroactively reward legacy recordings or manual metadata edits.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

from ..storage.repositories import SqliteSessionRepository
from .events import emit_for_scorecard

log = logging.getLogger('gamification')


@dataclass(frozen=True, slots=True)
class CareerJob:
    kind: str
    session_id: str
    driver_id: str | None
    payload: dict


class CareerProcessor:
    def __init__(self, runtime, repository, capacity: int = 128):
        self.runtime = runtime
        self.repository = repository
        self.sessions = SqliteSessionRepository(runtime.store)
        self.queue: asyncio.Queue[CareerJob] = asyncio.Queue(maxsize=capacity)
        self.task: asyncio.Task | None = None
        self.active_driver_id: str | None = None
        self.accepting = False
        self.last_run: float | None = None
        self.last_duration_ms: float | None = None
        self.failed_events = 0
        self.dropped_events = 0
        self.processed_events = 0
        self.last_error: str | None = None
        self._lap_identity: tuple | None = None
        self._identity_changed = False
        self._session_integrity = True
        self._session_driver: str | None = None

    def _identity(self) -> tuple:
        r = self.runtime
        track = r.track
        sample = r.sessions.latest
        car_id = sample.values.get('car_id') if sample is not None else r.sessions.meta.get('car_id')
        known = r.feature('v3_track_authority') and track.locked is not None
        return (track.locked_layout_id if known else None, car_id,
                getattr(r.sessions, 'provenance', None), 'locked' if known else 'unknown')

    def on_event(self, event) -> None:
        """O(1), no I/O, no reward computation; catches errors before the telemetry fault boundary."""
        try:
            if not self.accepting:
                return
            enabled = self.runtime.feature('gamification') and self.runtime.feature('driver_progression')
            if event.kind in ('track_locked', 'track_unlocked'):
                self._identity_changed = True
                return
            sid = event.data.get('session_id')
            if not sid:
                return
            if event.kind == 'session_started':
                self._lap_identity = self._identity()
                self._identity_changed = False
                self._session_integrity = enabled
                self._session_driver = self.active_driver_id
                payload = {'provenance': event.data.get('provenance', 'unknown'), 'integrity': enabled}
            elif event.kind == 'lap_completed':
                current = self._identity()
                layout_id, car_id, provenance, state = current
                stable = not self._identity_changed and current == self._lap_identity
                payload = {'lap_id': event.data['lap']['id'], 'context': {
                    'layout_id': layout_id, 'car_id': car_id, 'provenance': provenance,
                    'identity_state': state if stable else 'ambiguous',
                    'integrity': self._session_integrity and enabled,
                    'source': 'calculated', 'identity_source': 'v3_track_service',
                }}
                self._lap_identity = current
                self._identity_changed = False
            elif event.kind == 'session_ended':
                payload = {'integrity': self._session_integrity and enabled,
                           'features': {key: self.runtime.feature(key) for key in ('track_mastery', 'corner_mastery', 'dynamic_challenges', 'engineer_missions')}}
            elif event.kind == 'spatial_analysis_completed':
                payload = event.data['spatial']
            else:
                return
            if not enabled:
                self._session_integrity = False
            self.queue.put_nowait(CareerJob(event.kind, sid, self._session_driver, payload))
        except asyncio.QueueFull:
            self.dropped_events += 1
            self._session_integrity = False
            self.last_error = 'Career queue full; progression requires complete evidence'
        except Exception as error:
            self.failed_events += 1
            self._session_integrity = False
            self._error(error)

    def _error(self, error: Exception) -> None:
        self.last_error = str(error)[:200]
        log.warning('gamification.processing_pending', extra={
            'event': 'gamification.processing_pending',
            'details': {'error_type': type(error).__name__},
        })

    async def start(self) -> None:
        try:
            profile = await asyncio.to_thread(self.repository.ensure_default_profile)
            active = await asyncio.to_thread(self.repository.active_profile)
            self.active_driver_id = (active or profile)['id']
            self.accepting = True
            self.task = asyncio.create_task(self.run(), name='driver-career')
        except Exception as error:
            self.failed_events += 1
            self._error(error)

    def _process_session(self, sid: str, driver_id: str, integrity: bool = True) -> None:
        # The barrier is off the event loop. A missing final session remains pending.
        self.runtime.store.flush()
        detail = self.sessions.get(sid)
        if detail is None or detail.ended is None:
            raise RuntimeError('Final session evidence is not committed')
        context = self.repository.session_context(sid)
        context['integrity'] = context.get('integrity') is True and integrity
        context['features'] = {key: context.get('features', {}).get(key, True) and self.runtime.feature(key) for key in ('track_mastery', 'corner_mastery', 'dynamic_challenges', 'engineer_missions')}
        if not context['features']['corner_mastery']:
            context['spatial'] = {}
        scorecard = self.repository.process_session(detail.to_public(), driver_id, context)
        try:  # post-commit, idempotent, non-fatal
            emit_for_scorecard(self.runtime.store, scorecard, self.repository.curve)
        except Exception as error:
            self._error(error)

    def _handle(self, job: CareerJob) -> None:
        if job.driver_id is None:
            return
        if job.kind == 'session_started':
            self.repository.bind_session(job.session_id, job.driver_id, job.payload['provenance'], require_finalization=True)
            if not job.payload['integrity']:
                self.repository.invalidate_session(job.session_id, 'career_disabled_at_start')
        elif job.kind == 'lap_completed':
            self.repository.record_lap_context(job.session_id, job.payload['lap_id'], job.payload['context'])
        elif job.kind == 'spatial_analysis_completed':
            self.repository.record_spatial_context(job.session_id, job.payload)
        elif job.kind == 'session_ended':
            self.repository.finalize_context(job.session_id, job.payload)
            self._process_session(job.session_id, job.driver_id, job.payload['integrity'])

    def _recover(self) -> None:
        if not (self.runtime.feature('gamification') and self.runtime.feature('driver_progression')):
            return
        self.runtime.store.flush()
        for row in self.repository.pending_sessions():
            # A finalization event may already be queued while this off-thread
            # reconciliation runs. Never permanently exclude it ahead of its receipt.
            # A receipt lost in a crash stays pending and cannot earn rewards.
            if row.get('invalid_reason') == 'awaiting_finalization':
                continue
            try:
                self._process_session(row['session_id'], row['driver_id'])
            except Exception as error:
                self.failed_events += 1
                self._error(error)

    async def run(self) -> None:
        # Recovery only uses durable bindings and lap identity evidence, never guessed context.
        async def recover():
            try:
                await asyncio.to_thread(self._recover)
            except Exception as error:
                self.failed_events += 1
                self._error(error)
        await recover()
        while True:
            try:
                job = await asyncio.wait_for(self.queue.get(), timeout=30)
            except asyncio.TimeoutError:
                await recover()
                continue
            started = time.perf_counter()
            try:
                if job.kind == 'stop':
                    break
                await asyncio.to_thread(self._handle, job)
                self.processed_events += 1
            except Exception as error:
                self.failed_events += 1
                self._error(error)
            finally:
                self.last_run = time.time()
                self.last_duration_ms = (time.perf_counter() - started) * 1000
                self.queue.task_done()

    async def close(self) -> None:
        self.accepting = False
        if self.task is not None:
            # Do not cancel an in-flight to_thread transaction and then close its database.
            await self.queue.put(CareerJob('stop', '', None, {}))
            await asyncio.gather(self.task, return_exceptions=True)
            self.task = None

    def health(self) -> dict:
        return {'running': self.task is not None and not self.task.done(),
                'pending_events': self.queue.qsize(), 'capacity': self.queue.maxsize,
                'failed_events': self.failed_events, 'dropped_events': self.dropped_events,
                'processed_events': self.processed_events, 'last_processor_run': self.last_run,
                'last_evaluation_ms': self.last_duration_ms, 'last_error': self.last_error}
