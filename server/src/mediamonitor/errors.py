"""Ошибки API в форме контракта `ApiError` ({code, message, retryAfterSec?}).

Сбои площадок — не ошибки API: они внутри статусов площадок (ТЗ-Ф42).
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from mediamonitor.contract import ApiError, ApiErrorCode

log = logging.getLogger(__name__)

HTTP_STATUS: dict[ApiErrorCode, int] = {
    "invalid": 422,
    "too-long": 422,
    "not-found": 404,
    "too-many-requests": 429,
    "server": 500,
    "offline": 503,
}


class ApiProblem(Exception):  # noqa: N818 — это не сбой кода, а ответ пользователю
    """Ответ с ошибкой контракта. Сообщение — простым языком, для человека."""

    def __init__(
        self, code: ApiErrorCode, message: str, *, retry_after_sec: int | None = None
    ) -> None:
        super().__init__(message)
        self.code: ApiErrorCode = code
        self.message = message
        self.retry_after_sec = retry_after_sec

    def to_contract(self) -> ApiError:
        return ApiError(code=self.code, message=self.message, retry_after_sec=self.retry_after_sec)


def required[T](value: T | None, what: str) -> T:
    """Проверка инварианта вместо assert: в проде assert можно отключить флагом -O."""
    if value is None:
        raise RuntimeError(f"Нарушен инвариант: нет значения «{what}»")
    return value


def not_found(message: str) -> ApiProblem:
    return ApiProblem("not-found", message)


def invalid(message: str) -> ApiProblem:
    return ApiProblem("invalid", message)


def problem_response(problem: ApiProblem) -> JSONResponse:
    headers = {}
    if problem.retry_after_sec is not None:
        headers["Retry-After"] = str(problem.retry_after_sec)
    return JSONResponse(
        status_code=HTTP_STATUS[problem.code],
        content=problem.to_contract().dump(),
        headers=headers,
    )


def _field_path(loc: tuple[int | str, ...]) -> str:
    parts = [str(p) for p in loc if p not in {"body", "query", "path", "header"}]
    return ".".join(parts) or "запрос"


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiProblem)
    async def _api_problem(_: Request, exc: ApiProblem) -> JSONResponse:
        return problem_response(exc)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = exc.errors()
        where = _field_path(tuple(errors[0]["loc"])) if errors else "запрос"
        return problem_response(
            ApiProblem("invalid", f"Данные запроса не прошли проверку: поле «{where}».")
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        if exc.status_code == 404:
            return problem_response(ApiProblem("not-found", "Такого адреса в API нет."))
        if exc.status_code == 405:
            return JSONResponse(
                status_code=405,
                content=ApiError(
                    code="invalid", message="Этот метод здесь не поддерживается."
                ).dump(),
            )
        return JSONResponse(
            status_code=exc.status_code,
            content=ApiError(code="server", message="Запрос не выполнен.").dump(),
        )

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, exc: Exception) -> JSONResponse:
        log.exception("Необработанная ошибка: %s", type(exc).__name__)
        return problem_response(
            ApiProblem("server", "На сервере что-то пошло не так. Повторите через минуту.")
        )
