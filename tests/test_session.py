from src.services.session import GeneratedImage, VisitorSession


def _image(name: str = "a") -> GeneratedImage:
    return GeneratedImage(image=b"x", prompt=name, model_key="fast", seconds=1.0)


def test_select_style_toggles():
    session = VisitorSession(lang="sv")
    session.select_style("retro")
    assert session.style == "retro"
    session.select_style("photo")
    assert session.style == "photo"
    session.select_style("photo")
    assert session.style is None


def test_history_keeps_only_the_latest_images():
    session = VisitorSession(lang="sv")
    for i in range(8):
        session.set_current(_image(str(i)), history_size=6)
    assert [h.prompt for h in session.history] == ["2", "3", "4", "5", "6", "7"]
    assert session.current.prompt == "7"


def test_untouched_session_is_never_idle():
    session = VisitorSession(lang="sv", last_interaction=0.0)
    assert not session.is_idle(180, now=10_000)


def test_touched_session_becomes_idle_after_the_limit():
    session = VisitorSession(lang="sv")
    session.touch(now=100.0)
    assert not session.is_idle(180, now=279.9)
    assert session.is_idle(180, now=280.0)


def test_reset_clears_visitor_state_and_sets_language():
    session = VisitorSession(lang="en")
    session.touch(now=1.0)
    session.select_style("retro")
    session.set_current(_image(), history_size=6)
    session.reset("sv", now=5.0)
    assert (session.lang, session.style, session.current, session.history) == ("sv", None, None, [])
    assert not session.dirty and not session.is_idle(1, now=1000.0)
