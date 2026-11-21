"""Pagination helpers."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class Page:
    """Pagination meta-information."""

    page: int
    page_size: int
    total: int

    @property
    def pages(self) -> int:
        if self.total == 0:
            return 1
        return (self.total + self.page_size - 1) // self.page_size

    @property
    def has_prev(self) -> bool:
        return self.page > 0

    @property
    def has_next(self) -> bool:
        return self.page + 1 < self.pages


def paginate_meta(*, page: int, page_size: int, total: int) -> Page:
    return Page(page=page, page_size=page_size, total=total)
