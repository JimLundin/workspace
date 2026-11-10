"""Run the AI connection: `pythonw -m gateway`. The keeper starts it before the
other programs and ends it on stop; it holds no state of its own.

It imports only `protocol`, `settings.programs` and its own modules, so a deploy that
changes the rest of Workspace leaves it, and the provider connection that
dictation, meetings and the agent share, running.
"""

import os
import secrets

from protocol import Places
from settings import programs
lazy from gateway.endpoint import Endpoint, publish, read
lazy from gateway.proxy import Gateway
lazy from gateway.upstream import upstream_from


def main() -> None:
    path = Places.of(os.environ, programs.PROGRAMS).gateway_endpoint
    previous = None if path is None else read(path)
    token = secrets.token_urlsafe(32) if previous is None else previous.token
    gateway = Gateway.listen(upstream_from(os.environ), token, port=0 if previous is None else previous.port)
    if path is not None:
        publish(path, Endpoint(gateway.port, token))
    gateway.serve()


if __name__ == "__main__":
    main()
