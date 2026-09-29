from src.services.prompts import compose_prompt, style_fragment


def test_compose_appends_style_and_translation():
    assert compose_prompt("en katt", "oil painting", "a cat") == "en katt, oil painting, a cat"


def test_compose_without_extras_returns_visible_text():
    assert compose_prompt("a cat") == "a cat"


def test_compose_is_deterministic():
    assert compose_prompt("a cat.", "retro") == compose_prompt("a cat.", "retro")


def test_compose_skips_empty_parts_and_trailing_punctuation():
    assert compose_prompt("a cat.", None, "") == "a cat"
    assert compose_prompt("a cat,", "  retro  ") == "a cat, retro"


def test_compose_does_not_touch_the_caller_text():
    text = "En katt."
    compose_prompt(text, "retro")
    assert text == "En katt."


def test_style_fragment_lookup():
    fragments = {"retro": "retro poster"}
    assert style_fragment(fragments, "retro") == "retro poster"
    assert style_fragment(fragments, None) is None
    assert style_fragment(fragments, "unknown") is None
