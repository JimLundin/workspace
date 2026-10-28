"""Stage a checked tree and deploy source while preserving the Windows runtime.

python -m scripts.deploy deploy --check-receipt /tmp/workspace-check.json
A stage can be inspected/reverified with --stage after completion. Bundle rebuilds
remain a separate command for runtime pin changes.
"""

import argparse
import contextlib
import inspect
import os
import shutil
import subprocess
import time
import zipfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from scripts.deploy_files import HELPERS, PINS, read, sha, source_map, write, zip_files
from scripts.deploy_values import CONFIG, Config
from scripts.development_paths import LIVE, PROFILE, TEMP
lazy from scripts.check import source_files
lazy from scripts.deploy_windows import run

WORKSPACE = Path(__file__).resolve().parent.parent


@dataclass(frozen=True, slots=True)
class Options:
    action: Literal['stage', 'verify', 'deploy']
    stage: Path | None
    check_receipt: Path | None


def win(path: Path) -> str:
    if os.name == 'nt':
        absolute = path.absolute()
        if absolute.drive.upper() != 'C:':
            raise ValueError('Windows deployment paths must reside on the C drive.')
        return str(absolute)
    value = path.absolute().as_posix()
    if not value.startswith('/mnt/c/'):
        raise ValueError('Windows deployment paths must reside on the C drive.')
    return 'C:\\' + value.removeprefix('/mnt/c/').replace('/', '\\')


def workspace_files() -> dict[str, str]:
    return source_map({'files': source_files(WORKSPACE)})


def stage_source(receipt: Path, stage: Path | None = None) -> Path:
    checked = read(receipt)
    wanted = source_map(checked)
    match checked:
        case {'kind': 'workspace-edit-check-v1', 'tests': list()}:
            pass
        case _:
            raise ValueError('Supply a successful scripts.check source-bound receipt.')
    if workspace_files() != wanted:
        raise RuntimeError('The working tree differs from the checked source; rerun checks.')
    stage = stage or TEMP / f'workspace-source-{time.time_ns()}'
    if not stage.name.startswith('workspace-source-'):
        raise ValueError('Use a fresh workspace-source-* stage.')
    win(stage)
    stage.mkdir(exist_ok=False)
    (stage / 'scripts').mkdir()
    (stage / 'scripts' / '__init__.py').write_text('', encoding='utf-8')
    hashes: dict[str, str] = {}
    for name in HELPERS:
        shutil.copyfile(WORKSPACE / name, stage / name)
        hashes[name] = sha(stage / name)
    with zipfile.ZipFile(stage / 'source.zip', 'x', zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
        for name in wanted:
            archive.write(WORKSPACE / name, 'workspace/' + name)
    if zip_files(stage / 'source.zip') != wanted or workspace_files() != wanted:
        raise RuntimeError('Source changed while the release was staged.')
    shutil.copyfile(receipt, stage / 'checked.json')
    write(stage / 'source.json', {'files': wanted})
    write(stage / 'release.json', {
        'kind': 'workspace-source-only-v2', 'stage_id': stage.name,
        'live_windows': win(LIVE), 'archive_windows': win(LIVE.parent.parent / 'workspace-sdk-python315-win64.zip'),
        'profile_windows': win(PROFILE), 'helpers': hashes,
        'source_manifest_sha256': sha(stage / 'source.json'), 'payload_sha256': sha(stage / 'source.zip'),
        'check_sha256': sha(stage / 'checked.json'), 'pins': {name: wanted[name] for name in PINS}, 'created_at_ns': time.time_ns(),
    })
    print(f'Staged {len(wanted)} checked source files: {stage}', flush=True)
    return stage


def checked_config(stage: Path) -> tuple[Config, dict[str, str]]:
    config = CONFIG.validate_json((stage / 'release.json').read_bytes(), strict=True)
    if (config.get('kind') != 'workspace-source-only-v2' or config.get('stage_id') != stage.name
            or not stage.name.startswith('workspace-source-') or set(config['helpers']) != set(HELPERS)):
        raise RuntimeError('Invalid source release stage.')
    for name, expected in config['helpers'].items():
        if sha(stage / name) != expected or sha(WORKSPACE / name) != expected:
            raise RuntimeError('A checked deployment helper changed.')
    if sha(stage / 'source.json') != config['source_manifest_sha256'] or sha(stage / 'checked.json') != config['check_sha256']:
        raise RuntimeError('The checked source manifest or receipt changed.')
    wanted = source_map(read(stage / 'source.json'))
    if source_map(read(stage / 'checked.json')) != wanted or {name: wanted[name] for name in PINS} != config['pins']:
        raise RuntimeError('The staged source differs from the check receipt or runtime pins.')
    return config, wanted


def arguments(parser: argparse.ArgumentParser) -> Options:
    match dict(inspect.getmembers(parser.parse_args())):
        case {'action': str() as action, 'stage': (Path() | None) as stage,
              'check_receipt': (Path() | None) as receipt}:
            match action:
                case 'stage' | 'verify' | 'deploy':
                    return Options(action, stage, receipt)
                case _:
                    pass
        case _:
            pass
    return parser.error('Invalid deployment arguments.')


def coordinate_native(stage: Path, operation: Callable[[], None],
                      snapshot: Callable[[], Mapping[str, str]] | None = None) -> None:
    """Own the native coordinator's working folder and checked source lifetime."""
    before = snapshot() if snapshot is not None else None
    with contextlib.chdir(stage):
        operation()
    if snapshot is not None and snapshot() != before:
        raise RuntimeError('Source changed during deployment; the installed stage must be reconciled.')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('stage', 'verify', 'deploy'))
    parser.add_argument('--stage', type=Path)
    parser.add_argument('--check-receipt', type=Path)
    args = arguments(parser)
    stage = args.stage
    if stage is None:
        if args.check_receipt is None:
            parser.error('--check-receipt is required to create a source stage')
        stage = stage_source(args.check_receipt)
    if args.action == 'stage':
        return
    config, wanted = checked_config(stage)
    source_checkout = stage.resolve() != WORKSPACE
    if source_checkout and workspace_files() != wanted:
        raise RuntimeError('Source changed after staging; rerun checks.')
    if os.name == 'nt':
        # The venv shares the installed interpreter. Keep one coordinator so
        # an installed Python parent is not mistaken for an unowned workload.
        def coordinate() -> None:
            run(args.action, stage, config, wanted)
        coordinate_native(stage, coordinate, workspace_files if source_checkout else None)
        return
    result = subprocess.run(
        [str(LIVE / '.python' / 'python.exe'), '-B', '-m', 'scripts.deploy', args.action, '--stage', win(stage)],
        cwd=stage, check=False)
    if result.returncode == 0 and workspace_files() != wanted:
        raise RuntimeError('Source changed during deployment; the installed stage must be reconciled.')
    raise SystemExit(result.returncode)


if __name__ == '__main__':
    main()
