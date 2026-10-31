import { api } from "./api";
import { attachGatedMic, type VoiceGate } from "./voiceGate";

export interface LiveCall {
  hangup(): void;
}

interface Options {
  gated: boolean;
  family?: string;
  audio: HTMLAudioElement;
  onState(state: RTCPeerConnectionState): void;
  onMic(open: boolean): void;
}

/** Answer a ringing call from the browser: mic → WebRTC offer → server answer. Throws if setup fails. */
export async function answerCall(callId: string, o: Options): Promise<LiveCall> {
  const mic = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
  const pc = new RTCPeerConnection(await api.iceServers());
  let gate: VoiceGate | null = null;

  const hangup = () => {
    pc.close();
    gate?.close();
    mic.getTracks().forEach((t) => t.stop()); // release the microphone
  };

  try {
    if (o.gated) gate = await attachGatedMic(mic, pc, o.onMic);
    else mic.getTracks().forEach((t) => pc.addTrack(t, mic));

    pc.ontrack = (e) => {
      o.audio.srcObject = e.streams[0];
      gate?.watchRemote(e.streams[0]);
    };
    pc.onconnectionstatechange = () => o.onState(pc.connectionState);

    await pc.setLocalDescription(await pc.createOffer());
    await new Promise<void>((done) => { // wait for ICE candidates to be gathered into the SDP
      if (pc.iceGatheringState === "complete") return done();
      pc.onicegatheringstatechange = () => pc.iceGatheringState === "complete" && done();
      setTimeout(done, 3000);
    });
    const { sdp, type } = pc.localDescription!;
    const answer = await api.answerCall(callId, sdp, type, o.family);
    await pc.setRemoteDescription({ sdp: answer.sdp, type: answer.type });
  } catch (e) {
    hangup();
    throw e;
  }
  return { hangup };
}
