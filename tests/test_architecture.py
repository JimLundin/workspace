"""Policy behavior through the same source review used by editing checks."""

import json
import subprocess
import sys
from pathlib import Path

from scripts.architecture import dependencies, python_sources, review
from tests.check_fixture import copy_check_scripts
from tests.git_fixture import initialized


def write_tree(root: Path, files: dict[str, str]) -> None:
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    (root / "pyproject.toml").write_text("[tool.workspace.architecture]\n", encoding="utf-8")


def test_contracts_reach_no_effect_owner_service_or_qt(tmp_path: Path) -> None:
    # Defect: a shared contract imports an assistant service, a native binding or
    # Qt, so the desktop (or the assistant) loads the other side's effects with it.
    write_tree(
        tmp_path,
        {
            "contracts/__init__.py": "",
            "contracts/values.py": (
                "import json\nfrom pydantic import TypeAdapter\nfrom contracts import other\nfrom winapi.shapes import Rect\nimport protocol\n"
            ),
            "contracts/other.py": "",
            "contracts/leaky.py": "from assistant.store import Store\nlazy import PySide6\nfrom winapi.windows import focus\n",
            "assistant/__init__.py": "",
            "assistant/store.py": "class Store: pass\n",
            "winapi/__init__.py": "",
            "winapi/shapes.py": "class Rect: pass\n",
            "winapi/windows.py": "def focus(): pass\n",
            "protocol.py": "",
        },
    )
    found = [failure for failure in review(tmp_path).failures if failure.rule == "contract-isolation"]
    assert {failure.module for failure in found} == {"contracts.leaky"}
    reached = {failure.detail.split(" → ")[-1] for failure in found}
    assert {"assistant.store", "PySide6", "winapi.windows"} <= reached


def test_the_desktop_and_the_assistant_reach_each_other_only_through_contracts(tmp_path: Path) -> None:
    # Defect: a desktop module imports an assistant owner (or the assistant imports
    # Qt or a view), even through a third module, so one program can no longer run
    # or restart without the other.
    write_tree(
        tmp_path,
        {
            "contracts/__init__.py": "",
            "contracts/values.py": "",
            "desktop_ui/__init__.py": "",
            "desktop_ui/view.py": "from contracts import values\nimport helper\n",
            "helper.py": "lazy import assistant.store\n",
            "assistant/__init__.py": "",
            "assistant/store.py": "",
            "assistant/owner.py": "from contracts import values\nlazy import PySide6\n",
        },
    )
    found = {failure.module for failure in review(tmp_path).failures if failure.rule == "process-isolation"}
    assert found == {"desktop_ui.view", "assistant.owner"}


def exception(root: Path, *, reason: str = "Read the optional native error code.") -> None:
    with (root / "pyproject.toml").open("a", encoding="utf-8") as output:
        output.write(
            "\n[[tool.workspace.architecture.exceptions]]\n"
            'rule = "explicit-attributes"\nmodule = "native"\ndeclaration = "Owner.read"\n'
            "expression = \"getattr(error, 'winerror', None)\"\nreason = " + json.dumps(reason) + "\n"
        )


def test_recursive_inventory_excludes_dependencies_and_honors_checked_names(tmp_path: Path) -> None:
    write_tree(
        tmp_path,
        {
            "assistant/__init__.py": "",
            "assistant/feed/__init__.py": "",
            "assistant/feed/model.py": "",
            "runtime.py": "",
            "scripts/owner.py": "",
            ".venv/package.py": "",
            ".runtime/package.py": "",
            "__pycache__/ignored.py": "",
        },
    )
    assert python_sources(tmp_path) == (
        "assistant/__init__.py",
        "assistant/feed/__init__.py",
        "assistant/feed/model.py",
        "runtime.py",
        "scripts/owner.py",
    )
    assert python_sources(tmp_path, ("runtime.py", "deleted.py")) == ("runtime.py",)


def test_keyboard_rejection_follows_lazy_imports_and_package_initializers(tmp_path: Path) -> None:
    write_tree(
        tmp_path,
        {
            "miryoku/__init__.py": "",
            "miryoku/engine.py": "lazy from helper.values import value\n",
            "helper/__init__.py": "from desktop_ui import model\n",
            "helper/values.py": "value = 1\n",
            "assistant/__init__.py": "",
            "assistant/model.py": "",
            "desktop_ui/__init__.py": "",
            "desktop_ui/model.py": "",
        },
    )
    report = review(tmp_path)
    assert report.failures and all(finding.rule == "keyboard-isolation" for finding in report.failures)
    assert any("miryoku.engine → helper → desktop_ui" in finding.detail for finding in report.failures)
    (tmp_path / "helper/__init__.py").write_text("")
    assert not review(tmp_path).failures


def test_relative_lazy_and_aliased_dynamic_imports_select_their_consumers() -> None:
    imported = dependencies(
        "app/nested/owner.py", 'lazy from .. import model\nfrom importlib import import_module as load\nload("app.effects.native")\n'
    )
    assert {"app", "app.model", "app.effects", "app.effects.native"} <= imported


def test_keyboard_cannot_hide_dependencies_in_unresolved_dynamic_imports(tmp_path: Path) -> None:
    write_tree(
        tmp_path,
        {
            "miryoku/__init__.py": "",
            "miryoku/engine.py": "from importlib import import_module as load\ndef start(target):\n    return load(target)\n",
        },
    )
    assert [finding.rule for finding in review(tmp_path).failures] == ["keyboard-import"]


def test_data_records_must_be_frozen_and_slotted(tmp_path: Path) -> None:
    write_tree(
        tmp_path,
        {
            "assistant/__init__.py": "",
            "assistant/feed/__init__.py": "",
            "assistant/feed/model.py": "from dataclasses import dataclass as variant\n@variant(slots=True)\nclass Payload:\n    value: str\n",
            "assistant/worker.py": "from dataclasses import dataclass\n@dataclass(frozen=True, slots=True)\nclass Buffer:\n    value: str\n",
        },
    )
    report = review(tmp_path)
    assert [(finding.rule, finding.module, finding.declaration) for finding in report.failures] == [
        ("immutable-data", "assistant.feed.model", "Payload")
    ]
    (tmp_path / "assistant/feed/model.py").write_text(
        "import dataclasses as data\n@data.dataclass(frozen=True, slots=True)\nclass Payload:\n    value: str\n"
    )
    assert not review(tmp_path).failures


def test_a_frozen_record_cannot_hide_a_mutable_collection(tmp_path: Path) -> None:
    write_tree(
        tmp_path,
        {
            "owner.py": "from dataclasses import dataclass\n"
            "@dataclass(frozen=True, slots=True)\nclass Snapshot:\n    values: tuple[dict[str, str], ...]\n"
        },
    )
    assert [(finding.rule, finding.declaration) for finding in review(tmp_path).failures] == [("mutable-field", "Snapshot.values")]


def test_a_function_cannot_require_a_mutable_container_unless_its_base_dictates_it(tmp_path: Path) -> None:
    # Defect: a mutable parameter type hidden in a nested, aliased or variadic annotation passes,
    # or an override, whose base class owns the signature, is rejected.
    write_tree(
        tmp_path,
        {
            "owner.py": "from collections.abc import Callable, Mapping\nfrom typing import List, override\n"
            "def read(values: Mapping[str, int], *rest: tuple[int, ...]) -> None: ...\n"
            "def fill(values: list[int], *, seen: Callable[[set[str]], None], **more: List[int]) -> None: ...\n"
            "class Hook(Base):\n    @override\n    def receive(self, items: list[int]) -> None: ...\n"
            "    async def gather(self, found: dict[str, int] | None = None) -> None: ...\n"
        },
    )
    found = [(finding.rule, finding.declaration, finding.expression) for finding in review(tmp_path).failures]
    assert found == [
        ("mutable-parameter", "fill.values", "list[int]"),
        ("mutable-parameter", "fill.seen", "Callable[[set[str]], None]"),
        ("mutable-parameter", "fill.more", "List[int]"),
        ("mutable-parameter", "Hook.gather.found", "dict[str, int] | None"),
    ]


def test_a_class_that_only_holds_its_inputs_must_be_a_frozen_record(tmp_path: Path) -> None:
    # Defect: a plain class whose __init__ only stores its parameters passes the review
    # (nested in another class too), or an owner of changing state is flagged: one that
    # rebinds an attribute later, builds a lock or container, starts work in __init__,
    # derives from a base, or whose attribute another module assigns.
    owner = """import threading

class Holder:
    \"\"\"Only inputs.\"\"\"

    def __init__(self, path, publish=None):
        self.path, self.publish = path, publish if publish is not None else path

    def read(self):
        self.publish.current = self.path
        return self.path

class Outer:
    class Inner:
        def __init__(self, value):
            self.value: int = value

class Counter:
    def __init__(self, start):
        self.count = start

    def step(self):
        self.count += 1

class Guarded:
    def __init__(self):
        self.lock = threading.Lock()

class Buffered:
    def __init__(self, items):
        self.items = list(items)

class Started:
    def __init__(self, thread):
        self.thread = thread
        thread.start()

class Derived(Base):
    def __init__(self, value):
        self.value = value

class Clock:
    def __init__(self, now):
        self.now = now
"""
    write_tree(tmp_path, {"owner.py": owner, "driver.py": "def step(clock):\n    clock.now += 1\n"})
    found = [(finding.rule, finding.declaration) for finding in review(tmp_path).failures]
    assert found == [("plain-record", "Holder"), ("plain-record", "Outer.Inner")]


def test_exact_reflection_exception_survives_lines_but_cannot_cover_other_declarations(tmp_path: Path) -> None:
    write_tree(tmp_path, {"native.py": '\n\nclass Owner:\n    def read(self, error):\n        return getattr(error, "winerror", None)\n'})
    exception(tmp_path)
    report = review(tmp_path)
    assert not report.failures and len(report.exceptions) == 1
    with (tmp_path / "native.py").open("a") as output:
        output.write('    def other(self, error):\n        return getattr(error, "winerror", None)\n')
    assert [finding.declaration for finding in review(tmp_path).failures] == ["Owner.other"]
    (tmp_path / "native.py").write_text("class Owner:\n    def read(self, error):\n        return error\n")
    assert [finding.rule for finding in review(tmp_path).failures] == ["stale-exception"]


def test_reflection_aliases_are_detected_without_leaking_between_functions(tmp_path: Path) -> None:
    write_tree(
        tmp_path,
        {
            "owner.py": "import builtins as native\n"
            'def first(value):\n    from builtins import getattr as read\n    return read(value, "state")\n'
            'def second(value):\n    read = native.getattr\n    return read(value, "state")\n'
            'def third(value):\n    return native.hasattr(value, "state")\n'
        },
    )
    assert {finding.declaration for finding in review(tmp_path).failures} == {"first", "second", "third"}


def test_unsupported_and_unexplained_exceptions_are_configuration_errors(tmp_path: Path) -> None:
    write_tree(tmp_path, {})
    exception(tmp_path, reason="")
    try:
        review(tmp_path)
    except ValueError:
        pass
    else:
        raise AssertionError("An unexplained exception was accepted.")


def test_explicit_test_scope_cannot_bypass_architecture_or_write_a_receipt(tmp_path: Path) -> None:
    write_tree(
        tmp_path,
        {
            "miryoku/__init__.py": "",
            "miryoku/engine.py": "import assistant\n",
            "assistant/__init__.py": "",
            "tests/test_requested.py": 'def test_requested():\n    raise AssertionError("must not execute")\n',
        },
    )
    copy_check_scripts(tmp_path, ("check.py",))
    initialized(tmp_path)
    receipt = tmp_path / "checked.json"
    result = subprocess.run(
        [sys.executable, "-m", "scripts.check", "--tests", "tests/test_requested.py", "--receipt", str(receipt)],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 1 and "keyboard-isolation" in result.stdout
    assert "must not execute" not in result.stdout and not receipt.exists()


def test_mock_frameworks_and_replacement_fixtures_are_rejected_in_all_sources(tmp_path: Path) -> None:
    cases = (
        'from unittest.mock import patch as replace\nreplace("owner.effect")\n',
        "import unittest.mock as replacement\nreplacement.Mock()\n",
        'from unittest import mock\nmock.patch.object(owner, "effect")\n',
        "from pytest import MonkeyPatch as Replacement\nReplacement()\n",
        'def test_effect(monkeypatch):\n    monkeypatch.setattr(owner, "effect", lambda: None)\n',
        'def test_effect(mocker):\n    mocker.patch("owner.effect")\n',
        'import importlib\nimportlib.import_module("unittest.mock")\n',
    )
    for text in cases:
        write_tree(tmp_path, {"owner.py": text, "tests/test_owner.py": text})
        failures = review(tmp_path).failures
        assert {finding.module for finding in failures if finding.rule == "testing-dependencies"} == {"owner", "tests.test_owner"}
    write_tree(
        tmp_path,
        {
            "owner.py": "def observe(reader):\n    return reader()\n",
            "tests/test_owner.py": "from owner import observe\ndef test_read():\n    assert observe(lambda: 7) == 7\n",
        },
    )
    assert not review(tmp_path).failures


def test_a_match_that_only_maps_enum_members_to_constants_must_be_a_table(tmp_path: Path) -> None:
    # Defect: a member-to-constant `match` slips past the review because one
    # case joins members with `|`, a wildcard covers the rest, or it sits in a
    # method; or a `match` whose cases use the function's own values (a
    # parameter, `self`, a local or a nested function's parameter) is wrongly
    # flagged although no table could hold them.
    source = """from enum import Enum

class Light(Enum):
    RED = 1
    AMBER = 2
    GREEN = 3

def label(light: Light) -> str:
    match light:
        case Light.RED | Light.AMBER:
            return "stop"
        case Light.GREEN:
            return "go"

class Lamp:
    def colour(self, light: Light) -> Rgb:
        match light:
            case Light.RED:
                value = Rgb(255, 0)
            case Light.GREEN:
                value = Rgb(0, 255)
            case _:
                value = Rgb(0, 0)
        return value

def inset(light: Light, bounds: Box) -> Box:
    match light:
        case Light.RED:
            return bounds.adjusted(1)
        case Light.GREEN:
            return bounds.adjusted(2)

def outer() -> None:
    def inner(scale: int, light: Light) -> int:
        match light:
            case Light.RED:
                return scale
            case Light.GREEN:
                return -scale
"""
    write_tree(tmp_path, {"lights.py": source})
    found = [(finding.rule, finding.declaration, finding.expression) for finding in review(tmp_path).failures]
    assert found == [("enum-translation", "label", "light"), ("enum-translation", "Lamp.colour", "light")]


def test_a_fixed_tuple_of_numbers_must_be_a_named_type(tmp_path: Path) -> None:
    # Defect: a point, size or span passed as `tuple[int, int]` swaps its fields
    # or skips its bounds unnoticed, and the review misses it inside a method,
    # a mapping's key or a type alias; or it wrongly flags a variable-length
    # tuple of numbers or a pair that holds other types.
    source = """class Overlay:
    def move(self, position: tuple[int, int]) -> None: ...

SIZES: frozendict[tuple[int, int], str] = frozendict()
type Span = tuple[float, float]
samples: tuple[float, ...] = ()
pressed: tuple[str, str] = ("", "")
"""
    write_tree(tmp_path, {"overlay.py": source})
    found = [(finding.rule, finding.declaration, finding.expression) for finding in review(tmp_path).failures]
    assert found == [
        ("bare-tuple", "Overlay.move", "tuple[int, int]"),
        ("bare-tuple", "", "tuple[int, int]"),
        ("bare-tuple", "", "tuple[float, float]"),
    ]


def test_a_function_never_fills_a_local_container_in_a_loop(tmp_path: Path) -> None:
    # Defect: a collection built by appending, adding or index-assigning in a
    # loop slips past the review (or is reported twice from a nested function);
    # or a loop that only performs side effects, an owner updating its own
    # state, or a comprehension is wrongly flagged.
    source = """def names(items):
    found = []
    for item in items:
        found.append(item.name)
    return found

def index(items):
    by_id = {}
    for item in items:
        by_id[item.id] = item
    return by_id

def outer(items):
    def inner(values):
        seen = set()
        while values:
            seen.add(values.pop())
        return seen
    return inner(items)

def announce(items, sink):
    for item in items:
        sink.send(item)

class Owner:
    def take(self, items):
        for item in items:
            self.items.append(item)

def built(items):
    return tuple(item.name for item in items)
"""
    write_tree(tmp_path, {"collect.py": source})
    found = [(finding.rule, finding.module, finding.declaration, finding.expression) for finding in review(tmp_path).failures]
    assert found == [
        ("loop-accumulation", "collect", "names", "found"),
        ("loop-accumulation", "collect", "index", "by_id"),
        ("loop-accumulation", "collect", "outer.inner", "seen"),
    ]
