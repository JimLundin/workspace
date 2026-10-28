"""Teams reconnects and actions must reuse one tab, without launching Edge."""

import threading
from contextlib import nullcontext
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from assistant.browser import Browser, Product
from assistant.browser_values import BrowserError
from assistant.communications_browser import Observation, TeamsWeb

from .test_browser_host import Opener


def web(folder: Path) -> TeamsWeb:
    result = TeamsWeb(folder)
    result.browser = Browser(folder, source=Product.EDGE, opener=Opener())
    return result


def test_reconnect_reuses_existing_teams_when_saved_target_has_expired(tmp_path: Path) -> None:
    # A stale CDP ID must not allocate another Teams tab on every reconnect.
    cancel = threading.Event()
    rows = ({'id': 'existing', 'url': 'https://teams.cloud.microsoft/v2/'},)
    with patch.object(TeamsWeb, 'pages', return_value=rows), patch.object(
        Browser, 'request', side_effect=AssertionError('Teams must reuse the existing tab'),
    ):
        for _ in range(3):
            current = web(tmp_path)
            assert current.connect('expired', cancel) == 'existing'
            assert current.connect('existing', cancel) == 'existing'
            current.close()


def test_activity_and_open_share_the_selected_teams_tab(tmp_path: Path) -> None:
    # Splitting inspection/activity from collection would create extra tabs.
    current = web(tmp_path)
    current.target = 'existing'
    cancel = threading.Event()
    rows = ({'id': current.target, 'url': 'https://teams.cloud.microsoft/v2/'},)
    with (patch.object(TeamsWeb, 'pages', return_value=rows),
          patch.object(TeamsWeb, 'available', return_value=True),
          patch.object(TeamsWeb, 'evaluate', return_value={'ready': True, 'items': []}),
          patch.object(TeamsWeb, 'select', return_value=Observation('', '', (), (), False)) as select,
          patch.object(Browser, 'awake', return_value=nullcontext()) as awake,
          patch.object(Browser, 'activate_page') as activate,
          patch.object(Browser, 'request', side_effect=AssertionError('No extra Teams tab'))):
        assert current.activity(cancel).items == ()
        awake.assert_called_with(current.target, cancel)
        current.open('19:one@thread.v2', cancel)
        select.assert_called_once_with('19:one@thread.v2', cancel, target=current.target)
        activate.assert_called_once_with(current.target, cancel)


def test_connect_without_an_existing_teams_tab_does_not_open_one(tmp_path: Path) -> None:
    # Automatic recovery must not turn a closed Teams tab into more tabs.
    current = web(tmp_path)
    with (patch.object(TeamsWeb, 'pages', return_value=()),
          patch.object(Browser, 'request', side_effect=AssertionError('No automatic tab creation')),
          TestCase().assertRaisesRegex(BrowserError, 'Open Teams')):
        current.connect('', threading.Event())
    current.close()


def test_visible_shared_tab_pauses_activity_before_navigation(tmp_path: Path) -> None:
    # Background Activity must not switch the page the user is currently reading.
    current = web(tmp_path)
    current.target = 'existing'
    cancel = threading.Event()
    current.browser.connect(cancel)
    rows = ({'id': current.target, 'url': 'https://teams.cloud.microsoft/v2/'},)
    with (patch.object(TeamsWeb, 'pages', return_value=rows),
          patch.object(TeamsWeb, 'evaluate', return_value='visible'),
          patch.object(Browser, 'awake') as awake,
          TestCase().assertRaisesRegex(BrowserError, 'paused')):
        current.activity(cancel)
    awake.assert_not_called()
    current.close()
