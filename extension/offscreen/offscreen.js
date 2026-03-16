/**
 * Offscreen document for microphone capture.
 * Uses AudioWorkletNode for processing, streams PCM16 audio
 * to the service worker via a persistent port.
 */

let audioCtx = null;
let micStream = null;
let workletNode = null;
let recording = false;
let port = null;

// Connect port to service worker immediately
port = chrome.runtime.connect({ name: "offscreen-mic" });
console.log("[G-Axis Offscreen] Port connected");

port.onMessage.addListener((msg) => {
  if (msg.type === "start_mic") startMic();
  else if (msg.type === "stop_mic") stopMic();
});

port.onDisconnect.addListener(() => {
  console.log("[G-Axis Offscreen] Port disconnected");
  port = null;
  // Reconnect after brief delay
  setTimeout(() => {
    if (recording) {
      port = chrome.runtime.connect({ name: "offscreen-mic" });
      console.log("[G-Axis Offscreen] Port reconnected");
    }
  }, 500);
});

// Also listen via sendMessage as fallback
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type === "offscreen:start_mic") {
    startMic().then(() => sendResponse({ ok: true })).catch(e => sendResponse({ ok: false, error: e.message }));
    return true;
  }
  if (msg.type === "offscreen:stop_mic") {
    stopMic();
    sendResponse({ ok: true });
  }
});

async function startMic() {
  if (recording) return;

  console.log("[G-Axis Offscreen] Requesting mic access...");
  micStream = await navigator.mediaDevices.getUserMedia({
    audio: {
      sampleRate: 16000,
      channelCount: 1,
      echoCancellation: true,
      noiseSuppression: true,
      autoGainControl: true,
    },
  });
  console.log("[G-Axis Offscreen] Mic access granted");

  audioCtx = new AudioContext({ sampleRate: 16000 });
  const source = audioCtx.createMediaStreamSource(micStream);

  // Use ScriptProcessorNode (AudioWorklet not available in offscreen docs)
  const processor = audioCtx.createScriptProcessor(4096, 1, 1);
  let chunkCount = 0;

  processor.onaudioprocess = (e) => {
    if (!recording || !port) return;
    const float32 = e.inputBuffer.getChannelData(0);
    const int16 = new Int16Array(float32.length);
    for (let i = 0; i < float32.length; i++) {
      const s = Math.max(-1, Math.min(1, float32[i]));
      int16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
    }
    const bytes = new Uint8Array(int16.buffer);
    let binary = "";
    for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
    const b64 = btoa(binary);
    try {
      port.postMessage({ type: "audio_chunk", data: b64 });
    } catch {
      // Port disconnected — will auto-reconnect
    }
    chunkCount++;
    if (chunkCount % 100 === 0) {
      console.log(`[G-Axis Offscreen] ${chunkCount} chunks sent`);
    }
  };

  source.connect(processor);
  processor.connect(audioCtx.destination);
  recording = true;
  console.log("[G-Axis Offscreen] Mic streaming started");
}

function stopMic() {
  recording = false;
  if (micStream) { micStream.getTracks().forEach(t => t.stop()); micStream = null; }
  if (audioCtx) { audioCtx.close().catch(() => {}); audioCtx = null; }
  workletNode = null;
  console.log("[G-Axis Offscreen] Mic stopped");
}
