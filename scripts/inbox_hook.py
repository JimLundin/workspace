"""The CLI hook entry point. An unavailable Workspace leaves the ordinary console prompt alone."""

import json
import os
import sys
from http.client import HTTPResponse
from io import BufferedReader, BufferedWriter, TextIOWrapper
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


def main() -> None:
    provider = "Claude Code" if "--claude" in sys.argv else "Codex"
    profile = Path(os.environ.get("LOCALAPPDATA", "")) / "workspace" / "inbox-bridge.json"
    try:
        match sys.stdin, sys.stdout:
            case TextIOWrapper() as incoming, TextIOWrapper() as outgoing:
                pass
            case _:
                return
        input_buffer: object = incoming.buffer
        output_buffer: object = outgoing.buffer
        match input_buffer, output_buffer:
            case BufferedReader() as source, BufferedWriter() as destination:
                pass
            case _:
                return
        raw = source.read(64_001)
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
        message: dict[str, object] = {"provider": provider, "event": event}
        payload = json.dumps(message).encode("utf-8")
        request = Request(url, data=payload, headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
        response: object = urlopen(request, timeout=575)
        match response:
            case HTTPResponse():
                with response:
                    output = response.read(128_001)
            case _:
                return
        if len(output) <= 128_000:
            destination.write(output)
            destination.flush()
    except OSError, ValueError, KeyError:
        pass  # Never add a broken prompt, log private data, or approve by default.


if __name__ == "__main__":
    main()
