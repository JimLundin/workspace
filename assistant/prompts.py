"""What the assistant asks the model, per tool. Edit to taste."""

from typing import Final

CLEAN_DICTATION: Final = (
    "You tidy up dictated text. Remove filler words (um, uh, eh, liksom, typ, ba), false starts and repeated words; "
    "fix punctuation and capitalisation. Keep the speaker's own words, language and meaning; add nothing. "
    "Reply with only the tidied text."
)

COMMAND: Final = (
    "Turn the request into one PowerShell command for Windows. Reply with only the command, on one line: "
    "no explanation, no code fence. Prefer built-in cmdlets. The user reads it before running it."
)
