"""Cached policy observations must still detect changed ownership and interfaces."""

from pathlib import Path

from scripts.architecture import review
from scripts.quality import scan
from scripts.source_analysis import Cache
from tests.test_architecture import write_tree
from tests.test_quality import development_lint, source_tree


def test_cached_policy_review_recomputes_changed_imports(tmp_path: Path) -> None:
    # Detect an old module observation hiding a new transitive keyboard import,
    # or damaged cache records producing a passing report.
    root = tmp_path / "source"
    root.mkdir()
    write_tree(
        root,
        {
            "miryoku/__init__.py": "",
            "miryoku/engine.py": "from bridge import value\n",
            "bridge.py": "value = 1\n",
            "assistant/__init__.py": "",
            "assistant/model.py": "",
        },
    )
    cache = Cache.bound(root, folder=tmp_path / "cache")
    assert review(root, cache=cache) == review(root) and not review(root, cache=cache).failures
    (root / "bridge.py").write_text("from assistant import model\nvalue = 2\n")
    report = review(root, cache=cache)
    assert report == review(root) and any(item.rule == "keyboard-isolation" for item in report.failures)
    # Cache damage must fall back to analysis, never produce a passing report.
    for path in cache.folder.glob("*.json"):
        path.write_text("partial")
    assert review(root, cache=cache) == report


def test_cached_quality_cannot_accept_changed_boolean_signature_or_import_ownership(tmp_path: Path) -> None:
    # Detect reusing an earlier valid source when an edit introduces a forbidden
    # signature or forwarding import, including a move that changes source lines.
    development_lint()
    source_tree(tmp_path, "def update(*, enabled: bool):\n    pass\n")
    cache = Cache.bound(tmp_path, folder=tmp_path / "cache")
    assert not scan(tmp_path, cache=cache)
    path = tmp_path / "assistant" / "api.py"
    path.write_text("\n\ndef update(enabled: bool):\n    from owner import Event\n")
    found = scan(tmp_path, cache=cache)
    assert found == scan(tmp_path)
    assert {item.rule for item in found} == {"FBT001", "PLC0415"}
    path.write_text("def update(*, enabled: bool):\n    pass\n")
    assert not scan(tmp_path, cache=cache)
