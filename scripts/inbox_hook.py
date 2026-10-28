"""The CLI hook entry point. An unavailable Workspace leaves the ordinary console prompt alone."""

import json
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


def main() -> None:
    provider = "Claude Code" if "--claude" in sys.argv else "Codex"
    profile = Path(os.environ.get("LOCALAPPDATA", "")) / "workspace" / "inbox-bridge.json"
    try:
        raw = sys.stdin.buffer.read(64_001)
        if len(raw) > 64_000:
            return
        event: object = json.loads(raw)
        endpoint: object = json.loads(profile.read_text(encoding="utf-8"))
        match endpoint:
            case {"url": str() as url, "token": str() as token}:
                pass
            case _:
                return
        location = urlsplit(url)
        if location.scheme != "http" or location.hostname != "127.0.0.1" or location.path != "/request":
            return
        payload = json.dumps({"provider": provider, "event": event}).encode("utf-8")
        request = Request(url, data=payload, headers={"Authorization": "Bearer " + token,
                                                               "Content-Type": "application/json"})
        with urlopen(request, timeout=575) as response:
            output = response.read(128_001)
        if len(output) <= 128_000:
            sys.stdout.buffer.write(output)
            sys.stdout.buffer.flush()
    except (OSError, ValueError, KeyError):
        pass  # Never add a broken prompt, log private data, or approve by default.


if __name__ == "__main__":
    main()
