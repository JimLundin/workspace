"""Changed-source selection through actual imports, package initialization and deletion."""

import contextlib
import importlib
import sys
from pathlib import Path

from scripts.architecture import dependencies
from scripts.check import Selection, execute, select, windows_only


def tree(root: Path) -> dict[str, str]:
    text = {'app/__init__.py': '', 'app/value.py': 'value = 42\n', 'app/api.py': 'from .value import value\n',
            'tests/fixture.py': 'from app import api\n', 'tests/test_api.py': 'from tests.fixture import api\n',
            'tests/test_other.py': 'import json\n', 'tests/test_windows_api.py': 'from app.api import value\n'}
    for name, content in text.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    return dict.fromkeys(text, 'before')


def test_selection_follows_relative_imports_and_test_fixtures(tmp_path: Path) -> None:
    previous = tree(tmp_path)
    nested = 'tests/properties/test_api.py'
    path = tmp_path / nested
    path.parent.mkdir()
    path.write_text('from tests.fixture import api\n')
    previous = previous | {nested: 'before'}
    current = previous | {'app/value.py': 'after'}
    result = select(tmp_path, current, previous)
    assert set(result.tests) == {'tests/test_api.py', nested}
    result = select(tmp_path, current, previous, native=True)
    assert set(result.tests) == {'tests/test_api.py', 'tests/test_windows_api.py', nested}
    assert set(select(tmp_path, current, previous, full=True).tests) == {'tests/test_api.py', 'tests/test_other.py', nested}


def test_package_initializer_and_deleted_source_select_consumers(tmp_path: Path) -> None:
    previous = tree(tmp_path)
    assert select(tmp_path, previous | {'app/__init__.py': 'after'}, previous).tests == ('tests/test_api.py',)
    current = {name: digest for name, digest in previous.items() if name != 'app/value.py'}
    (tmp_path / 'app/value.py').unlink()
    assert select(tmp_path, current, previous).tests == ('tests/test_api.py',)


def test_broad_changes_fall_back_to_full_suite(tmp_path: Path) -> None:
    previous = tree(tmp_path)
    for name in ('runtime.py', 'requirements/windows-py315.lock', 'app/assets.js'):
        result = select(tmp_path, previous | {name: 'after'}, previous)
        assert set(result.tests) == {'tests/test_api.py', 'tests/test_other.py'}
    assert select(tmp_path, previous, previous).tests == ()
    assert set(select(tmp_path, previous, previous, full=True).tests) == {'tests/test_api.py', 'tests/test_other.py'}


def test_static_dynamic_imports_and_ancestors_are_dependencies() -> None:
    imports = dependencies('app/sub/source.py', 'from .. import api\nimport app.value\nimportlib.import_module("app.more.value")\n')
    assert {'app', 'app.api', 'app.value', 'app.more', 'app.more.value'} <= imports


def test_editing_checks_do_not_hide_local_import_or_runtime_failures() -> None:
    assert not windows_only(ImportError('missing_workspace_module'))
    assert not windows_only(RuntimeError('PySide6 initialization failed'))
    assert windows_only(ImportError('PySide6 missing')) is (sys.platform != 'win32')


def test_function_selection_runs_the_requested_case_and_rejects_typos(tmp_path: Path) -> None:
    test = tmp_path / 'selected_case.py'
    test.write_text('def test_requested():\n    pass\n\ndef test_unrelated():\n    raise AssertionError("must not run")\n')
    sys.path.insert(0, str(tmp_path))
    try:
        importlib.invalidate_caches()
        passed, skipped, failures, _ = execute(Selection(('selected_case.py::test_requested',), (), 'explicit iteration scope'), tmp_path)
        assert (passed, skipped, failures) == (1, 0, ())
        passed, _, failures, _ = execute(Selection(('selected_case.py::test_missing',), (), 'explicit iteration scope'), tmp_path)
        assert passed == 0 and failures == ('No test function matched selected_case.py::test_missing',)
    finally:
        sys.path.remove(str(tmp_path))
        with contextlib.suppress(KeyError):
            del sys.modules['selected_case']
