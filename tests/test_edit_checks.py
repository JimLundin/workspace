"""Changed-source selection through actual imports, package initialization and deletion."""

import contextlib
import importlib
import io
import json
import sys
from pathlib import Path
from unittest.mock import Mock, patch

from scripts.architecture import Report, dependencies
from scripts.check import Selection, execute, main, select, windows_only


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


def test_generated_checks_precede_broad_dependency_imports_and_keep_import_gate(tmp_path: Path) -> None:
    # Eager SDK import before a property makes Hypothesis inspect bundled
    # dependency sources as local constants. Broad import failures must still
    # prevent a successful result after the generated checks run.
    order: list[str] = []

    def generated() -> None:
        order.append('generated')
        assert 'imports' not in order

    generated.__name__ = 'test_order'
    generated.__module__ = 'tests.properties.test_order'

    class Generated:
        __slots__ = ()
        test_order = staticmethod(generated)

    def imports(root: Path, failures: list[str]) -> None:
        order.append('imports')
        failures.append('A dependency does not import')

    with (patch('scripts.check.selfcheck', Mock(compile_all=Mock(), import_all=imports)),
          patch('scripts.check.importlib', Mock(import_module=Mock(return_value=Generated())))):
        passed, skipped, failures, _ = execute(
            Selection(('tests/properties/test_order.py',), (), 'full source checks'), tmp_path)
    assert order == ['generated', 'imports']
    assert (passed, skipped, failures) == (1, 0, ('A dependency does not import',))


def test_failed_checks_keep_complete_cost_evidence_without_a_success_receipt(tmp_path: Path) -> None:
    # The previous runner discarded every duration except five printed bodies
    # when a check failed, preventing attribution of the full suite's overhead.
    report, receipt = tmp_path / 'timings.json', tmp_path / 'receipt.json'
    (tmp_path / 'pyproject.toml').write_text('')
    current = {'tests/test_requested.py': 'checked-source'}
    durations = tuple((float(index), f'tests.test_requested.test_case_{index}') for index in range(1, 8))
    selected = Selection(tuple(current), (), 'explicit iteration scope')
    with (contextlib.redirect_stdout(io.StringIO()),
          patch('sys.argv', ['check', '--tests', *current, '--timings', str(report), '--receipt', str(receipt),
                             '--baseline', str(tmp_path)]),
          patch('scripts.check.ROOT', tmp_path),
          patch('scripts.check.source_files', return_value=current),
          patch('scripts.check.check_architecture', return_value=Report((), (), ())),
          patch('scripts.check.check_quality'),
          patch('scripts.check.select', return_value=selected),
          patch('scripts.check.execute', return_value=(6, 0, ('Fixture failure',), durations))):
        try:
            main()
        except SystemExit as error:
            assert error.code == 1
        else:
            raise AssertionError('A failed check must exit unsuccessfully')
    evidence = json.loads(report.read_text())
    assert evidence['failed'] == 1 and evidence['files'] == current
    assert all([seconds, name] in evidence['durations'] for seconds, name in durations)
    assert not receipt.exists()
