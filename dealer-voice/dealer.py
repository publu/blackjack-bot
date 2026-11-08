"""LiveKit blackjack dealer voice, fully local: faster-whisper STT, Kokoro TTS, silero VAD.

Commands go through the closed parser in commands.py (no LLM). Only the game API
on 127.0.0.1:8202 is used. LIVEKIT_URL / LIVEKIT_API_KEY / LIVEKIT_API_SECRET
come from the process environment (run.sh passes the local dev server's values).
"""
import asyncio, json, logging, os, threading, time
import aiohttp
import numpy as np
from livekit.agents import Agent, AgentServer, AgentSession, JobContext, JobExecutorType, JobProcess, cli, inference, room_io
from commands import parse, describe
from narration import a, cap, narrate, conversation
RANKS = ('A', '2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K')
from local_models import KokoroTTS, WhisperSTT, load_kokoro, load_whisper, transcribe

BASE = os.environ.get('BJ_GAME', 'http://127.0.0.1:8230')
ROOM_PREFIX = 'armstrong-blackjack-continuous'
log = logging.getLogger('blackjack-voice')
ACK = {'deal': 'Good luck.', 'stand': 'Standing.', 'double': 'Doubling down.', 'split': 'Splitting.'}


WELCOME = "My name is Poker Bot. If you want me to deal and start the game, say deal. I will keep listening."
# Common sentences are rendered once per process so they play with no TTS wait.
PHRASES = [*ACK.values(), *WELCOME.split('. '), 'Your move.', 'The house takes it.', 'Dealer wins this one.', 'Push.',
           'Dealer busts.', 'Blackjack!', 'Blackjack pays three to two.', 'Dealer blackjack.', 'You win 25 dollars.',
           *[f'Dealer shows {a({"rank": r})}.' for r in RANKS], *[cap(a({'rank': r})) + '.' for r in RANKS]]


_MODELS = {}
_MODELS_LOCK = threading.Lock()


def prewarm(proc: JobProcess):
    # Jobs run as threads of one process, so the models load (and the phrases render) once.
    with _MODELS_LOCK:
        if not _MODELS:
            t0 = time.perf_counter()
            whisper, kokoro = load_whisper(), load_kokoro()
            transcribe(whisper, np.zeros(16000, np.float32))
            voice = KokoroTTS(kokoro)
            for p in PHRASES:
                voice.render(p if p.endswith(('.', '!', '?')) else p + '.')
            _MODELS.update(whisper=whisper, kokoro=kokoro)
            log.info('models warm, %d phrases cached, in %.1f s', len(PHRASES), time.perf_counter() - t0)
    proc.userdata.update(_MODELS, vad=inference.VAD(model='silero', min_silence_duration=0.35, activation_threshold=0.5))


server = AgentServer(host='127.0.0.1', port=0, job_executor_type=JobExecutorType.THREAD, num_idle_processes=1,
                     setup_fnc=prewarm, initialize_process_timeout=120, job_memory_warn_mb=4000, log_level='INFO',
                     # Other local applications' CPU load must not strand a
                     # single table without a dealer. Bound actual room jobs;
                     # allow one reconnect while the previous room closes.
                     load_fnc=lambda worker: len(worker.active_jobs) / 2, load_threshold=1.0)


class Dealer(Agent):
    def __init__(self):
        super().__init__(instructions='Calm blackjack dealer. Commands are handled by a closed, deterministic parser. No robot control.')

    async def llm_node(self, *args, **kwargs):
        return None


@server.rtc_session(agent_name='continuous-blackjack-dealer')
async def entrypoint(ctx: JobContext):
    if not ctx.room.name.startswith(ROOM_PREFIX):
        raise RuntimeError('Blackjack voice only joins its own rooms')
    http = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5))
    ctx.add_shutdown_callback(http.close)
    ud = ctx.proc.userdata
    session = AgentSession(
        stt=WhisperSTT(ud['whisper']), tts=KokoroTTS(ud['kokoro']), vad=ud['vad'],
        turn_handling={'turn_detection': 'vad', 'endpointing': {'min_delay': 0.2, 'max_delay': 1.5},
                       'interruption': {'enabled': False},
                       'preemptive_generation': {'enabled': False}},
        aec_warmup_duration=0.5, user_away_timeout=None)
    tasks = set(); last = {'text': '', 'at': 0.0}; epoch = [0]
    closing = asyncio.Event()
    speak_lock = asyncio.Lock(); command_lock = asyncio.Lock()

    def task(coro):
        if closing.is_set():
            coro.close()
            return None
        t = asyncio.create_task(coro); tasks.add(t)
        def finished(done):
            tasks.discard(done)
            if not done.cancelled():
                error = done.exception()
                if error is not None and not closing.is_set():
                    log.error('Voice background task failed: %s', error)
        t.add_done_callback(finished)
        return t

    async def cleanup():
        closing.set()
        pending = list(tasks)
        for t in pending:
            t.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
    ctx.add_shutdown_callback(cleanup)

    @session.on('close')
    def closed(_event):
        closing.set()
        epoch[0] += 1
        ctx.shutdown(reason='Voice participant session closed')

    async def api(path, data=None):
        async with http.request('POST' if data is not None else 'GET', BASE + path, json=data) as r:
            value = await r.json()
            if r.status >= 400:
                raise ValueError(value.get('error', 'Table unavailable'))
            return value

    async def caption(speaking, text=''):
        try:
            await api('/api/voice', {'speaking': speaking, 'text': text})
        except (ValueError, aiohttp.ClientError, asyncio.TimeoutError):
            pass

    async def say(line, mine=None):
        mine = epoch[0] if mine is None else mine
        async with speak_lock:
            if closing.is_set() or mine != epoch[0] or not line:
                return  # a newer command made this line stale
            log.info('say %r', line)
            await caption(True, line)
            try:
                await session.say(line, allow_interruptions=False).wait_for_playout()
            finally:
                await caption(False)

    async def command(text, heard_at):
        if closing.is_set():
            return
        now = time.monotonic()
        if text == last['text'] and now - last['at'] < .7:
            return
        last.update(text=text, at=now)
        intent = parse(text)
        log.info('heard %r -> %s', text, intent)
        if not intent:
            return  # unknown phrases never act and stay silent (open mic in a loud room)
        epoch[0] += 1; mine = epoch[0]
        async with command_lock:
            try:
                current = await api('/api/state')
                live_session = current.get('session') or {}
                action = intent['action']
                if action in ('hand', 'bankroll'):
                    line = describe(current, action)
                elif action == 'stop':
                    await api('/api/session', {'action':'stop'})
                    line = 'I have stopped this game.'
                elif action == 'deal':
                    await api('/api/session', {'action':'deal'})
                    line = ''  # The opening state event narrates the accepted deal.
                elif action == 'reset':
                    await api('/api/session', {'action':'reconcile', 'checked':True})
                    line = 'The old hand is cleared. Say deal when you are ready for a fresh game.'
                elif live_session.get('active'):
                    if action not in ('hit', 'stand') or live_session.get('phase') != 'player':
                        raise ValueError('Wait for your turn. ' + live_session.get('message', ''))
                    await api('/api/session', {'action':action, 'decision_id':live_session.get('decision_id')})
                    line = ''  # One narrator for both voice and button choices.
                elif action == 'bet':
                    state = await api('/api/action', intent)
                    line = f"Your bet is {state['bet']:g} dollars. Say deal when you are ready."
                else:
                    line = 'Say deal to start the game. Then you can say hit or stand on your turn.'
            except ValueError as e:
                line = str(e)
            except (aiohttp.ClientError, asyncio.TimeoutError):
                line = 'The table is unavailable.'
        if line:
            task(say(line, mine))

    @session.on('user_input_transcribed')
    def transcribed(event):
        if event.is_final and event.transcript.strip():
            task(command(event.transcript, time.monotonic()))

    async def text_input(sess, event):
        task(command(event.text, time.monotonic()))

    await session.start(agent=Dealer(), room=ctx.room,
                        room_options=room_io.RoomOptions(text_input=room_io.TextInputOptions(text_input_cb=text_input)))
    await ctx.connect()

    async def events():
        while not closing.is_set():
            # Fresh each connection: the table server may have been restarted (event ids start over),
            # so ask for everything and drop rows older than this connection.
            quiet = None; last_id = '0'; joined = time.time()
            try:
                async with http.get(BASE + '/api/events', headers={'Last-Event-ID': '0'},
                                    timeout=aiohttp.ClientTimeout(total=None, sock_read=15)) as r:
                    kind = ''
                    async for raw in r.content:
                        line = raw.decode().strip()
                        if line.startswith('id:'):
                            last_id = line[3:].strip()
                        elif line.startswith('event:'):
                            kind = line[6:].strip()
                        elif line.startswith('data:') and kind == 'state':
                            row = json.loads(line[5:])
                            if row.get('at', joined) < joined - 0.5:
                                continue  # history the server replays on first connect
                            cur = row.get('state') or {}
                            if quiet is None:
                                quiet = cur
                                continue
                            if cur.get('revision') == quiet.get('revision'):
                                continue
                            spoken = conversation(quiet, cur) if cur.get('session') else narrate(quiet, cur)
                            quiet = cur
                            if spoken:
                                task(say(spoken))
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
                await asyncio.sleep(1)

    task(events())
    try:
        initial = await api('/api/state')
        welcome = ('My name is Poker Bot. ' + initial.get('message', '')) if (initial.get('session') or {}).get('active') else WELCOME
    except (ValueError, aiohttp.ClientError, asyncio.TimeoutError):
        welcome = WELCOME
    await say(welcome)

if __name__ == '__main__':
    cli.run_app(server)
