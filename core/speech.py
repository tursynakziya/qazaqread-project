"""
Server-side Kazakh speech recognition (offline, Vosk).

The reading page first tries to recognise speech in the browser (Web Speech
API, kk-KZ). That only works in Chrome/Edge with internet access, so when the
browser sends no transcript the server recognises the recording itself.

Setup (already done in this project):

    pip install vosk imageio-ffmpeg
    # Kazakh model unpacked into models/, e.g. models/vosk-model-small-kz-0.42
    # https://alphacephei.com/vosk/models

QAZAQREAD_VOSK_MODEL may point to another model folder. ffmpeg is taken from
PATH or, failing that, from the imageio-ffmpeg package.

If anything is missing, transcribe() returns "" and the session is marked
for teacher review.
"""

import json
import logging
import os
import shutil
import subprocess
import threading
import time
import wave
from pathlib import Path

from django.conf import settings

logger = logging.getLogger(__name__)

_model = None
_model_lock = threading.Lock()


def model_path():
    path = os.environ.get("QAZAQREAD_VOSK_MODEL")
    if path:
        return path if os.path.isdir(path) else None
    models_dir = Path(settings.BASE_DIR) / "models"
    found = sorted(models_dir.glob("vosk-model*kz*")) if models_dir.is_dir() else []
    return str(found[-1]) if found else None


def ffmpeg_path():
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg
    except ImportError:
        return None
    return imageio_ffmpeg.get_ffmpeg_exe()


def is_available():
    try:
        import vosk  # noqa: F401
    except ImportError:
        return False
    return bool(model_path() and ffmpeg_path())


def _get_model():
    global _model
    with _model_lock:
        if _model is None:
            from vosk import Model, SetLogLevel

            SetLogLevel(-1)
            _model = Model(model_path())
        return _model


def text_grammar(body):
    """
    Words the recogniser may choose from while a student reads `body`.

    Limiting recognition to the text's own words (plus "[unk]" for anything
    else) makes it far more reliable on children's and noisy speech; a
    misread word comes out as "[unk]" or as a different word, so it is still
    counted as an error.
    """
    from .models import split_words

    words = set()
    for word in split_words(body):
        words.update(p for p in word.lower().replace("ё", "е").split("-") if p)
    return sorted(words) + [UNKNOWN]


UNKNOWN = "[unk]"


def _recognizer(grammar=None):
    from vosk import KaldiRecognizer

    if grammar:
        return KaldiRecognizer(_get_model(), 16000, json.dumps(grammar, ensure_ascii=False))
    return KaldiRecognizer(_get_model(), 16000)


# With a grammar the recogniser always picks one of the text's words; a guess it
# is unsure about is more likely a misread word, so it is reported as unknown.
MIN_CONFIDENCE = 0.5


def _confident_words(results):
    for result in results:
        for word in result.get("result", []):
            yield word["word"] if word.get("conf", 1) >= MIN_CONFIDENCE else UNKNOWN


def transcribe(audio_path, grammar=None):
    if not is_available():
        return ""

    wav_path = f"{audio_path}.wav"
    try:
        subprocess.run(
            [ffmpeg_path(), "-y", "-loglevel", "error", "-i", audio_path, "-ac", "1", "-ar", "16000", "-f", "wav", wav_path],
            check=True,
            timeout=120,
            capture_output=True,
        )
        recognizer = _recognizer(grammar)
        recognizer.SetWords(True)
        results = []
        with wave.open(wav_path, "rb") as wav:
            while chunk := wav.readframes(4000):
                if recognizer.AcceptWaveform(chunk):
                    results.append(json.loads(recognizer.Result()))
        results.append(json.loads(recognizer.FinalResult()))
        return " ".join(_confident_words(results))
    except Exception:
        logger.exception("Server-side transcription failed")
        return ""
    finally:
        if os.path.exists(wav_path):
            os.remove(wav_path)


# ---------------------------------------------------------------------------
# Live recognition while the student reads.
#
# The reading page streams 16 kHz mono PCM (16-bit little-endian) in small
# chunks; each live session keeps its own recogniser in memory, so this works
# with a single server process (runserver, or one gunicorn worker with threads).

LIVE_IDLE_SECONDS = 120
LIVE_MAX_SESSIONS = 60
_live = {}
_live_lock = threading.Lock()


class _LiveSession:
    def __init__(self, grammar=None):
        self.recognizer = _recognizer(grammar)
        self.final = []
        self.lock = threading.Lock()
        self.touched = time.monotonic()

    def feed(self, pcm):
        with self.lock:
            self.touched = time.monotonic()
            partial = ""
            if pcm:
                if self.recognizer.AcceptWaveform(pcm):
                    text = json.loads(self.recognizer.Result()).get("text", "")
                    if text:
                        self.final.append(text)
                else:
                    partial = json.loads(self.recognizer.PartialResult()).get("partial", "")
            return " ".join(self.final + ([partial] if partial else []))

    def close(self):
        with self.lock:
            text = json.loads(self.recognizer.FinalResult()).get("text", "")
            if text:
                self.final.append(text)
            return " ".join(self.final)


def live_feed(key, pcm, final=False, grammar=None):
    """Feed a chunk of audio to the live session `key`; returns the text heard so far."""
    now = time.monotonic()
    with _live_lock:
        for k in [k for k, s in _live.items() if now - s.touched > LIVE_IDLE_SECONDS]:
            del _live[k]
        session = _live.get(key)
        if session is None:
            # A new session for this student replaces their previous one.
            for k in [k for k in _live if k[0] == key[0]]:
                del _live[k]
            if len(_live) >= LIVE_MAX_SESSIONS:
                return None
            session = _live[key] = _LiveSession(grammar)
    text = session.feed(pcm)
    if final:
        with _live_lock:
            _live.pop(key, None)
        text = session.close()
    return text
