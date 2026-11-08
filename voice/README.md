# Blackjack voice (Claude's build)

LiveKit voice agent for the robot blackjack dealer. Copied from Astra's
`~/armstrong/tools/blackjack-voice` (left untouched) and changed to run with no cloud:

- its own LiveKit dev server (`livekit-dev.yaml`, ports 7980/7981/7982, keys `devkey`/`secret`);
- local STT: faster-whisper `small.en` (int8, CPU) behind the bundled silero VAD;
- local TTS: Kokoro 82M ONNX, voice `am_michael`, common sentences pre-rendered;
- no `.env` is read. `run.sh` passes LIVEKIT_URL/KEY/SECRET for the dev server explicitly.

Game API only (`127.0.0.1:8202`): `/api/state`, `/api/events`, `/api/action`, `/api/voice`.
No station, Manifest, camera, CAN or arm client exists in this code.

| File | What |
|------|------|
| `dealer.py` | the agent (LiveKit Agents 1.8, thread executor, closed parser, narration) |
| `local_models.py` | WhisperSTT and KokoroTTS plugins |
| `commands.py` | closed, deterministic command parser (no LLM) |
| `narration.py` | short dealer lines from state changes |
| `join.py`, `join.html` | browser join page and tokens on :8226 |
| `e2e_test.py` | self-test: speaks "Deal." and "Hit." into a room |
| `run.sh` | start or restart everything; `run.sh status` |
| `DEMO.md` | how to run the demo from the laptop |

Runtime: `~/.cache/armstrong-claude-voice` (its own venv; Astra's runtime is not modified).
Models: `models/` (Kokoro) and the Hugging Face cache (Whisper).

Tests: `~/.cache/armstrong-claude-voice/bin/python -m unittest test_commands test_narration test_join`
