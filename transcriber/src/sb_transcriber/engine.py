"""Speech to text with faster-whisper (CTranslate2) on an NVIDIA GPU.

A long file (an audiobook can be one file of 20 hours) is not decoded at once (that would
be gigabytes of samples): it is read in chunks of CHUNK_SECONDS, each cut at the quietest
moment near its end so that no word is split, and transcribed in turn.
"""

# faster-whisper, PyAV and numpy have partial type information.
# pyright: basic

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sb_transcriber.config import MODELS
from sb_transcriber.cuda import add_nvidia_libraries
from sb_transcriber.lines import Segment, Word, to_lines

SAMPLE_RATE = 16_000  # what Whisper takes
CHUNK_SECONDS = 30 * 60
SEARCH_SECONDS = 15  # where to look for a quiet moment, at the end of a chunk
QUIET_WINDOW = SAMPLE_RATE // 10  # 0.1 s
LANGUAGE_DETECTION_SEGMENTS = 6  # of 30 s


@dataclass
class Result:
    language: str | None
    lines: list[dict[str, Any]]


def _quiet_point(samples: Any, start: int) -> int:
    """The quietest 0.1 s window from `start` to the end: where to cut."""
    import numpy as np

    tail = samples[start:]
    windows = len(tail) // QUIET_WINDOW
    if windows < 2:
        return len(samples)
    energy = np.abs(tail[: windows * QUIET_WINDOW].astype(np.float32)).reshape(windows, -1).sum(1)
    return start + int(np.argmin(energy)) * QUIET_WINDOW + QUIET_WINDOW // 2


def audio_chunks(path: Path) -> Iterator[tuple[float, Any]]:
    """(offset in seconds, float32 mono 16 kHz samples), chunk after chunk."""
    import av
    import numpy as np

    chunk = CHUNK_SECONDS * SAMPLE_RATE
    search = SEARCH_SECONDS * SAMPLE_RATE
    offset = 0
    pending: list[Any] = []
    buffered = 0

    def cut(final: bool) -> Iterator[tuple[float, Any]]:
        nonlocal pending, buffered, offset
        samples = np.concatenate(pending) if len(pending) > 1 else pending[0]
        end = len(samples) if final else _quiet_point(samples, chunk)
        yield offset / SAMPLE_RATE, samples[:end].astype(np.float32) / 32768.0
        offset += end
        rest = samples[end:]
        pending, buffered = ([rest], len(rest)) if len(rest) else ([], 0)

    with av.open(str(path), metadata_errors="ignore") as container:
        stream = container.streams.audio[0]
        resampler = av.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
        for frame in container.decode(stream):
            for resampled in resampler.resample(frame):
                samples = resampled.to_ndarray().reshape(-1)
                pending.append(samples)
                buffered += len(samples)
            if buffered >= chunk + search:
                yield from cut(final=False)
        for resampled in resampler.resample(None):  # what the resampler still holds
            samples = resampled.to_ndarray().reshape(-1)
            pending.append(samples)
            buffered += len(samples)
    if buffered:
        yield from cut(final=True)


class Engine:
    def __init__(self, model: str, gpu: int, compute_type: str, batch_size: int) -> None:
        add_nvidia_libraries()
        from faster_whisper import BatchedInferencePipeline, WhisperModel

        self.name = f"whisper {model}"
        self._batch_size = batch_size
        self._model = WhisperModel(
            model,
            device="cuda",
            device_index=gpu,
            compute_type=compute_type,
            download_root=str(MODELS),
        )
        self._batched = BatchedInferencePipeline(self._model) if batch_size > 1 else None

    def _segments(self, samples: Any, language: str | None) -> tuple[Iterator[Any], Any]:
        common = {
            "language": language,
            "word_timestamps": True,
            "vad_filter": True,
            # Detected on 3 minutes of speech, not the first 30 s (a title, a jingle).
            "language_detection_segments": LANGUAGE_DETECTION_SEGMENTS,
        }
        if self._batched is not None:
            return self._batched.transcribe(samples, batch_size=self._batch_size, **common)
        # One by one: not conditioned on the previous text, which can loop on hours of audio.
        return self._model.transcribe(samples, condition_on_previous_text=False, **common)

    def transcribe(
        self,
        path: Path,
        duration_seconds: float,
        language: str | None,
        on_progress: Callable[[float], None],
    ) -> Result:
        """`language`: None to detect it (on the first chunk, then kept for the others)."""
        segments: list[Segment] = []
        for offset, samples in audio_chunks(path):
            found, info = self._segments(samples, language)
            language = language or info.language
            for segment in found:
                segments.append(
                    Segment(
                        offset + segment.start,
                        offset + segment.end,
                        segment.text,
                        [
                            Word(offset + w.start, offset + w.end, w.word)
                            for w in segment.words or []
                        ],
                    )
                )
                if duration_seconds > 0:
                    on_progress(min((offset + segment.end) / duration_seconds, 0.99))
        return Result(language, to_lines(segments))
