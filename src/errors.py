"""Typed errors. Each maps to a locale key; raw details never reach visitors (spec section 15)."""

from __future__ import annotations


class AppError(Exception):
    code = "unexpected"
    message_key = "error.generic"


class EmptyInputError(AppError):
    code = "empty_input"
    message_key = "error.empty"


class TooLongInputError(AppError):
    code = "too_long"
    message_key = "error.too_long"


class ProviderTimeoutError(AppError):
    code = "timeout"
    message_key = "error.timeout"


class RateLimitedError(AppError):
    code = "rate_limited"
    message_key = "error.busy"


class CooldownError(AppError):
    code = "cooldown"
    message_key = "error.cooldown"


class BudgetReachedError(AppError):
    code = "budget_reached"
    message_key = "error.budget"


class PausedError(AppError):
    code = "paused"
    message_key = "error.paused"


class SafetyRefusalError(AppError):
    message_key = "error.safety"

    def __init__(self, code: str = "refused", rewrite: str | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.rewrite = rewrite


class CheckFailedError(AppError):
    """A safety check could not run. Generation stops (fail closed)."""

    code = "check_failed"
    message_key = "error.generic"


def error_code(exc: BaseException) -> str:
    return exc.code if isinstance(exc, AppError) else AppError.code


def error_message_key(exc: BaseException) -> str:
    return exc.message_key if isinstance(exc, AppError) else AppError.message_key
