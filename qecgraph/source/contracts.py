"""Typed shapes shared by literal source extraction and reading projections."""
from typing import TypedDict


class SourceRange(TypedDict):
    path: str
    char_start: int
    char_end: int
    line_start: int
    line_end: int


class MacroDefinition(TypedDict):
    name: str
    latex: str
    source: SourceRange


class PaperMetadata(TypedDict):
    title: str | None
    authors: list[str]
    published_date: str | None
    topics: list[str]
    link: str | None
