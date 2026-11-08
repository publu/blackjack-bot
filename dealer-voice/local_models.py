"""Local STT (faster-whisper) and TTS (Kokoro ONNX) as LiveKit Agents plugins.

Both run on the Halo CPU. No cloud inference, no network calls.
"""
import asyncio
import logging
import os
import re
import threading
import time
import uuid
from pathlib import Path

import numpy as np
from livekit import rtc
from livekit.agents import stt, tts, APIConnectOptions, DEFAULT_API_CONNECT_OPTIONS
from livekit.agents.language import LanguageCode
from livekit.agents.types import NOT_GIVEN, NotGivenOr

log = logging.getLogger('blackjack-voice')
MODELS = Path(__file__).parent / 'models'
WHISPER_MODEL = os.environ.get('BJ_WHISPER', 'small.en')
# Biases recognition toward the closed vocabulary. The parser still decides what acts.
PROMPT = 'Blackjack table. Deal. Hit. Stand. Double down. Split. Bet twenty five.'


def load_whisper():
    from faster_whisper import WhisperModel
    return WhisperModel(WHISPER_MODEL, device='cpu', compute_type='int8', cpu_threads=8)


def load_kokoro():
    from kokoro_onnx import Kokoro
    return Kokoro(str(MODELS / 'kokoro-v1.0.onnx'), str(MODELS / 'voices-v1.0.bin'))


def to_16k_mono(frame: rtc.AudioFrame) -> np.ndarray:
    pcm = np.frombuffer(frame.data, dtype=np.int16).astype(np.float32) / 32768.0
    if frame.num_channels > 1:
        pcm = pcm.reshape(-1, frame.num_channels).mean(axis=1)
    if frame.sample_rate != 16000 and len(pcm):
        n = int(round(len(pcm) * 16000 / frame.sample_rate))
        pcm = np.interp(np.linspace(0, len(pcm) - 1, n), np.arange(len(pcm)), pcm).astype(np.float32)
    return pcm


def transcribe(model, audio: np.ndarray) -> str:
    """Whisper on one VAD segment. Drops segments that look like non-speech."""
    if len(audio) < 16000 * 0.15:
        return ''
    audio = np.concatenate([np.zeros(4000, np.float32), audio, np.zeros(4000, np.float32)])
    segments, _ = model.transcribe(audio, language='en', beam_size=5, temperature=0.0,
                                   initial_prompt=PROMPT, condition_on_previous_text=False,
                                   without_timestamps=True, vad_filter=False)
    kept = [s.text for s in segments if not (s.no_speech_prob > 0.6 and s.avg_logprob < -0.8)]
    return ' '.join(t.strip() for t in kept).strip()


class WhisperSTT(stt.STT):
    def __init__(self, model):
        super().__init__(capabilities=stt.STTCapabilities(streaming=False, interim_results=False))
        self._model = model
        self._lock = threading.Lock()

    @property
    def model(self):
        return f'faster-whisper/{WHISPER_MODEL}'

    @property
    def provider(self):
        return 'local'

    def _run(self, audio):
        with self._lock:
            return transcribe(self._model, audio)

    async def _recognize_impl(self, buffer, *, language: NotGivenOr[str] = NOT_GIVEN,
                              conn_options: APIConnectOptions) -> stt.SpeechEvent:
        frame = rtc.combine_audio_frames(buffer)
        audio = to_16k_mono(frame)
        t0 = time.perf_counter()
        text = await asyncio.to_thread(self._run, audio)
        log.info('stt %.0f ms for %.2f s audio: %r', (time.perf_counter() - t0) * 1000, len(audio) / 16000, text)
        return stt.SpeechEvent(type=stt.SpeechEventType.FINAL_TRANSCRIPT, request_id=uuid.uuid4().hex,
                               alternatives=[stt.SpeechData(language=LanguageCode('en'), text=text)])


SENTENCE = re.compile(r'(?<=[.!?])\s+')
_CACHE = {}  # rendered sentences, shared by every session in this process
_RENDER_LOCK = threading.Lock()


class KokoroTTS(tts.TTS):
    def __init__(self, kokoro, voice=None, speed=None):
        super().__init__(capabilities=tts.TTSCapabilities(streaming=False), sample_rate=24000, num_channels=1)
        self._kokoro = kokoro
        self._voice = voice or os.environ.get('BJ_VOICE', 'am_michael')
        self._speed = float(speed or os.environ.get('BJ_SPEED', '1.05'))

    @property
    def model(self):
        return 'kokoro-82m-onnx'

    @property
    def provider(self):
        return 'local'

    def render(self, text: str) -> np.ndarray:
        key = (self._voice, self._speed, text)
        with _RENDER_LOCK:
            pcm = _CACHE.get(key)
            if pcm is None:
                samples, _ = self._kokoro.create(text, voice=self._voice, speed=self._speed, lang='en-us')
                pcm = (np.clip(samples, -1, 1) * 32767).astype(np.int16)
                if len(_CACHE) < 1024:
                    _CACHE[key] = pcm
            return pcm

    def synthesize(self, text: str, *, conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS):
        return _KokoroStream(tts=self, input_text=text, conn_options=conn_options)


class _KokoroStream(tts.ChunkedStream):
    async def _run(self, output_emitter: tts.AudioEmitter) -> None:
        output_emitter.initialize(request_id=uuid.uuid4().hex, sample_rate=24000, num_channels=1, mime_type='audio/pcm')
        # Sentence by sentence, so the first words play while the rest renders.
        for sentence in [s for s in SENTENCE.split(self._input_text.strip()) if s]:
            t0 = time.perf_counter()
            pcm = await asyncio.to_thread(self._tts.render, sentence)
            log.info('tts %.0f ms for %.2f s audio: %r', (time.perf_counter() - t0) * 1000, len(pcm) / 24000, sentence)
            output_emitter.push(pcm.tobytes())
        output_emitter.flush()
