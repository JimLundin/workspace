"""Current browser capabilities through the agent and its real durable journal."""

import json
from pathlib import Path
from typing import cast
from unittest import TestCase

from pydantic import TypeAdapter, ValidationError

from assistant.browser_requests import Open, OpenHidden
from assistant.browser_tools import OpenArguments, open_request
from assistant.browser_values import BrowserError, BrowserStatus
from tests.fake_endpoint import fake_endpoint
from tests.test_agent import Rig, ToolRig, calls, durable, says


def test_model_receives_only_current_browser_capabilities(tmp_path: Path) -> None:
    with fake_endpoint() as endpoint:
        rig = Rig(
            endpoint,
            calls(("browser_tabs", {})),
            calls(("browser_open", {"url": "https://example.com/"})),
            says("Tabs inspected."),
            work=durable(tmp_path),
        )
        rig.run()
        data: object = json.loads(endpoint.received[0].body)
        assert isinstance(data, dict)
        tools = cast("list[dict[str, object]]", cast("dict[str, object]", data)["tools"])
        names = {str(tool["name"]) for tool in tools}
        assert {"browser_open", "browser_tabs", "browser_snapshot", "browser_action"} <= names
        assert "browser_attach" not in names
        assert "source=<Separate.PROFILE:" in rig.machine.log[-1]
        assert not any(name.startswith("browser_app_") for name in names)
        assert rig.machine.log[0] == "browser PageList(offset=0, limit=20)"


def test_invisible_pages_require_explicit_selection_and_preserve_exact_target_visibility() -> None:
    # Defect: changing the default to hidden breaks workflows requiring a
    # rendering surface, or navigation silently changes an existing tab's mode.
    url = "https://example.com"
    assert open_request(OpenArguments(url)) == Open(url)
    assert open_request(OpenArguments(url, visibility="tab")) == Open(url)
    assert open_request(OpenArguments(url, visibility="hidden")) == OpenHidden(url)
    assert open_request(OpenArguments(url, target_id="existing")) == Open(url, target_id="existing")
    with TestCase().assertRaises(BrowserError):
        open_request(OpenArguments(url, target_id="existing", visibility="tab"))
    with TestCase().assertRaises(ValidationError):
        TypeAdapter(OpenArguments).validate_python({"url": url, "visibility": "invisible"})


def test_only_a_complete_listing_proves_unlisted_pages_closed(tmp_path: Path) -> None:
    # Defect: a paged listing marks every omitted page as closed, letting an
    # unrelated observation reconcile a pending close.
    readback = ToolRig(work=durable(tmp_path)).agent.tools["browser_tabs"].readback

    def pages(following: int | None) -> str:
        return TypeAdapter(BrowserStatus).dump_json(BrowserStatus("background", (), next_offset=following), exclude_none=True).decode()

    assert readback({}, pages(None)).resources == ("all:browser-page",)
    assert readback({}, pages(1)).resources == ()
    assert readback({"offset": 1}, pages(None)).resources == ()
