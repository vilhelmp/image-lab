"""Login users and the admin check (spec section 11). Password values are never logged."""

from __future__ import annotations

from collections.abc import Mapping

WORKSHOP_USER = "workshop"
ADMIN_USER = "admin"
WORKSHOP_ENV = "WORKSHOP_PASSWORD"
ADMIN_ENV = "ADMIN_PASSWORD"
MIN_PASSWORD_CHARS = 10  # for a short supervised event; raise it for anything longer-lived

_USERS = ((WORKSHOP_USER, WORKSHOP_ENV), (ADMIN_USER, ADMIN_ENV))


def password_problems(env: Mapping[str, str]) -> list[str]:
    """Reasons the passwords that are set cannot be used. Missing ones are reported elsewhere."""
    values = {name: env.get(name, "") for _, name in _USERS}
    problems = [
        f"{name} must be at least {MIN_PASSWORD_CHARS} characters"
        for name, value in values.items()
        if value and len(value) < MIN_PASSWORD_CHARS
    ]
    if values[WORKSHOP_ENV] and values[WORKSHOP_ENV] == values[ADMIN_ENV]:
        problems.append(f"{WORKSHOP_ENV} and {ADMIN_ENV} must differ")
    return problems


def build_auth(
    env: Mapping[str, str], *, enabled: bool, development_mode: bool
) -> list[tuple[str, str]] | None:
    """Credentials for Gradio auth, or None for an open app.

    Development mode runs open unless both passwords are set, so login can be tried with fakes.
    """
    if not enabled:
        return None
    credentials = [(user, env.get(name, "")) for user, name in _USERS]
    if all(password for _, password in credentials):
        return credentials
    if development_mode:
        return None
    raise RuntimeError("Access is enabled but a password secret is missing.")


def is_admin(username: str | None) -> bool:
    return username == ADMIN_USER
