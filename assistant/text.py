"""Making dictated text safe before it's typed."""


def typed_text(transcript: str) -> str:
    """What to type for dictation: one line, with a space after it so the next
    dictation doesn't run into this one. Newlines become spaces (a newline would
    press Enter, and in a terminal run the command); control characters go."""
    line = " ".join("".join(c for c in transcript if c.isprintable() or c.isspace()).split())
    return f"{line} " if line else ""
