"""Workspace's interface policy gate."""

import ast
import importlib.util
import unittest
from pathlib import Path

from scripts.quality import imports


def source_tree(root: Path, text: str) -> None:
    (root / "assistant").mkdir()
    (root / "assistant" / "api.py").write_text(text, encoding="utf-8")
    (root / "pyproject.toml").write_text("[tool.workspace.architecture]\n", encoding="utf-8")


def development_lint() -> None:
    if importlib.util.find_spec("ruff") is None:
        raise unittest.SkipTest("Ruff is a development tool; Workspace itself does not require it.")


def test_import_ownership_rejects_aliases_and_forwarding() -> None:
    text = (
        "from owner import Request as Request\nfrom owner import Reply as ConsoleReply\n"
        "import owner as api\nfrom owner import Event\n"
        'def local():\n    pass\n__all__ = ("Event", "local")\n'
    )
    found = tuple(imports("assistant/api.py", ast.parse(text)))
    assert tuple((item.rule, item.line) for item in found) == (("import-alias", 1), ("import-alias", 2), ("import-alias", 3), ("re-export", 7))
    assert not tuple(imports("assistant/api.py", ast.parse('from owner import Event\ndef local():\n    pass\n__all__ = ("local",)\n')))
