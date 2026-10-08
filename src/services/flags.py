"""Switches an admin flips while the app runs. In memory: a restart goes back to the defaults."""

from __future__ import annotations


class RuntimeFlags:
    """The photo studio starts off. The admin account switches it on for the workshop."""

    def __init__(self, *, photo_studio: bool = False) -> None:
        self._photo_studio = photo_studio

    @property
    def photo_studio(self) -> bool:
        return self._photo_studio

    def set_photo_studio(self, value: bool) -> None:
        self._photo_studio = bool(value)
