"""End-to-end voice test, no human: speak "deal" then "hit" into a LiveKit room.

Joins room armstrong-blackjack-e2e on the local dev server as a participant,
publishes Kokoro-generated speech as a microphone track, and checks that
/api/state changed and that the dealer agent answered (audio + transcript).
Practice mode only. If no table page is drawing the practice cards, this test
draws them through /api/action, exactly as the table page does.
"""
import asyncio, json, os, sys, time, urllib.request
from pathlib import Path
import numpy as np
from livekit import api, rtc

sys.path.insert(0, str(Path(__file__).parent))
from local_models import load_kokoro

GAME = os.environ.get('BJ_GAME', '')
AGENT = os.environ.get('BJ_AGENT_NAME', 'blackjack-dealer-test')
if not GAME or GAME.rstrip('/').endswith(':8202') or AGENT == 'blackjack-dealer':
    # :8202 is the one shared demo game every table page shows. Tests never drive it.
    raise SystemExit('Run against your own tabletop_server.py port with a test agent: '
                     'set BJ_GAME=http://127.0.0.1:<port> and BJ_AGENT_NAME=<test agent name> (see DEMO.md)')
URL = os.environ.get('LIVEKIT_URL', 'ws://127.0.0.1:7980')
ROOM = 'armstrong-blackjack-e2e'
SR = 24000
T0 = time.monotonic()


def ts():
    return f'{time.monotonic() - T0:7.2f}s'


def http(path, data=None):
    req = urllib.request.Request(GAME + path, data=None if data is None else json.dumps(data).encode(),
                                 headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        return {'error': json.load(e)}


def brief(s):
    hands = ' | '.join(' '.join(c['rank'] + c['suit'] for c in h['cards']) + f" ({h['total']}{' ' + h['result'] if h.get('result') else ''})" for h in s['hands'])
    dealer = ' '.join(c['rank'] + c['suit'] for c in s['dealer']['cards'])
    return (f"rev={s['revision']} mode={s['mode']} round={s['round']} phase={s['phase']} bankroll={s['bankroll']:g} "
            f"bet={s['bet']:g} player=[{hands}] dealer=[{dealer} ({s['dealer']['total']})] legal={s['legal_actions']} "
            f"pending={'yes' if s['pending'] else 'no'} msg={s['message']!r}")


class Mic:
    """Feeds the published track continuously: silence, or queued speech, in real time."""
    def __init__(self, source):
        self.source, self.queue, self.ended = source, [], None

    async def run(self):
        n = SR // 50  # 20 ms frames
        silence = np.zeros(n, np.int16)
        next_at = time.monotonic()
        while True:
            chunk = silence
            if self.queue:
                chunk, self.queue[0] = self.queue[0][:n], self.queue[0][n:]
                if len(self.queue[0]) == 0:
                    self.queue.pop(0); self.ended = time.monotonic() + 0.02
                if len(chunk) < n:
                    chunk = np.concatenate([chunk, silence[:n - len(chunk)]])
            await self.source.capture_frame(rtc.AudioFrame(chunk.tobytes(), SR, 1, n))
            next_at += 0.02
            await asyncio.sleep(max(0, next_at - time.monotonic()))

    async def say(self, pcm):
        self.ended = None; self.queue.append(pcm)
        while self.ended is None:
            await asyncio.sleep(0.005)
        return self.ended


async def finish_draws(log):
    """Wait for the table page to draw practice cards; draw them ourselves if nobody does."""
    for _ in range(40):
        s = http('/api/state')
        p = s.get('pending')
        if not p:
            return s
        await asyncio.sleep(1.2)
        s2 = http('/api/state')
        if s2.get('pending') and s2['pending']['id'] == p['id'] and s2['revision'] == s['revision']:
            if p.get('status') != 'practice_draw':
                raise SystemExit('Pending card is not a practice draw; refusing to touch a physical round')
            r = http('/api/action', {'action': 'draw', 'revision': s2['revision'], 'token': p['id']})
            log.append('test drew ' + ('error ' + str(r['error']) if 'error' in r else 'a practice card'))
    raise SystemExit('cards stayed pending')


async def main():
    kokoro = load_kokoro()

    def speech(text):  # a different voice from the dealer's
        s, _ = kokoro.create(text, voice='af_bella', speed=1.0, lang='en-us')
        return (np.clip(s, -1, 1) * 32767).astype(np.int16)

    lines = {w: speech(w) for w in ('Deal.', 'Hit.')}
    token = (api.AccessToken(os.environ.get('LIVEKIT_API_KEY', 'devkey'), os.environ.get('LIVEKIT_API_SECRET', 'secret'))
             .with_identity('e2e-player').with_name('E2E player')
             .with_grants(api.VideoGrants(room_join=True, room=ROOM))
             .with_room_config(api.RoomConfiguration(agents=[api.RoomAgentDispatch(agent_name=AGENT)]))
             .to_jwt())
    room = rtc.Room()
    transcripts, onsets, ends, draws = [], [], [], []

    def on_text(reader, identity):
        async def read():
            text = await reader.read_all()
            who = 'player' if identity == 'e2e-player' else 'dealer'
            transcripts.append((time.monotonic(), who, text))
            print(f'{ts()} transcript[{who}] {text!r}', flush=True)
        asyncio.ensure_future(read())
    room.register_text_stream_handler('lk.transcription', on_text)

    async def listen(track):
        speaking, last_loud = False, 0.0
        async for ev in rtc.AudioStream(track, sample_rate=SR, num_channels=1):
            x = np.frombuffer(ev.frame.data, np.int16).astype(np.float32)
            now = time.monotonic()
            if x.size and np.sqrt(np.mean(x * x)) > 300:
                last_loud = now
                if not speaking:
                    speaking = True; onsets.append(now); print(f'{ts()} dealer audio starts', flush=True)
            elif speaking and now - last_loud > 0.5:
                speaking = False; ends.append(last_loud); print(f'{ts()} dealer audio ends', flush=True)

    @room.on('track_subscribed')
    def on_track(track, pub, participant):
        if track.kind == rtc.TrackKind.KIND_AUDIO:
            print(f'{ts()} subscribed to audio from {participant.identity}', flush=True)
            asyncio.ensure_future(listen(track))

    await room.connect(URL, token)
    source = rtc.AudioSource(SR, 1, queue_size_ms=100)
    track = rtc.LocalAudioTrack.create_audio_track('mic', source)
    await room.local_participant.publish_track(track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE))
    mic = Mic(source); asyncio.ensure_future(mic.run())
    print(f'{ts()} connected to {URL} room {ROOM}', flush=True)

    async def quiet(after, timeout=12):
        """Wait until the dealer has spoken after `after` and gone quiet."""
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if any(o > after for o in onsets) and ends and ends[-1] > max(o for o in onsets) and time.monotonic() - ends[-1] > 0.6:
                return True
            await asyncio.sleep(0.05)
        return False

    await quiet(T0, 40)  # welcome line
    s = http('/api/state')
    print(f'{ts()} BEFORE {brief(s)}', flush=True)
    if s['mode'] != 'practice':
        raise SystemExit('Table is not in practice mode; refusing to act')
    if s['phase'] == 'player':
        http('/api/action', {'action': 'stand'})
    s = await finish_draws(draws)
    await quiet(time.monotonic() - 0.1, 8)

    results = []

    async def speak(word, changed):
        before = http('/api/state')
        t_end = await mic.say(lines[word])
        while time.monotonic() - t_end < 6:
            s = http('/api/state')
            if changed(before, s):
                t_act = time.monotonic()
                break
            await asyncio.sleep(0.02)
        else:
            print(f'{ts()} {word!r}: NO STATE CHANGE within 6 s', flush=True)
            results.append((word, None, None)); return None
        first = next((o for o in onsets if o > t_end), None)
        print(f'{ts()} {word!r}: state changed {1000 * (t_act - t_end):.0f} ms after end of speech -> {brief(s)}', flush=True)
        after = await finish_draws(draws)
        acks = ('Good luck.', 'Standing.', 'Doubling down.', 'Splitting.')
        for _ in range(240):  # the narration transcript closes when that line has finished playing
            if any(t > t_act and who == 'dealer' and text not in acks for t, who, text in transcripts):
                break
            await asyncio.sleep(0.05)
        await quiet(t_end, 3)
        first = next((o for o in onsets if o > t_end), None)
        results.append((word, t_act - t_end, None if first is None else first - t_end))
        print(f'{ts()} after draws: {brief(after)}', flush=True)
        return after

    for attempt in range(4):
        s = await speak('Deal.', lambda b, a: a['round'] > b['round'])
        if s is None or 'hit' in s['legal_actions']:
            break
        print(f'{ts()} round ended at once (natural); dealing again', flush=True)
    if s is not None and 'hit' in s['legal_actions']:
        await speak('Hit.', lambda b, a: a['revision'] > b['revision'] and a['round'] == b['round'])
    await asyncio.sleep(1.0)
    final = http('/api/state')
    print(f'{ts()} AFTER {brief(final)}', flush=True)
    print('== summary')
    for word, act, voice in results:
        print(f"{word!r}: end of speech -> game action {'FAILED' if act is None else f'{act * 1000:.0f} ms'}; "
              f"-> dealer audio {'none' if voice is None else f'{voice * 1000:.0f} ms'}")
    print('practice draws done by test:', len([d for d in draws if 'practice card' in d]), draws[-3:])
    print('transcripts:', [(who, text) for _, who, text in transcripts])
    await room.disconnect()


if __name__ == '__main__':
    asyncio.run(main())
