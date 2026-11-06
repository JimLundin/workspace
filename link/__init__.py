"""Loopback links between Workspace's programs: published endpoints and framed messages.

A program that serves publishes its port and a per-boot token in the keeper's
state folder (`endpoint`); a client reads them, connects and proves the token.
`server` and `client` carry length-prefixed frames of bytes; the messages in
them belong to `contracts`. Standard library and pydantic only.
"""
