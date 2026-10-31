/**
 * Opt-in browser-side voice gate: sends microphone audio only while the user is speaking.
 * The audio sent is a 120 ms delayed copy and speech is detected on the live signal, so the gate opens
 * before the first syllable arrives. It stays open ~1 s after speech so the server's turn detection still
 * hears trailing silence, and the trigger rises while the agent is audible so speaker echo doesn't open it.
 * The track is never detached: detaching signals end-of-stream and the server stops reading audio.
 */
const PREROLL = 0.12;
const HANG = 0.9;

const WORKLET = `
class Gate extends AudioWorkletProcessor {
  constructor() { super(); this.floor = 0.003; this.speech = true; this.last = currentTime; this.boost = 1;
                  this.port.onmessage = (e) => { this.boost = e.data.boost; }; }
  process(inputs) {
    const ch = inputs[0][0]; if (!ch) return true;
    let sum = 0; for (let i = 0; i < ch.length; i++) sum += ch[i] * ch[i];
    const rms = Math.sqrt(sum / ch.length);
    if (!this.speech) this.floor = Math.min(0.02, this.floor * 0.995 + rms * 0.005);
    const threshold = Math.max(0.012, this.floor * 3) * this.boost;
    if (rms > threshold) { this.last = currentTime; if (!this.speech) { this.speech = true; this.port.postMessage({ speech: true }); } }
    else if (this.speech && currentTime - this.last > ${HANG + PREROLL}) { this.speech = false; this.port.postMessage({ speech: false }); }
    return true;
  }
}
registerProcessor("gate", Gate);`;

export interface VoiceGate {
  watchRemote(stream: MediaStream): void;
  close(): void;
}

export async function attachGatedMic(
  mic: MediaStream,
  pc: RTCPeerConnection,
  onOpen: (open: boolean) => void,
): Promise<VoiceGate> {
  const ctx = new AudioContext();
  const url = URL.createObjectURL(new Blob([WORKLET], { type: "application/javascript" }));
  await ctx.audioWorklet.addModule(url);
  URL.revokeObjectURL(url);

  const src = ctx.createMediaStreamSource(mic);
  const delay = ctx.createDelay(1);
  delay.delayTime.value = PREROLL;
  const valve = ctx.createGain();
  const out = ctx.createMediaStreamDestination();
  src.connect(delay).connect(valve).connect(out);

  const gate = new AudioWorkletNode(ctx, "gate");
  src.connect(gate);
  const silent = ctx.createGain();
  silent.gain.value = 0;
  gate.connect(silent).connect(ctx.destination); // keeps the worklet running

  pc.addTrack(out.stream.getAudioTracks()[0], out.stream);
  onOpen(true);
  gate.port.onmessage = (e) => {
    valve.gain.setTargetAtTime(e.data.speech ? 1 : 0, ctx.currentTime, 0.005); // 5 ms ramp, no click
    onOpen(e.data.speech);
  };

  let timer: ReturnType<typeof setInterval> | undefined;
  return {
    watchRemote(stream) {
      const an = ctx.createAnalyser();
      an.fftSize = 512;
      ctx.createMediaStreamSource(stream).connect(an);
      const buf = new Float32Array(an.fftSize);
      timer = setInterval(() => {
        an.getFloatTimeDomainData(buf);
        let sum = 0;
        for (const v of buf) sum += v * v;
        gate.port.postMessage({ boost: Math.sqrt(sum / buf.length) > 0.01 ? 2.5 : 1 });
      }, 100);
    },
    close() {
      clearInterval(timer);
      ctx.close().catch(() => {});
    },
  };
}
