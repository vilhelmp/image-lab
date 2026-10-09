"""Switches an admin flips while the app runs. In memory: a restart goes back to the defaults."""

from __future__ import annotations


class RuntimeFlags:
    """The photo studio starts off, and so does the high-quality image model."""

    def __init__(self, *, photo_studio: bool = False, high_quality: bool = False) -> None:
        self._photo_studio = photo_studio
        self._high_quality = high_quality

    @property
    def photo_studio(self) -> bool:
        return self._photo_studio

    def set_photo_studio(self, value: bool) -> None:
        self._photo_studio = bool(value)

    @property
    def high_quality(self) -> bool:
        return self._high_quality

    def set_high_quality(self, value: bool) -> None:
        self._high_quality = bool(value)
