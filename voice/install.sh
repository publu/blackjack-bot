# Own venv for the Claude blackjack voice agent (does not touch Astra's runtime).
set -eu
V=$HOME/.cache/armstrong-claude-voice
M=$HOME/armstrong-claude/blackjack-voice/models
mkdir -p "$M"
echo "start $(date +%T)"
UV=$(command -v uv || ls $HOME/.local/bin/uv 2>/dev/null || true)
echo "uv=$UV"
if [ ! -x "$V/bin/python" ]; then
  if [ -n "$UV" ]; then "$UV" venv -q -p 3.12 "$V"; else python3 -m venv "$V"; fi
fi
if [ -n "$UV" ]; then PIP="$UV pip install -q --python $V/bin/python"; else "$V/bin/python" -m pip install -q -U pip; PIP="$V/bin/python -m pip install -q"; fi
$PIP "livekit-agents[silero]==1.8.11" faster-whisper kokoro-onnx soundfile python-dotenv aiohttp
echo "pip done $(date +%T)"
cd "$M"
[ -s kokoro-v1.0.onnx ] || curl -sSL -o kokoro-v1.0.onnx https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx
[ -s voices-v1.0.bin ] || curl -sSL -o voices-v1.0.bin https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin
ls -la "$M"
"$V/bin/python" -c "
from faster_whisper import WhisperModel
for n in ('base.en','small.en'): WhisperModel(n, device='cpu', compute_type='int8'); print('whisper', n, 'ok')
"
"$V/bin/python" -c "import importlib.metadata as m; print(sorted(d.metadata['Name']+'=='+d.version for d in m.distributions() if any(k in d.metadata['Name'].lower() for k in ('livekit','whisper','kokoro','onnx','ctranslate','silero','phonem','espeak'))))"
echo "ALL DONE $(date +%T)"
