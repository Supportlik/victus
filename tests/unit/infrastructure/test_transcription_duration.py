"""T-DOM-087: the length of a recording is read out of what ffmpeg printed.

The transcription provider only reports a duration for the `whisper-*` models, which answer
in verbose JSON; the `gpt-4o-*` transcribers return the text alone. So for the configured
model `duration_s` was always null, the cost derived from it was always null, and the card
had no length to print. The player could not fill in for it either: a recording the
browser's MediaRecorder produced carries no duration in its header, which is why the
control shows 0:00 until the file has played to the end.

`Duration:` in ffmpeg's banner is read from that same header and is therefore `N/A` for
exactly these files. The progress lines are not — they say how far the decoder actually
got, so the last one is the length.
"""

from __future__ import annotations

import pytest

from victus.infrastructure.transcription.openai_transcribe import duration_from_ffmpeg

pytestmark = pytest.mark.domain

#: What ffmpeg prints for a voice note the browser recorded: no length in the header,
#: and the truth in the last progress line.
HEADERLESS_WEBM = """\
Input #0, matroska,webm, from 'input.webm':
  Metadata:
    encoder         : Chrome
  Duration: N/A, start: 0.000000, bitrate: N/A
  Stream #0:0(eng): Audio: opus, 48000 Hz, mono, fltp (default)
Stream mapping:
  Stream #0:0 -> #0:0 (opus (native) -> pcm_s16le (native))
size=       0kB time=00:00:00.00 bitrate=N/A speed=N/A
size=    2048kB time=00:00:21.44 bitrate= 782.4kbits/s speed=42.9x
size=    4022kB time=00:00:42.11 bitrate= 782.4kbits/s speed=43.1x
[out#0/null @ 000001] video:0kB audio:4022kB subtitle:0kB
"""


def test_the_last_progress_line_is_the_length() -> None:
    assert duration_from_ffmpeg(HEADERLESS_WEBM) == 42.11


def test_hours_and_minutes_add_up() -> None:
    assert duration_from_ffmpeg("time=01:02:03.50 bitrate=1") == 3723.5


def test_no_progress_at_all_is_no_length() -> None:
    """A file ffmpeg refused says nothing about how long it is."""
    assert duration_from_ffmpeg("input.webm: Invalid data found when processing input") is None


def test_a_recording_of_nothing_is_not_a_length() -> None:
    """Zero would be printed as a length, and "0:00" is the very thing being fixed."""
    assert duration_from_ffmpeg("size=0kB time=00:00:00.00 bitrate=N/A") is None
