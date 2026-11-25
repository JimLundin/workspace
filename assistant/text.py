def typed_text(transcript: str) -> str:
    line = " ".join(
        "".join(c for c in transcript if c.isprintable() or c.isspace()).split()
    )
    return f"{line} " if line else ""
