"""The patched typeshed is rebuilt when stale and never patches a changed upstream file."""

import re
import shutil
from pathlib import Path
from unittest import TestCase

from scripts.typecheck import PATCH, TYPESHED, Bundled, ensure, installed

ROOT = Path(__file__).resolve().parent.parent
PATCHED = tuple(re.findall(r"(?m)^diff --git a/(\S+) ", (ROOT / PATCH).read_text(encoding="utf-8")))


def fixture(tmp_path: Path) -> tuple[Path, Bundled]:
    root = tmp_path / "checkout"
    (root / PATCH).parent.mkdir(parents=True)
    shutil.copyfile(ROOT / PATCH, root / PATCH)
    folder = tmp_path / "typeshed-fallback"
    upstream = installed().folder
    (folder / "stdlib").mkdir(parents=True)
    shutil.copyfile(upstream / "LICENSE", folder / "LICENSE")
    for name in (*PATCHED, "stdlib/os/__init__.pyi"):
        (folder / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(upstream / name, folder / name)
    return root, Bundled(folder, "1.0.0")


def test_the_patch_corrects_its_stubs_and_a_stale_build_is_rebuilt(tmp_path: Path) -> None:
    # Defect: the patch is not applied, or an edited patch or a pyright
    # upgrade keeps using the previously built typeshed.
    root, bundled = fixture(tmp_path)
    built = ensure(root, bundled)
    assert built == root / TYPESHED
    assert "def __init__(self) -> None: ...\n        def copy(self) -> frozendict" not in (built / "stdlib/builtins.pyi").read_text(encoding="utf-8")
    assert (built / "stdlib/os/__init__.pyi").read_bytes() == (bundled.folder / "stdlib/os/__init__.pyi").read_bytes()
    (root / PATCH).write_text(
        (root / PATCH).read_text(encoding="utf-8").replace("stdout: IO[AnyStr]", "stdout: IO[bytes]"), encoding="utf-8", newline="\n"
    )
    assert "stdout: IO[bytes]" in (ensure(root, bundled) / "stdlib/subprocess.pyi").read_text(encoding="utf-8")
    (bundled.folder / "stdlib/os/__init__.pyi").write_text("# upgraded\n", encoding="utf-8")
    assert (ensure(root, Bundled(bundled.folder, "2.0.0")) / "stdlib/os/__init__.pyi").read_text(encoding="utf-8") == "# upgraded\n"


def test_the_patch_is_refused_when_pyright_ships_a_different_upstream_file(tmp_path: Path) -> None:
    # Defect: a pyright upgrade's corrected stub is silently overwritten by a patch made from the old one.
    root, bundled = fixture(tmp_path)
    (bundled.folder / "stdlib/winreg.pyi").write_text("# upstream fix\n", encoding="utf-8")
    with TestCase().assertRaisesRegex(RuntimeError, "does not apply"):
        ensure(root, bundled)
    assert not (root / TYPESHED).exists()
    assert not tuple((root / TYPESHED).parent.glob(".workspace-typeshed-*"))
