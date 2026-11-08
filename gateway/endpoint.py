"""How a client reaches the AI connection: its loopback port and this boot's token.

The gateway writes the file once it listens and leaves it when it exits, so a
restarted gateway can take the same port and token back and clients built
before the restart keep working.
"""

from dataclasses import dataclass
from pathlib import Path

from pydantic import TypeAdapter, ValidationError


@dataclass(frozen=True, slots=True)
class Endpoint:
    port: int
    token: str
    """The only credential a client holds; the gateway adds the provider's key."""

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/v1"


_ENDPOINT = TypeAdapter(Endpoint)


def read(path: Path) -> Endpoint | None:
    """The published endpoint; None before the gateway first listens."""
    try:
        return _ENDPOINT.validate_json(path.read_bytes())
    except OSError, ValidationError:
        return None


def publish(path: Path, endpoint: Endpoint) -> None:
    """Replace the file whole, so a reader never sees half of it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".partial")
    partial.write_bytes(_ENDPOINT.dump_json(endpoint))
    partial.replace(path)
