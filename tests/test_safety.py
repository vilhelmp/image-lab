import pytest

from src.errors import EmptyInputError, TooLongInputError
from src.services.safety import validate_input


def test_validate_input_trims_and_collapses_whitespace():
    assert validate_input("  en   katt\n på\ttaket ", 400) == "en katt på taket"


def test_validate_input_strips_control_and_invisible_characters():
    assert validate_input("a\x00b\u202ec\u200bd", 400) == "abcd"


@pytest.mark.parametrize("text", [None, "", "   ", "\n\t", "\u200b"])
def test_validate_input_rejects_empty(text):
    with pytest.raises(EmptyInputError):
        validate_input(text, 400)


def test_validate_input_rejects_absurdly_long_input_before_processing():
    with pytest.raises(TooLongInputError):
        validate_input("x" * 41, 10)


def test_validate_input_normalises_fullwidth_characters():
    assert validate_input("\uff21\uff22\uff23", 400) == "ABC"


def test_validate_input_rejects_too_long():
    with pytest.raises(TooLongInputError):
        validate_input("x" * 11, 10)
    assert validate_input("x" * 10, 10) == "x" * 10
