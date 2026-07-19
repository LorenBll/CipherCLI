"""Generic POST response model."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class PostResponse:
    """Describe a normalized POST response."""

    status_code: int
    body: str
    json_body: dict | list | str | int | float | bool | None = None
