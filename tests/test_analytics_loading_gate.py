"""Tests for the analytics loading-indicator decision.

The "Показатели" and "Сравнение с Pro" buttons switch between lazily generated
pages. A loading message is only justified while a page is actually being
computed; on an already generated page it is a pointless flicker.

main.py cannot be imported in this environment (no redis package), so the
predicate is loaded from its AST instead of through a normal import.
"""

import ast
import types
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MAIN_PATH = PROJECT_ROOT / "main.py"
FUNC_NAME = "_analytics_page_needs_generation"


def _load_predicate():
    tree = ast.parse(MAIN_PATH.read_text(encoding="utf-8-sig"))
    node = next(
        n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == FUNC_NAME
    )
    namespace = {}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(MAIN_PATH), "exec"), namespace)
    return namespace[FUNC_NAME]


needs_generation = _load_predicate()


def _context(user_data):
    return types.SimpleNamespace(user_data=user_data)


@pytest.mark.parametrize(
    "user_data, page_idx, expected",
    [
        # Nothing cached yet: the first open computes the page.
        ({}, 0, True),
        ({}, 1, True),
        # Placeholder rows from analyze_command are not real pages.
        ({"analytics_generated": {0}, "analytics_pages": [None, None]}, 0, True),
        ({"analytics_generated": set(), "analytics_pages": []}, 0, True),
        # Generated page: switching is an instant message edit, no spinner.
        (
            {"analytics_generated": {0, 1}, "analytics_pages": [{"text": "a"}, {"text": "b"}]},
            0,
            False,
        ),
        (
            {"analytics_generated": {0, 1}, "analytics_pages": [{"text": "a"}, {"text": "b"}]},
            1,
            False,
        ),
        # Page 1 not generated yet while page 0 is.
        ({"analytics_generated": {0}, "analytics_pages": [{"text": "a"}, None]}, 1, True),
    ],
)
def test_needs_generation(user_data, page_idx, expected):
    assert needs_generation(_context(user_data), page_idx) is expected


def test_buttons_ask_predicate_before_sending_loading():
    """Both analytics buttons must gate show_loading on the predicate."""
    content = MAIN_PATH.read_text(encoding="utf-8-sig")
    gated = content.count("_analytics_page_needs_generation(context, 0)")
    assert gated == 2, "analytics_show and analytics_pro_compare must both check it"
