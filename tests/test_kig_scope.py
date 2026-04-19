"""Tests for library scope resolution."""

from kig_scope import Entry, resolve_library, Suppress


def E(text: str, category: str = "misc", entry_id: str | None = None) -> Entry:
    return Entry(id=entry_id or text[:4], text=text, category=category)


def test_isolate_ignores_global():
    g = [E("global-a")]
    p = [E("proj-a")]
    result = resolve_library(
        g, p, scope_mode="per-category", suppress=Suppress(), isolate=True
    )
    assert [e.text for e in result] == ["proj-a"]


def test_override_replaces_global_when_project_nonempty():
    g = [E("global-a"), E("global-b")]
    p = [E("proj-a")]
    result = resolve_library(
        g, p, scope_mode="override", suppress=Suppress(), isolate=False
    )
    assert [e.text for e in result] == ["proj-a"]


def test_override_falls_back_to_global_when_project_empty():
    g = [E("global-a")]
    result = resolve_library(
        g, [], scope_mode="override", suppress=Suppress(), isolate=False
    )
    assert [e.text for e in result] == ["global-a"]


def test_additive_concatenates():
    g = [E("g1"), E("g2")]
    p = [E("p1")]
    result = resolve_library(
        g, p, scope_mode="additive", suppress=Suppress(), isolate=False
    )
    assert [e.text for e in result] == ["g1", "g2", "p1"]


def test_per_category_filters_by_category():
    g = [E("g1", category="tests"), E("g2", category="docs")]
    p = [E("p1", category="docs")]
    result = resolve_library(
        g,
        p,
        scope_mode="per-category",
        suppress=Suppress(categories={"tests"}),
        isolate=False,
    )
    assert [e.text for e in result] == ["g2", "p1"]


def test_per_category_filters_by_id():
    g = [E("g1", entry_id="abc"), E("g2", entry_id="def")]
    result = resolve_library(
        g,
        [],
        scope_mode="per-category",
        suppress=Suppress(ids={"abc"}),
        isolate=False,
    )
    assert [e.text for e in result] == ["g2"]


def test_empty_global_empty_project_returns_empty():
    result = resolve_library(
        [], [], scope_mode="per-category", suppress=Suppress(), isolate=False
    )
    assert result == []


def test_isolate_with_empty_project_returns_empty():
    result = resolve_library(
        [E("g")], [], scope_mode="per-category", suppress=Suppress(), isolate=True
    )
    assert result == []
