"""Typed records at the checked release, process and receipt boundaries."""

from typing import Literal, NotRequired, TypedDict

from pydantic import TypeAdapter

Role = Literal['keeper', 'assistant', 'automation', 'miryoku', 'runtime']


class Config(TypedDict):
    kind: str
    stage_id: str
    live_windows: str
    archive_windows: str
    profile_windows: str
    helpers: dict[str, str]
    source_manifest_sha256: str
    payload_sha256: str
    check_sha256: str
    pins: dict[str, str]
    created_at_ns: int


class Prepared(TypedDict):
    stage_id: str
    manifest_sha256: str
    old_archive_sha256: str
    new_archive_sha256: str
    runtime: dict[str, str]
    runtime_fingerprint: dict[str, list[int]]
    runtime_audit_reused: bool
    old_source: dict[str, str]
    source_before: dict[str, str]
    unrelated_source: dict[str, str]
    runtime_directory_ids: dict[str, list[int]]
    prepared_at_ns: int


class Identity(TypedDict):
    pid: int
    parent_pid: int
    role: Role
    executable: str
    created_ms: int


class Exit(Identity):
    exit_code: int
    observed_at_ns: int


class Stopped(TypedDict):
    stage_id: NotRequired[str]
    was_running: bool
    clean_exit: bool
    processes_before: list[Identity]
    exits: list[Exit]
    bar_was_visible: NotRequired[bool]
    requested_at_ns: NotRequired[int]
    completed_at_ns: NotRequired[int]
    transient_exits: NotRequired[list[dict[str, object]]]


class Ready(TypedDict):
    core: dict[str, Identity]
    markers: dict[str, int]


class RunningReload(TypedDict):
    was_running: Literal[True]
    keeper_pid: int
    started_at_ns: int
    core: dict[str, Identity]
    verified_at_ns: int


class StoppedReload(TypedDict):
    was_running: Literal[False]
    left_stopped: Literal[True]


type Reloaded = RunningReload | StoppedReload


class RuntimeAudit(TypedDict):
    runtime: dict[str, str]
    fingerprint: dict[str, list[int]]
    archive_sha256: str
    verified_stage: str


CONFIG = TypeAdapter[Config](Config)
PREPARED = TypeAdapter[Prepared](Prepared)
STOPPED = TypeAdapter[Stopped](Stopped)
RELOADED = TypeAdapter[Reloaded](Reloaded)
RUNTIME_AUDIT = TypeAdapter[RuntimeAudit](RuntimeAudit)
