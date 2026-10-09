from collections.abc import Iterator

import pytest
from gradio_client import Client

from app import build_demo
from src.config import Settings, load_settings
from src.services.access import ADMIN_USER, WORKSHOP_USER, build_auth, is_admin, password_problems
from src.services.flags import RuntimeFlags
from src.services.limits import LimitService

WORKSHOP_PW = "workshop-password-1234567"
ADMIN_PW = "admin-password-abcdefghij"
GOOD = {"WORKSHOP_PASSWORD": WORKSHOP_PW, "ADMIN_PASSWORD": ADMIN_PW}


def test_password_rules_never_echo_the_values():
    problems = password_problems({"WORKSHOP_PASSWORD": "short", "ADMIN_PASSWORD": "short"})
    assert len(problems) == 3 and "short" not in " ".join(problems).replace("must be", "")
    assert password_problems(GOOD) == []
    same = {"WORKSHOP_PASSWORD": WORKSHOP_PW, "ADMIN_PASSWORD": WORKSHOP_PW}
    assert any("differ" in p for p in password_problems(same))


def test_build_auth_returns_both_users():
    auth = build_auth(GOOD, enabled=True, development_mode=False)
    assert auth == [(WORKSHOP_USER, WORKSHOP_PW), (ADMIN_USER, ADMIN_PW)]


def test_build_auth_is_off_when_disabled_or_in_dev_mode_without_passwords():
    assert build_auth(GOOD, enabled=False, development_mode=False) is None
    assert build_auth({}, enabled=True, development_mode=True) is None
    assert build_auth(GOOD, enabled=True, development_mode=True) is not None


def test_build_auth_fails_without_passwords_outside_dev_mode():
    with pytest.raises(RuntimeError) as info:
        build_auth({"WORKSHOP_PASSWORD": WORKSHOP_PW}, enabled=True, development_mode=False)
    assert WORKSHOP_PW not in str(info.value)


def test_only_the_admin_user_is_admin():
    assert is_admin("admin")
    assert not is_admin("workshop") and not is_admin(None) and not is_admin("Admin")


def test_startup_stops_on_weak_or_missing_passwords(make_settings):
    settings = make_settings()
    env = dict.fromkeys(settings.required_secrets(), "x")
    problems = settings.startup_problems(env)
    assert any("at least 10" in p for p in problems)
    assert not any("Missing secret: WORKSHOP_PASSWORD" in p for p in problems)
    assert any("Missing secret: ADMIN_PASSWORD" in p for p in settings.startup_problems({"X": "y"}))


def test_real_keys_never_run_without_login_or_with_the_api_exposed(make_settings):
    def open_app(app):
        app["access"]["enabled"] = False
        app["access"]["expose_api"] = True

    settings = make_settings(app=open_app)
    problems = settings.startup_problems(dict.fromkeys(settings.required_secrets(), "x" * 24))
    assert any("no login" in p for p in problems)
    assert any("expose_api" in p for p in problems)


def test_dev_mode_with_passwords_is_allowed_on_a_space_but_one_alone_is_not():
    settings = load_settings(env={"DEVELOPMENT_MODE": "true"})
    assert settings.startup_problems({"SPACE_ID": "me/space", **GOOD}) == []
    lone = settings.startup_problems({"WORKSHOP_PASSWORD": WORKSHOP_PW})
    assert lone and "both" in lone[0]


def test_default_build_exposes_no_endpoints_to_api_clients(dev_settings: Settings, fake_providers):
    demo = build_demo(dev_settings, fake_providers)
    functions = [d for d in demo.get_config_file()["dependencies"] if d.get("targets")]
    assert functions
    assert all(d["api_visibility"] == "private" for d in functions if d.get("api_name"))


@pytest.fixture
def secured(dev_settings: Settings, fake_providers) -> Iterator[tuple[str, LimitService]]:
    dev_settings.config.access.expose_api = True
    limits = LimitService(dev_settings.config.limits)
    demo = build_demo(dev_settings, fake_providers, limits)
    demo.launch(
        prevent_thread_lock=True,
        quiet=True,
        auth=build_auth(GOOD, enabled=True, development_mode=True),
    )
    try:
        yield demo.local_url, limits
    finally:
        demo.close()


def test_login_is_required(secured):
    url, _ = secured
    with pytest.raises(Exception):  # noqa: B017 - the client raises on a failed login
        Client(url, verbose=False).predict(api_name="/touch")
    Client(url, auth=(WORKSHOP_USER, WORKSHOP_PW), verbose=False).predict(api_name="/touch")


def test_wrong_password_is_rejected(secured):
    url, _ = secured
    with pytest.raises(Exception):  # noqa: B017
        Client(url, auth=(WORKSHOP_USER, "wrong-password-value-000"), verbose=False)


def test_pause_works_for_admin_only(secured):
    url, limits = secured
    visitor = Client(url, auth=(WORKSHOP_USER, WORKSHOP_PW), verbose=False)
    admin = Client(url, auth=(ADMIN_USER, ADMIN_PW), verbose=False)

    visitor.predict(True, api_name="/on_pause")
    assert limits.paused is False

    admin.predict(True, api_name="/on_pause")
    assert limits.paused is True
    admin.predict(False, api_name="/on_pause")
    assert limits.paused is False


def test_the_admin_tab_works_with_only_the_quality_switch(dev_settings: Settings, fake_providers):
    dev_settings.config.access.expose_api = True
    dev_settings.config.features.photo_studio = False  # so the quality box is the only extra one
    demo = build_demo(dev_settings, fake_providers, flags=RuntimeFlags(high_quality=True))
    demo.launch(
        prevent_thread_lock=True,
        quiet=True,
        auth=build_auth(GOOD, enabled=True, development_mode=True),
    )
    try:
        admin = Client(demo.local_url, auth=(ADMIN_USER, ADMIN_PW), verbose=False)
        summary, paused, quality = admin.predict(api_name="/on_refresh")
        assert quality is True and paused is False and "Bilder:" in summary
    finally:
        demo.close()


def test_the_quality_switch_works_for_admin_only(dev_settings: Settings, fake_providers):
    dev_settings.config.access.expose_api = True
    flags = RuntimeFlags()
    demo = build_demo(dev_settings, fake_providers, flags=flags)
    demo.launch(
        prevent_thread_lock=True,
        quiet=True,
        auth=build_auth(GOOD, enabled=True, development_mode=True),
    )
    try:
        visitor = Client(demo.local_url, auth=(WORKSHOP_USER, WORKSHOP_PW), verbose=False)
        admin = Client(demo.local_url, auth=(ADMIN_USER, ADMIN_PW), verbose=False)
        visitor.predict(True, api_name="/on_quality")
        assert flags.high_quality is False
        admin.predict(True, api_name="/on_quality")
        assert flags.high_quality is True
    finally:
        demo.close()


def test_reset_counters_works_for_admin_only(secured):
    url, limits = secured
    limits.reserve(count=1, est_cost=0.01, device="a")
    Client(url, auth=(WORKSHOP_USER, WORKSHOP_PW), verbose=False).predict(
        api_name="/on_confirm_reset"
    )
    assert limits.snapshot().images_used == 1
    Client(url, auth=(ADMIN_USER, ADMIN_PW), verbose=False).predict(api_name="/on_confirm_reset")
    assert limits.snapshot().images_used == 0


def test_admin_status_is_not_rendered_for_a_visitor(secured):
    url, limits = secured
    limits.reserve(count=1, est_cost=0.01, device="a")
    visitor = Client(url, auth=(WORKSHOP_USER, WORKSHOP_PW), verbose=False)
    admin = Client(url, auth=(ADMIN_USER, ADMIN_PW), verbose=False)
    assert "Bilder: 1 av" in admin.predict(api_name="/on_refresh")[0]
    assert visitor.predict(api_name="/on_refresh")[0] != admin.predict(api_name="/on_refresh")[0]
