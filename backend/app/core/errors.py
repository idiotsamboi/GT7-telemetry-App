"""Application errors. Adapters (api.py, group/admin.py, group/public.py) map these to HTTP."""
from enum import StrEnum


class ResultCode(StrEnum):
    """Outcome of a command; also the vocabulary for AppError."""
    OK = 'ok'
    REJECTED = 'rejected'
    NOT_AUTHORIZED = 'not_authorized'
    INVALID_STATE = 'invalid_state'
    INVALID_INPUT = 'invalid_input'
    TIMEOUT = 'timeout'
    CONNECTION_LOST = 'connection_lost'
    RATE_LIMITED = 'rate_limited'
    NOT_FOUND = 'not_found'
    CONFLICT = 'conflict'
    UNAVAILABLE = 'unavailable'


# HTTP status per result code (adapters use this; core itself never imports a web framework).
HTTP_STATUS = {
    ResultCode.OK: 200, ResultCode.REJECTED: 400, ResultCode.NOT_AUTHORIZED: 403,
    ResultCode.INVALID_STATE: 409, ResultCode.INVALID_INPUT: 422, ResultCode.TIMEOUT: 504,
    ResultCode.CONNECTION_LOST: 503, ResultCode.RATE_LIMITED: 429, ResultCode.NOT_FOUND: 404,
    ResultCode.CONFLICT: 409, ResultCode.UNAVAILABLE: 503,
}
_STATUS_TO_CODE = {400: ResultCode.REJECTED, 401: ResultCode.NOT_AUTHORIZED, 403: ResultCode.NOT_AUTHORIZED,
                   404: ResultCode.NOT_FOUND, 409: ResultCode.CONFLICT, 413: ResultCode.INVALID_INPUT,
                   422: ResultCode.INVALID_INPUT, 429: ResultCode.RATE_LIMITED, 503: ResultCode.UNAVAILABLE}


def code_for_status(status: int) -> ResultCode:
    return _STATUS_TO_CODE.get(status, ResultCode.REJECTED if status < 500 else ResultCode.UNAVAILABLE)


class AppError(Exception):
    """Raised by services; carries the HTTP status the adapters answer with.

    `status`/`detail` mirror fastapi.HTTPException so adapters can translate it without
    the service layer importing FastAPI.
    """

    def __init__(self, code: ResultCode | str, status: int, message: str):
        super().__init__(message)
        self.code = ResultCode(code) if not isinstance(code, ResultCode) else code
        self.status_code = status
        self.detail = message

    @classmethod
    def from_status(cls, status: int, message: str) -> 'AppError':
        return cls(code_for_status(status), status, message)

    @classmethod
    def from_code(cls, code: ResultCode, message: str) -> 'AppError':
        return cls(code, HTTP_STATUS[code], message)
