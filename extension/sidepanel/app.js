/**
 * G-Axis Side Panel Application
 *
 * Handles user interaction, voice input, and displays agent state
 * in real-time via messages from the background service worker.
 */

import { MSG } from "../shared/types.js";

// ─── DOM ELEMENTS ─────────────────────────────────────────────

const $ = (id) => document.getElementById(id);

const els = {
  connectionStatus: $("connection-status"),
  settingsBtn: $("settings-btn"),
  taskInput: $("task-input"),
  voiceBtn: $("voice-btn"),
  sendBtn: $("send-btn"),
  suggestions: $("suggestions"),
  statusSection: $("status-section"),
  statusText: $("status-text"),
  taskInstruction: $("task-instruction"),
  stopBtn: $("stop-btn"),
  screenshotContainer: $("screenshot-container"),
  screenshotImg: $("screenshot-img"),
  approvalSection: $("approval-section"),
  approvalAction: $("approval-action"),
  approvalReason: $("approval-reason"),
  approvalRisk: $("approval-risk"),
  approvalConfidence: $("approval-confidence"),
  approveBtn: $("approve-btn"),
  denyBtn: $("deny-btn"),
  inputSection: $("input-section"),
  timeline: $("timeline"),
  timelineSection: $("timeline-section"),
  completeSection: $("complete-section"),
  completeIcon: $("complete-icon"),
  completeSummary: $("complete-summary"),
  completeStats: $("complete-stats"),
  newTaskBtn: $("new-task-btn"),
};

// ─── STATE ────────────────────────────────────────────────────

let isRunning = false;
let recognition = null;
let isRecording = false;
let stepCount = 0;
let startTime = 0;

// ─── INITIALIZE ───────────────────────────────────────────────

function init() {
  // Connect to backend
  chrome.runtime.sendMessage({ type: MSG.CONNECT });

  // Input handling
  els.taskInput.addEventListener("input", () => {
    els.sendBtn.disabled = !els.taskInput.value.trim();
  });

  els.taskInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (els.taskInput.value.trim()) runTask();
    }
  });

  els.sendBtn.addEventListener("click", runTask);
  els.stopBtn.addEventListener("click", stopTask);
  els.voiceBtn.addEventListener("click", toggleVoice);
  els.approveBtn.addEventListener("click", () => sendApproval(true));
  els.denyBtn.addEventListener("click", () => sendApproval(false));
  els.newTaskBtn.addEventListener("click", resetUI);
  els.settingsBtn.addEventListener("click", () => chrome.runtime.openOptionsPage());

  // Suggestion buttons
  els.suggestions.querySelectorAll(".suggestion").forEach((btn) => {
    btn.addEventListener("click", () => {
      els.taskInput.value = btn.dataset.task;
      els.sendBtn.disabled = false;
      runTask();
    });
  });

  // Listen for messages from background
  chrome.runtime.onMessage.addListener(handleMessage);
}

// ─── TASK EXECUTION ───────────────────────────────────────────

function runTask() {
  const instruction = els.taskInput.value.trim();
  if (!instruction) return;

  isRunning = true;
  stepCount = 0;
  startTime = Date.now();

  chrome.runtime.sendMessage({ type: MSG.RUN_TASK, instruction });

  // Update UI
  els.inputSection.classList.add("hidden");
  els.statusSection.classList.remove("hidden");
  els.stopBtn.classList.remove("hidden");
  els.completeSection.classList.add("hidden");
  els.taskInstruction.textContent = instruction;
  els.timeline.innerHTML = "";
  setStatus("Starting...", "");

  addTimelineEntry("start", "Task started", instruction);
}

function stopTask() {
  chrome.runtime.sendMessage({ type: MSG.STOP_TASK });
  resetUI();
}

function sendApproval(approved) {
  chrome.runtime.sendMessage({ type: approved ? MSG.APPROVE : MSG.DENY });
  els.approvalSection.classList.add("hidden");
  if (approved) {
    addTimelineEntry("approved", "Approved", "");
  } else {
    addTimelineEntry("denied", "Denied by operator", "");
  }
}

// ─── MESSAGE HANDLER ──────────────────────────────────────────

function handleMessage(msg) {
  switch (msg.type) {
    case MSG.CONNECTION_STATUS:
      els.connectionStatus.className = `status-dot ${msg.data.connected ? "connected" : "disconnected"}`;
      els.connectionStatus.title = msg.data.connected ? "Connected" : "Disconnected";
      break;

    case MSG.TASK_STARTED:
      setStatus("Running", "executing");
      break;

    case MSG.PERCEIVING:
      setStatus("Analyzing page...", "perceiving");
      addTimelineEntry("eye", "Analyzing", msg.data?.url || "");
      break;

    case MSG.PERCEPTION:
      if (msg.data?.screenshot) {
        els.screenshotContainer.classList.remove("hidden");
        els.screenshotImg.src = `data:image/jpeg;base64,${msg.data.screenshot}`;
      }
      if (msg.data?.page_summary) {
        addTimelineEntry("brain", "Understood", msg.data.page_summary);
      }
      break;

    case MSG.ACTION_PLANNED:
      setStatus(`${msg.data?.action_type?.toUpperCase() || "Action"}...`, "executing");
      addTimelineEntry(
        "action",
        msg.data?.action_type?.toUpperCase() || "ACTION",
        msg.data?.reasoning || "",
        msg.data?.risk_level,
        msg.data?.confidence
      );
      break;

    case MSG.ACTION_SUCCEEDED:
      stepCount++;
      const lastEntry = els.timeline.lastElementChild;
      if (lastEntry) {
        const icon = lastEntry.querySelector(".timeline-icon");
        if (icon) icon.textContent = "\u2713";
      }
      break;

    case MSG.ACTION_FAILED:
      addTimelineEntry("error", "Failed", msg.data?.error || "Unknown error");
      break;

    case MSG.APPROVAL_NEEDED:
      setStatus("Awaiting approval", "awaiting");
      showApproval(msg.data);
      break;

    case MSG.TASK_COMPLETED:
      isRunning = false;
      showComplete(true, msg.data);
      break;

    case MSG.TASK_FAILED:
      isRunning = false;
      showComplete(false, msg.data);
      break;

    case MSG.ERROR:
      addTimelineEntry("error", "Error", msg.data?.message || "Unknown error");
      break;
  }
}

// ─── UI HELPERS ───────────────────────────────────────────────

function setStatus(text, className) {
  els.statusText.textContent = text;
  els.statusText.className = className || "";
}

function addTimelineEntry(icon, actionType, reasoning, riskLevel, confidence) {
  const iconMap = {
    start: "\u25B6",
    eye: "\uD83D\uDC41",
    brain: "\uD83E\uDDE0",
    action: "\u2022",
    approved: "\u2705",
    denied: "\u274C",
    error: "\u26A0",
    complete: "\u2714",
  };

  const entry = document.createElement("div");
  entry.className = "timeline-entry";

  let metaHtml = "";
  if (riskLevel) {
    metaHtml += `<span class="risk-badge ${riskLevel}">${riskLevel}</span> `;
  }
  if (confidence != null) {
    metaHtml += `<span class="dim">${Math.round(confidence * 100)}%</span>`;
  }

  entry.innerHTML = `
    <div class="timeline-icon">${iconMap[icon] || "\u2022"}</div>
    <div class="timeline-content">
      <span class="action-type">${actionType}</span> ${metaHtml}
      <div class="reasoning">${reasoning}</div>
    </div>
    <span class="timeline-time">${formatTime()}</span>
  `;

  els.timeline.appendChild(entry);
  entry.scrollIntoView({ behavior: "smooth", block: "end" });
}

function showApproval(data) {
  els.approvalSection.classList.remove("hidden");
  els.approvalAction.textContent = `${data.action_type?.toUpperCase()}: ${data.reasoning || ""}`;
  els.approvalReason.textContent = data.reason || "";
  els.approvalRisk.textContent = data.risk_level || "medium";
  els.approvalRisk.className = `risk-badge ${data.risk_level || "medium"}`;
  els.approvalConfidence.textContent = data.confidence != null
    ? `${Math.round(data.confidence * 100)}% confidence`
    : "";
}

function showComplete(success, data) {
  els.statusSection.classList.add("hidden");
  els.stopBtn.classList.add("hidden");
  els.completeSection.classList.remove("hidden");
  els.approvalSection.classList.add("hidden");

  const duration = ((Date.now() - startTime) / 1000).toFixed(1);

  if (success) {
    els.completeIcon.textContent = "\u2705";
    els.completeSummary.textContent = data?.summary || "Task completed successfully";
    setStatus("Complete", "success");
    addTimelineEntry("complete", "Done", data?.summary || "");
  } else {
    els.completeIcon.textContent = "\u274C";
    els.completeSummary.textContent = data?.error || "Task failed";
    setStatus("Failed", "failed");
  }

  els.completeStats.textContent = `${stepCount} actions \u00B7 ${duration}s`;
}

function resetUI() {
  isRunning = false;
  els.inputSection.classList.remove("hidden");
  els.statusSection.classList.add("hidden");
  els.completeSection.classList.add("hidden");
  els.approvalSection.classList.add("hidden");
  els.screenshotContainer.classList.add("hidden");
  els.stopBtn.classList.add("hidden");
  els.taskInput.value = "";
  els.sendBtn.disabled = true;
  els.timeline.innerHTML = "";
}

function formatTime() {
  return new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

// ─── VOICE INPUT ──────────────────────────────────────────────

function toggleVoice() {
  if (isRecording) {
    stopVoice();
  } else {
    startVoice();
  }
}

function startVoice() {
  if (!("webkitSpeechRecognition" in window) && !("SpeechRecognition" in window)) {
    addTimelineEntry("error", "Voice", "Speech recognition not supported in this browser");
    return;
  }

  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  recognition = new SpeechRecognition();
  recognition.continuous = false;
  recognition.interimResults = true;
  recognition.lang = "en-US";

  recognition.onresult = (event) => {
    const transcript = Array.from(event.results)
      .map((r) => r[0].transcript)
      .join("");
    els.taskInput.value = transcript;
    els.sendBtn.disabled = !transcript.trim();
  };

  recognition.onend = () => {
    isRecording = false;
    els.voiceBtn.classList.remove("recording");
    // Auto-send if we got a result
    if (els.taskInput.value.trim()) {
      runTask();
    }
  };

  recognition.onerror = (e) => {
    isRecording = false;
    els.voiceBtn.classList.remove("recording");
    if (e.error !== "no-speech") {
      addTimelineEntry("error", "Voice", `Error: ${e.error}`);
    }
  };

  recognition.start();
  isRecording = true;
  els.voiceBtn.classList.add("recording");
}

function stopVoice() {
  if (recognition) {
    recognition.stop();
  }
  isRecording = false;
  els.voiceBtn.classList.remove("recording");
}

// ─── START ────────────────────────────────────────────────────

init();
