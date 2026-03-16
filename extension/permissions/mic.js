/**
 * Mic capture page. Auto-requests permission and streams audio.
 * Uses AudioWorkletNode — no deprecated ScriptProcessorNode.
 */

let audioCtx = null;
let micStream = null;
let workletNode = null;
let recording = false;
let port = null;

const status = document.getElementById("status");

function ensurePort() {
  if (port) return port;
  port = chrome.runtime.connect({ name: "offscreen-mic" });
  port.onMessage.addListener((msg) => {
    if (msg.type === "stop_mic") stopStreaming();
    else if (msg.type === "start_mic") startStreaming();
  });
  port.onDisconnect.addListener(() => {
    port = null;
    if (recording) setTimeout(() => ensurePort(), 300);
  });
  return port;
}

async function startStreaming() {
  if (recording) return;

  ensurePort();

  micStream = await navigator.mediaDevices.getUserMedia({
    audio: { sampleRate: 16000, channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
  });

  audioCtx = new AudioContext({ sampleRate: 16000 });
  const source = audioCtx.createMediaStreamSource(micStream);

  // Load AudioWorklet processor
  await audioCtx.audioWorklet.addModule("mic-processor.js");
  workletNode = new AudioWorkletNode(audioCtx, "mic-processor");

  workletNode.port.onmessage = (e) => {
    if (!recording || !port) return;
    const buffer = e.data.buffer;
    const bytes = new Uint8Array(buffer);
    let binary = "";
    for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
    try { port.postMessage({ type: "audio_chunk", data: btoa(binary) }); } catch {}
  };

  source.connect(workletNode);
  workletNode.connect(audioCtx.destination);
  recording = true;
  status.textContent = "Streaming";
  status.style.color = "#34a853";
}

function stopStreaming() {
  recording = false;
  if (workletNode) { workletNode.disconnect(); workletNode = null; }
  if (micStream) { micStream.getTracks().forEach(t => t.stop()); micStream = null; }
  if (audioCtx) { audioCtx.close().catch(() => {}); audioCtx = null; }
  // Close the window — it'll reopen next voice session if needed
  window.close();
}

// Auto-start — Chrome will show permission dialog if needed
startStreaming().catch((e) => {
  status.textContent = "Mic denied";
  status.style.color = "#ea4335";
});
