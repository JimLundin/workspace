"""The patched typeshed is rebuilt when stale and never overrides a changed upstream file."""

import shutil
from pathlib import Path
from unittest import TestCase

from scripts.typecheck import OVERRIDES, TYPESHED, UPSTREAM, Bundled, ensure, installed

ROOT = Path(__file__).resolve().parent.parent


def fixture(tmp_path: Path) -> tuple[Path, Bundled]:
    root = tmp_path / "checkout"
    shutil.copytree(ROOT / OVERRIDES, root / OVERRIDES)
    folder = tmp_path / "typeshed-fallback"
    upstream = installed().folder
    (folder / "stdlib").mkdir(parents=True)
    shutil.copyfile(upstream / "LICENSE", folder / "LICENSE")
    for name in (*UPSTREAM, "stdlib/os/__init__.pyi"):
        (folder / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(upstream / name, folder / name)
    return root, Bundled(folder, "1.0.0")


def test_overrides_replace_their_upstream_files_and_a_stale_build_is_rebuilt(tmp_path: Path) -> None:
    # Defect: an override is not applied, or an edited override or a pyright
    # upgrade keeps using the previously built typeshed.
    root, bundled = fixture(tmp_path)
    builtins = root / OVERRIDES / "stdlib/builtins.pyi"
    built = ensure(root, bundled)
    assert built == root / TYPESHED
    assert (built / "stdlib/builtins.pyi").read_bytes() == builtins.read_bytes()
    assert (built / "stdlib/os/__init__.pyi").read_bytes() == (bundled.folder / "stdlib/os/__init__.pyi").read_bytes()
    builtins.write_text(builtins.read_text(encoding="utf-8") + "# edited\n", encoding="utf-8")
    assert (ensure(root, bundled) / "stdlib/builtins.pyi").read_text(encoding="utf-8").endswith("# edited\n")
    (bundled.folder / "stdlib/os/__init__.pyi").write_text("# upgraded\n", encoding="utf-8")
    assert (ensure(root, Bundled(bundled.folder, "2.0.0")) / "stdlib/os/__init__.pyi").read_text(encoding="utf-8") == "# upgraded\n"


def test_an_override_is_refused_when_pyright_ships_a_different_upstream_file(tmp_path: Path) -> None:
    # Defect: a pyright upgrade's corrected stub is silently replaced by an override made from the old one.
    root, bundled = fixture(tmp_path)
    (bundled.folder / "stdlib/winreg.pyi").write_text("# upstream fix\n", encoding="utf-8")
    with TestCase().assertRaisesRegex(RuntimeError, "stdlib/winreg.pyi"):
        ensure(root, bundled)
    assert not (root / TYPESHED).exists()
