"""What a meeting recording captures: the microphone alone, or with the computer's audio."""

from typing import Literal

type AudioSource = Literal["both", "microphone"]
