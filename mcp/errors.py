"""Errors a tool may raise on purpose. The gateway turns them into answers."""


class BadArguments(Exception):
    """The caller's arguments are not usable. The message is shown to the agent,
    so it must never contain secrets."""
