"""Real archive/file boundaries for the source-only deployment path."""

import contextlib
import io
import os
import shutil
import subprocess
import sys
import zipfile
from collections.abc import Generator
from pathlib import Path, PureWindowsPath
from typing import IO, Literal
from unittest.mock import patch

from scripts import deploy
from scripts.deploy_archive import repack
from scripts.deploy_files import file_at, files, member, names, sha, source_map, write, zip_files
from scripts.deploy_processes import Process, role_for
from scripts.deploy_values import Prepared
from scripts.deploy_windows import Release, drive, group


def test_only_the_exact_development_editor_server_is_exempt_from_installed_process_ownership() -> None:
    interpreter = PureWindowsPath(r'C:\Users\Jim.Lundin\Projects\workspace\.venv\Scripts\python.exe')
    extensions = PureWindowsPath(r'C:\Users\Jim.Lundin\.vscode\extensions')
    script = extensions / 'ms-python.black-formatter-2026.6.0' / 'bundled' / 'tool' / 'lsp_server.py'
    editor = interpreter, extensions
    assert role_for((str(interpreter).lower(), str(script)), windowed=False, editor=editor) is None
    for arguments in ((str(interpreter), str(script), 'extra'),
                      (r'C:\installed\.python\python.exe', str(script)),
                      (str(interpreter), str(script.with_name('workspace.pyw'))),
                      (str(interpreter), str(extensions / 'unrelated-extension' / 'bundled' / 'tool' / 'lsp_server.py')),
                      (str(interpreter), r'C:\elsewhere\lsp_server.py')):
        assert role_for(arguments, windowed=False, editor=editor) == 'runtime'


def test_native_development_tools_can_coexist_with_deployment_only_from_the_reviewed_venv() -> None:
    interpreter = PureWindowsPath(r'C:\Users\Jim.Lundin\Projects\workspace\.venv\Scripts\python.exe')
    editor = (interpreter, PureWindowsPath(r'C:\Users\Jim.Lundin\.vscode\extensions'))
    for module in ('scripts.watch', 'scripts.check', 'scripts.preview'):
        command = (str(interpreter), '-B', '-m', module, '--once')
        assert role_for(command, windowed=False, editor=editor) is None
        assert role_for(command, windowed=True, editor=editor) == 'runtime'
        assert role_for((r'C:\elsewhere\python.exe', *command[1:]), windowed=False, editor=editor) == 'runtime'
    assert role_for((str(interpreter), '-m', 'unrelated'), windowed=False, editor=editor) == 'runtime'


def test_only_the_exact_installed_console_hook_is_external_to_the_application_process_tree() -> None:
    root = PureWindowsPath(r'C:\Users\Jim.Lundin\Downloads\workspace-sdk\workspace')
    interpreter = str(root / '.python' / 'python.exe')
    hook = str(root / 'scripts' / 'inbox_hook.py')
    for provider in ((), ('--codex',), ('--claude',)):
        assert role_for((interpreter, hook, *provider), windowed=False) is None
    for command in ((interpreter, hook, '--other'), (interpreter, hook, '--codex', 'extra'),
                    (interpreter, str(root / 'scripts' / 'unrelated.py'), '--codex'),
                    (r'C:\elsewhere\python.exe', hook, '--codex'),
                    (interpreter, '-c', hook)):
        assert role_for(command, windowed=False) == 'runtime'
    assert role_for((interpreter, hook), windowed=True) == 'runtime'


def test_native_checkout_uses_one_coordinator_and_detects_changes_after_deployment(tmp_path: Path) -> None:
    if os.name != 'nt':
        return
    stage = tmp_path / 'workspace-source-test'
    stage.mkdir()
    original_cwd = Path.cwd()
    wanted = {'source.py': 'checked-hash'}
    def in_stage(*_arguments: object) -> None:
        assert Path.cwd() == stage
    with (patch.object(sys, 'argv', ['deploy', 'deploy', '--stage', str(stage)]),
          patch.object(deploy, 'checked_config', return_value=({}, wanted)),
          patch.object(deploy, 'workspace_files', return_value=wanted),
          patch('scripts.deploy_windows.run', side_effect=in_stage) as coordinator,
          patch.object(subprocess, 'run', side_effect=AssertionError('A second installed Python must not be launched'))):
        deploy.main()
        coordinator.assert_called_once_with('deploy', stage, {}, wanted)
        assert Path.cwd() == original_cwd
    with (patch.object(sys, 'argv', ['deploy', 'deploy', '--stage', str(stage)]),
          patch.object(deploy, 'checked_config', return_value=({}, wanted)),
          patch.object(deploy, 'workspace_files', side_effect=[wanted, {'source.py': 'changed'}]),
          patch('scripts.deploy_windows.run')):
        try:
            deploy.main()
        except RuntimeError as error:
            assert 'Source changed during deployment' in str(error)
        else:
            raise AssertionError('A modified development checkout was reported as successfully deployed')


def test_release_paths_reject_windows_aliases_and_escapes(tmp_path: Path) -> None:
    for path in ('../escape', '/escape', 'a/../b', 'a\\b', 'a//b', 'NUL.txt', 'a:stream', 'a. ', 'a.'):
        try:
            member(path)
        except ValueError:
            continue
        raise AssertionError(path)
    try:
        names(('One/file', 'one/other'))
    except ValueError:
        pass
    else:
        raise AssertionError('Windows directory aliases must fail')
    (tmp_path / 'real').mkdir()
    if os.name == 'nt':
        subprocess.run(['cmd.exe', '/c', 'mklink', '/J', str(tmp_path / 'link'), str(tmp_path / 'real')],
                       check=True, capture_output=True)
    else:
        (tmp_path / 'link').symlink_to(tmp_path / 'real', target_is_directory=True)
    try:
        file_at(tmp_path, 'link/file')
    except ValueError:
        pass
    else:
        raise AssertionError('Linked destinations must fail')


def test_source_contract_excludes_runtime_and_bytecode() -> None:
    pins = {'requirements/python-win64.json': 'a' * 64, 'requirements/windows-py315.lock': 'b' * 64}
    for extra in ('.python/private', '.runtime/private', 'a/__pycache__/b.pyc', 'a.pyc'):
        try:
            source_map({'files': pins | {extra: 'c' * 64}})
        except ValueError:
            continue
        raise AssertionError(extra)


def test_source_repack_preserves_compressed_runtime_without_opening_it(tmp_path: Path) -> None:
    prior, output = tmp_path / 'prior.zip', tmp_path / 'fresh.zip'
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'new.py').write_bytes(b'answer = 42\n')
    data = os.urandom(2_000_000)
    with zipfile.ZipFile(prior, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('workspace/.python/runtime.bin', data)
        archive.writestr('workspace/removed.py', 'stale')
    original_open = zipfile.ZipFile.open

    def source_only(archive: zipfile.ZipFile, name: str | zipfile.ZipInfo, mode: Literal["r", "w"] = "r",
                    pwd: bytes | None = None, *, force_zip64: bool = False) -> IO[bytes]:
        label = name.filename if isinstance(name, zipfile.ZipInfo) else name
        assert '/.python/' not in label, 'source deploy must never decompress/recompress runtime'
        return original_open(archive, name, mode, pwd, force_zip64=force_zip64)

    with patch.object(zipfile.ZipFile, 'open', source_only):
        repack(prior, output, source, {'new.py': sha(source / 'new.py')})
    with zipfile.ZipFile(output) as archive:
        assert archive.read('workspace/.python/runtime.bin') == data
        assert archive.read('workspace/new.py') == b'answer = 42\n'
        assert set(archive.namelist()) == {'workspace/.python/runtime.bin', 'workspace/new.py'}
    assert prior.stat().st_size - 1000 < output.stat().st_size < prior.stat().st_size + 1000
    assert zip_files(output)['new.py'] == sha(source / 'new.py')


def test_repack_rejects_duplicate_or_unsafe_archive_members(tmp_path: Path) -> None:
    source = tmp_path / 'source'
    source.mkdir()
    prior = tmp_path / 'prior.zip'
    with zipfile.ZipFile(prior, 'w') as archive:
        archive.writestr('workspace/../escape', 'bad')
    try:
        repack(prior, tmp_path / 'new.zip', source, {})
    except ValueError:
        pass
    else:
        raise AssertionError('Unsafe ZIP member accepted')


def test_repack_preserves_descriptor_and_zip64_records(tmp_path: Path) -> None:
    class Unseekable(io.BytesIO):
        def seekable(self) -> bool:
            return False

        def seek(self, offset: int, whence: int = os.SEEK_SET) -> int:
            raise OSError('nonseekable writer')

    stream = Unseekable()
    with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as archive, \
            archive.open('workspace/.runtime/library', 'w', force_zip64=True) as writer:
        writer.write(b'important runtime bytes' * 500)
    prior = tmp_path / 'prior.zip'
    prior.write_bytes(stream.getvalue())
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'next.py').write_bytes(b'next = True\n')
    output = tmp_path / 'next.zip'
    repack(prior, output, source, {'next.py': sha(source / 'next.py')})
    with zipfile.ZipFile(output) as archive:
        assert archive.read('workspace/.runtime/library') == b'important runtime bytes' * 500
        assert archive.read('workspace/next.py') == b'next = True\n'


def test_process_classifier_preserves_only_independent_browser_host() -> None:
    assert role_for(('pythonw.exe', '-B', '-m', 'assistant.browser_host', '--generation', '1'), windowed=True) is None
    assert role_for(('pythonw.exe', '-m', 'assistant'), windowed=True) == 'assistant'
    assert role_for(('pythonw.exe', 'workspace.pyw'), windowed=True) == 'keeper'
    assert role_for(('python.exe', 'test.py', '-m', 'assistant.browser_host'), windowed=False) == 'runtime'
    assert role_for(('pythonw.exe', 'test.py', 'workspace.pyw'), windowed=True) == 'runtime'


def test_process_group_rejects_unowned_or_duplicate_children() -> None:
    rows = (Process(10, 1, 'keeper', 'pythonw.exe', 1), Process(11, 10, 'assistant', 'pythonw.exe', 1),
            Process(12, 10, 'automation', 'pythonw.exe', 1), Process(13, 10, 'miryoku', 'pythonw.exe', 1))
    assert group(rows)['assistant'].pid == 11
    for bad in ((*rows, rows[1]), (*rows, Process(14, 99, 'runtime', 'python.exe', 1)), rows[:-1]):
        try:
            group(bad)
        except RuntimeError:
            continue
        raise AssertionError('Unowned/incomplete process tree accepted')


def test_partial_install_restores_verified_before_images(tmp_path: Path) -> None:
    """Drive the real coordinator/install/copy/restore path with owned temp files."""
    class LocalRelease(Release):
        def __init__(self, root: Path = tmp_path, *, fail_copy: bool = True) -> None:
            self.fail_copy = fail_copy
            self.stage = root / 'stage'
            self.live = root / 'live'
            self.profile = root / 'profile'
            self.state = self.profile / 'keeper'
            self.archive = root / 'bundle.zip'
            self.stage.mkdir()
            self.live.mkdir()
            for directory in ('.python', '.runtime'):
                (self.live / directory).mkdir()
                (self.live / directory / 'preserved').write_bytes(b'pinned runtime bytes')
            (self.live / 'old.py').write_bytes(b'old source')
            source = self.stage / 'source'
            source.mkdir()
            (source / 'old.py').write_bytes(b'new source')
            (source / 'added.py').write_bytes(b'new file')
            self.wanted = files(source)
            with zipfile.ZipFile(self.archive, 'w') as archive:
                archive.writestr('workspace/old.py', b'old source')
            backup = self.stage / 'backup'
            (backup / 'source').mkdir(parents=True)
            shutil.copyfile(self.live / 'old.py', backup / 'source' / 'old.py')
            shutil.copyfile(self.archive, backup / 'previous-bundle.zip')
            repack(self.archive, self.stage / 'new-bundle.zip', source, self.wanted)
            runtime = {f'{directory}/preserved': sha(self.live / directory / 'preserved') for directory in ('.python', '.runtime')}
            self.baseline: Prepared = {'stage_id': self.stage.name, 'source_before': {'old.py': sha(self.live / 'old.py')},
                             'old_source': {'old.py': sha(self.live / 'old.py')}, 'unrelated_source': {},
                             'old_archive_sha256': sha(self.archive), 'new_archive_sha256': sha(self.stage / 'new-bundle.zip'),
                             'runtime': runtime, 'runtime_fingerprint': self.runtime_fingerprint(runtime),
                             'manifest_sha256': '0' * 64, 'runtime_audit_reused': False, 'runtime_directory_ids': {}, 'prepared_at_ns': 0}
            self.copies = 0
            self.restored = False

        def prepared(self) -> Prepared:
            return self.baseline

        def prepare(self) -> None:
            pass

        def stop(self) -> None:
            write(self.stage / 'stopped.json', {'stage_id': self.stage.name, 'was_running': False, 'clean_exit': True,
                                              'processes_before': [], 'exits': []})

        def pins(self) -> None:
            pass

        @contextlib.contextmanager
        def exclusive(self) -> Generator[None]:
            yield

        def copy(self, source: Path, destination: Path) -> None:
            self.copies += 1
            if self.fail_copy and self.copies == 2:
                raise OSError('injected second source replacement failure')
            super().copy(source, destination)

        def inventory(self) -> tuple[Process, ...]:
            return ()

        def reload(self) -> None:
            # Both successful source installation and rollback reach this real
            # coordinator seam before any archive publication is allowed.
            assert (self.live / 'old.py').read_bytes() == (b'old source' if self.fail_copy else b'new source')
            assert (self.live / 'added.py').exists() is not self.fail_copy
            assert sha(self.archive) == self.baseline['old_archive_sha256']
            self.receipt('reloaded.json', {'was_running': False, 'left_stopped': True})
            self.restored = True

    release = LocalRelease()
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            drive(release, 'deploy')
    except OSError as error:
        assert 'second source replacement' in str(error)
    else:
        raise AssertionError('A failed install must report failure')
    assert release.restored
    assert (release.stage / 'rollback.json').is_file()
    assert not (release.stage / 'verified.json').exists()
    assert release.runtime_fingerprint(release.baseline['runtime']) == release.baseline['runtime_fingerprint']
    success_root = tmp_path / 'success'
    success_root.mkdir()
    success = LocalRelease(success_root, fail_copy=False)
    with contextlib.redirect_stdout(io.StringIO()):
        drive(success, 'deploy')
    assert success.restored
    assert sha(success.archive) == success.baseline['new_archive_sha256']
    assert (success.stage / 'verified.json').is_file()
    assert (success.stage / 'archive-published.json').is_file()


def test_runtime_metadata_detects_changed_members_and_bytes(tmp_path: Path) -> None:
    """The cheap metadata audit still invalidates an ordinary modified runtime."""
    class LocalRelease(Release):
        def __init__(self) -> None:
            self.live = tmp_path

    for folder in ('.python', '.runtime'):
        (tmp_path / folder).mkdir()
        (tmp_path / folder / 'library').write_bytes(b'old')
    release = LocalRelease()
    expected = {'.python/library': '0' * 64, '.runtime/library': '0' * 64}
    before = release.runtime_fingerprint(expected)
    (tmp_path / '.runtime/library').write_bytes(b'new longer library')
    assert release.runtime_fingerprint(expected) != before
    (tmp_path / '.runtime/added').write_bytes(b'new member')
    assert '.runtime/added' in release.runtime_fingerprint(expected)
    (tmp_path / '.runtime/__pycache__').mkdir()
    (tmp_path / '.runtime/__pycache__/generated.pyc').write_bytes(b'generated')
    assert '.runtime/__pycache__/generated.pyc' not in release.runtime_fingerprint(expected)
