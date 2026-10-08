"""Pipecat pipeline for one call: SmallWebRTC -> Silero VAD + smart-turn -> Deepgram -> OpenAI
(function calling) -> [CallTap: gate + transcript] -> Cartesia -> transport.

Needs OPENAI / DEEPGRAM / CARTESIA keys. Everything with decisions in it (tools, gate, tagger)
lives in modules that don't import Pipecat, so it is unit tested without keys."""
import asyncio
import logging

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import (BotStartedSpeakingFrame, BotStoppedSpeakingFrame, EndFrame,
                                   FunctionCallResultProperties, LLMMessagesAppendFrame, LLMRunFrame,
                                   UserStartedSpeakingFrame, UserStoppedSpeakingFrame)
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.worker import PipelineParams, PipelineWorker, ProcessorUnusablePolicy
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (LLMContextAggregatorPair,
                                                                    LLMUserAggregatorParams)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.services.cartesia.tts import CartesiaTTSService
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.transports.base_transport import TransportParams
from pipecat.turns.user_mute import FunctionCallUserMuteStrategy, MuteUntilFirstBotCompleteUserMuteStrategy
from pipecat.turns.user_start import MinWordsUserTurnStartStrategy
from pipecat.turns.user_turn_strategies import UserTurnStrategies
from pipecat.transports.smallwebrtc.connection import IceServer, SmallWebRTCConnection
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport

from app.core.config import Settings, settings as default_settings
from app.voice.gate import InjectionGate
from app.voice.prompt import build_prompt
from app.voice.session import CallSession
from app.voice.tools import TOOL_SPECS, ToolBox, VoiceDeps

log = logging.getLogger(__name__)

INTERRUPT_MIN_WORDS = 2
OPENING = "The customer has just answered the call. Begin with your opening line."


def ice_servers(cfg: Settings = default_settings) -> list[IceServer]:
    servers = [IceServer(urls="stun:stun.l.google.com:19302")]
    urls = [u.strip() for u in cfg.turn_ice_urls.split(",") if u.strip()]
    if urls:  # TURN is required for judges behind NAT; configure on client and here
        servers.append(IceServer(urls=urls, username=cfg.turn_username, credential=cfg.turn_credential))
    return servers


class CallTap(FrameProcessor):
    """Feeds the injection gate (speaking state + voice-to-voice latency). Sits after the LLM: user
    speaking frames flow through it downstream and bot speaking frames come back upstream from the
    transport. The transcript is NOT built here: the user aggregator consumes transcription frames
    and TTS text is produced after this point, so it comes from the aggregators' turn events."""

    def __init__(self, session: CallSession, gate: InjectionGate, **kw) -> None:
        super().__init__(**kw)
        self.s, self.gate = session, gate

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        if isinstance(frame, UserStartedSpeakingFrame):
            await self.gate.user_started()
        elif isinstance(frame, UserStoppedSpeakingFrame):
            await self.gate.user_stopped()
        elif isinstance(frame, BotStartedSpeakingFrame):
            await self.gate.bot_started()
        elif isinstance(frame, BotStoppedSpeakingFrame):
            await self.gate.bot_stopped()
            self.s.latency_ms = list(self.gate.latencies_ms)
        await self.push_frame(frame, direction)


def record_turn(session: CallSession, role: str, content: str | None, interrupted: bool = False) -> None:
    """Append a finished conversation turn to the transcript (empty turns are ignored)."""
    text = (content or "").strip()
    if text:
        session.transcript.append({"role": role, "text": text, **({"interrupted": True} if interrupted else {})})


def tools_schema(allowed: list[str]) -> ToolsSchema:
    return ToolsSchema(standard_tools=[
        FunctionSchema(name=n, description=TOOL_SPECS[n]["description"],
                       properties=TOOL_SPECS[n]["properties"], required=TOOL_SPECS[n]["required"])
        for n in allowed if n in TOOL_SPECS])


def build_task(session: CallSession, connection: SmallWebRTCConnection, deps: VoiceDeps,
               cfg: Settings = default_settings, merchant: str = "the store") -> PipelineWorker:
    transport = SmallWebRTCTransport(connection, params=TransportParams(
        audio_in_enabled=True, audio_out_enabled=True))
    stt = DeepgramSTTService(api_key=cfg.deepgram_api_key,
                             settings=DeepgramSTTService.Settings(model=cfg.stt_model))
    llm = OpenAILLMService(api_key=cfg.llm_key, base_url=cfg.llm_base_url or None,
                           settings=OpenAILLMService.Settings(model=cfg.llm_model))
    tts = CartesiaTTSService(api_key=cfg.cartesia_api_key,
                             settings=CartesiaTTSService.Settings(voice=cfg.tts_voice_id))

    context = LLMContext(
        messages=[{"role": "system", "content": build_prompt(session, merchant)},
                  {"role": "user", "content": OPENING}],
        tools=tools_schema(session.tools))
    agg = LLMContextAggregatorPair(context, user_params=LLMUserAggregatorParams(
        vad_analyzer=SileroVADAnalyzer(), user_idle_timeout=cfg.silence_timeout_seconds,
        # Real-call lessons: speaker echo and noise were chopping Maya's replies to one word.
        # 1) the opening line can't be interrupted, 2) nor can she be mid tool call, and
        # 3) a single stray word doesn't count as an interruption while she is talking.
        user_mute_strategies=[MuteUntilFirstBotCompleteUserMuteStrategy(),
                              FunctionCallUserMuteStrategy()],
        user_turn_strategies=UserTurnStrategies(
            start=[MinWordsUserTurnStartStrategy(min_words=INTERRUPT_MIN_WORDS)])))

    gate_push_task: dict = {}

    async def push(messages: list[dict]) -> None:
        for m in messages:
            if m["content"].startswith("[PAYPAL EVENT]"):  # chip in the transcript, at injection time
                session.transcript.append({"role": "event", "text": m["content"]})
        await gate_push_task["task"].queue_frames([LLMMessagesAppendFrame(messages, run_llm=True)])

    gate = InjectionGate(push)
    session.gate = gate
    toolbox = ToolBox(session, deps)

    def make_handler(name: str):
        async def handler(params):
            # call_started/finished wrap the whole tool call so the gate never injects mid-call,
            # regardless of which direction Pipecat routes the result frame
            await gate.call_started(params.tool_call_id)
            try:
                result = await toolbox.dispatch(name, params.arguments)
                if name == "end_call":
                    await params.result_callback(result, properties=FunctionCallResultProperties(
                        run_llm=False))
                    await task.queue_frame(EndFrame())  # queued behind any speech already in flight
                else:
                    await params.result_callback(result)
            finally:
                await gate.call_finished(params.tool_call_id)
        return handler

    for name in session.tools:
        if name in TOOL_SPECS:
            llm.register_function(name, make_handler(name))

    tap = CallTap(session, gate)
    pipeline = Pipeline([transport.input(), stt, agg.user(), llm, tap, tts, transport.output(),
                         agg.assistant()])
    # A dead STT / LLM / TTS (bad key, outage) must end the call now, not sit silent until the cap.
    task = PipelineWorker(pipeline, params=PipelineParams(enable_metrics=True),
                          processor_unusable_policy=ProcessorUnusablePolicy.CANCEL,
                          enable_rtvi=False)  # no RTVI client here; it only filled the data-channel queue
    gate_push_task["task"] = task
    session.task = task

    @transport.event_handler("on_client_connected")
    async def _connected(_t, _c):
        session.status = "live"
        await task.queue_frames([LLMRunFrame()])

    @transport.event_handler("on_client_disconnected")
    async def _disconnected(_t, _c):
        session.ended_reason = session.ended_reason or "client_left"
        await task.cancel()

    @agg.user().event_handler("on_user_turn_stopped")
    async def _user_turn(_agg, _strategy, message):
        record_turn(session, "user", message.content)

    @agg.assistant().event_handler("on_assistant_turn_stopped")
    async def _assistant_turn(_agg, message):
        record_turn(session, "assistant", message.content, message.interrupted)

    @task.event_handler("on_pipeline_error")
    async def _errored(_task, frame):
        if frame.processor is not None and not frame.processor.is_usable:
            session.ended_reason = "service_error"

    @agg.user().event_handler("on_user_turn_idle")
    async def _idle(_agg):
        session.ended_reason = "silence"
        await task.cancel()

    return task


async def run_bot(session: CallSession, connection: SmallWebRTCConnection, deps: VoiceDeps,
                  cfg: Settings = default_settings) -> None:
    task = build_task(session, connection, deps, cfg)
    await PipelineRunner(handle_sigint=False).run(task)
