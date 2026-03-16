/**
 * G-Axis Side Panel Application
 *
 * Handles user interaction, voice input, and displays agent state
 * in real-time via messages from the background service worker.
 * Material Design 3 themed with smooth animations.
 */

import { MSG } from "../shared/types.js";

/** Check if extension context is still valid */
function extOk() {
  return !!(chrome.runtime && chrome.runtime.id);
}

/** Safe sendMessage wrapper — no-ops if extension context is dead */
function safeSend(msg, callback) {
  if (!extOk()) return;
  try {
    if (callback) {
      chrome.runtime.sendMessage(msg, callback);
    } else {
      chrome.runtime.sendMessage(msg);
    }
  } catch {
    // Extension context invalidated
  }
}

// Keep service worker alive while side panel is open
// Also receives messages from service worker via port (more reliable than runtime.sendMessage)
let keepAlivePort = null;
try {
  if (extOk()) {
    keepAlivePort = chrome.runtime.connect({ name: "keepalive" });
    keepAlivePort.onMessage.addListener((msg) => {
      handleMessage(msg);
    });
    keepAlivePort.onDisconnect.addListener(() => {
      keepAlivePort = null;
    });
  }
} catch {
  // Extension context invalidated on load
}

// ─── DOM ELEMENTS ─────────────────────────────────────────────

const $ = (id) => document.getElementById(id);

const els = {
  connectionStatus: $("connection-status"),
  settingsBtn: $("settings-btn"),
  taskInput: $("task-input"),
  voiceBtn: $("voice-btn"),
  sendBtn: $("send-btn"),
  attachBtn: $("attach-btn"),
  connectorsBtn: $("connectors-btn"),
  skillsBtn: $("skills-btn"),
  connectorsPanel: $("connectors-panel"),
  connectorsPanelClose: $("connectors-panel-close"),
  connectorsIcons: $("connectors-icons"),
  suggestions: $("suggestions"),
  welcomeSection: $("welcome-section"),
  statusSection: $("status-section"),
  agentStatusCard: $("agent-status-card"),
  agentAvatar: $("agent-avatar"),
  statusText: $("status-text"),
  agentSubtitle: $("agent-subtitle"),
  taskInstructionCard: $("task-instruction-card"),
  taskInstruction: $("task-instruction"),
  loadingDots: $("loading-dots"),
  stopBtn: $("stop-btn"),
  pauseBtn: $("pause-btn"),
  resumeBtn: $("resume-btn"),
  takeoverBtn: $("takeover-btn"),
  givebackBtn: $("giveback-btn"),
  screenshotContainer: $("screenshot-container"),
  screenshotImg: $("screenshot-img"),
  approvalSection: $("approval-section"),
  approvalAction: $("approval-action"),
  approvalReason: $("approval-reason"),
  approvalRisk: $("approval-risk"),
  approvalConfidence: $("approval-confidence"),
  approveBtn: $("approve-btn"),
  denyBtn: $("deny-btn"),
  inputBar: $("input-bar"),
  chatSection: $("chat-section"),
  chatMessages: $("chat-messages"),
  timeline: $("timeline"),
  timelineSection: $("timeline-section"),
  stepCounter: $("step-counter"),
  completeSection: $("complete-section"),
  completeIcon: $("complete-icon"),
  completeSummary: $("complete-summary"),
  completeStats: $("complete-stats"),
  newTaskBtn: $("new-task-btn"),
  cleanupBtn: $("cleanup-btn"),
  replayPlayer: $("replay-player"),
  replayCard: $("replay-card"),
  replayScreenshotWrap: $("replay-screenshot-wrap"),
  replayScreenshot: $("replay-screenshot"),
  replayScreenshotOverlay: $("replay-screenshot-overlay"),
  replayOverlayStep: $("replay-overlay-step"),
  replayOverlayAction: $("replay-overlay-action"),
  replayNoScreenshot: $("replay-no-screenshot"),
  replayStepIcon: $("replay-step-icon"),
  replayStepTitle: $("replay-step-title"),
  replayStepDetail: $("replay-step-detail"),
  replayStepUrl: $("replay-step-url"),
  replayStepStatus: $("replay-step-status"),
  replayStepIndicator: $("replay-step-indicator"),
  replayProgressFill: $("replay-progress-fill"),
  replayDots: $("replay-dots"),
  replayPrev: $("replay-prev"),
  replayPlay: $("replay-play"),
  replayNext: $("replay-next"),
  replayPlayIcon: $("replay-play-icon"),
  replayPauseIcon: $("replay-pause-icon"),
  replayDuration: $("replay-duration"),
  // Voice UI
  voiceSection: $("voice-section"),
  voiceOrb: $("voice-orb"),
  voiceStatusText: $("voice-status-text"),
  voiceTranscriptLive: $("voice-transcript-live"),
  voiceTranscript: $("voice-transcript"),
  voiceEndBtn: $("voice-end-btn"),
  personaSelect: $("persona-select"),
  dashboardSection: $("dashboard-section"),
  dashboardBtn: $("dashboard-btn"),
  dashCloseBtn: $("dash-close-btn"),
  voiceStreamBtn: $("voice-stream-btn"),
  voiceMicBtn: $("voice-mic-btn"),
  voiceNewBtn: $("voice-new-btn"),
  voiceLiveBadge: $("voice-live-badge"),
  micIconOn: $("mic-icon-on"),
  micIconOff: $("mic-icon-off"),
  streamPauseIcon: $("stream-pause-icon"),
  streamPlayIcon: $("stream-play-icon"),
  settingsOverlay: $("settings-overlay"),
  settingsPanel: $("settings-panel"),
  settingsCloseBtn: $("settings-close-btn"),
  settingsSaveBtn: $("settings-save-btn"),
  contentArea: $("content-area"),
  confirmSection: $("confirm-section"),
  confirmCard: $("confirm-card"),
  confirmIcon: $("confirm-icon"),
  confirmTitle: $("confirm-title"),
  confirmFields: $("confirm-fields"),
  confirmCreateBtn: $("confirm-create-btn"),
  confirmCancelBtn: $("confirm-cancel-btn"),
  confirmDragHandle: $("confirm-drag-handle"),
  confirmPinBtn: $("confirm-pin-btn"),
  operatorWindow: $("operator-window"),
  operatorTitle: $("operator-title"),
  operatorStatusBadge: $("operator-status-badge"),
  operatorActions: $("operator-actions"),
  operatorMessage: $("operator-message"),
  operatorMessageText: $("operator-message-text"),
  activityTracker: $("activity-tracker"),
  activityBar: $("activity-bar"),
  activityToggle: $("activity-toggle"),
  activitySteps: $("activity-steps"),
  activityIcon: $("activity-icon"),
  activityLabel: $("activity-label"),
  activityCounter: $("activity-counter"),
};

// Settings elements
const settingEls = {
  backendUrl: $("setting-backendUrl"),
  model: $("setting-model"),
  temperature: $("setting-temperature"),
  temperatureValue: $("temperature-value"),
  maxSteps: $("setting-maxSteps"),
  maxStepsValue: $("maxSteps-value"),
  confidenceThreshold: $("setting-confidenceThreshold"),
  confidenceThresholdValue: $("confidenceThreshold-value"),
  alwaysApprovePasswords: $("setting-alwaysApprovePasswords"),
  alwaysApprovePayments: $("setting-alwaysApprovePayments"),
  allowDownloads: $("setting-allowDownloads"),
};

// ─── STATE ────────────────────────────────────────────────────

// Single state machine — only one can be active at a time
// idle → planning → running → idle (or → needs_input → running)
let appState = "idle"; // "idle" | "planning" | "running" | "needs_input" | "paused" | "takeover"
let planExecuteInstruction = "";  // Refined instruction from planner
let plannerTimeout = null;
let recognition = null;
let isRecording = false;
let liveMode = false;        // Gemini Live Audio active
let liveAudioCtx = null;     // AudioContext for mic capture (16kHz)
let livePlayCtx = null;      // AudioContext for playback (24kHz)
let liveMicStream = null;    // MediaStream from getUserMedia
let livePlayQueue = [];      // Queued audio buffers for sequential playback
let livePlayingSource = null; // Currently playing AudioBufferSourceNode
let stepCount = 0;
let startTime = 0;
let narrativeStepNum = 0;
let lastActionType = "";
let lastActionGroup = "";
let currentAgent = null;
let activitySteps = []; // Array of { label, status: 'pending'|'active'|'done'|'failed' }
let activityExpanded = false;
let operatorActions = []; // Array of { label, value, status: 'pending'|'active'|'done'|'failed' }

// ─── AGENT CONFIG ─────────────────────────────────────────────

const AGENT_CONFIG = {
  perceiver: {
    name: "Perceiver",
    color: "#1a73e8",
    icon: `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M2 12s4-8 10-8 10 8 10 8-4 8-10 8-10-8-10-8z"/></svg>`,
    class: "perceiver",
  },
  orchestrator: {
    name: "Orchestrator",
    color: "#9334e6",
    icon: `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg>`,
    class: "orchestrator",
  },
  navigator: {
    name: "Navigator",
    color: "#e8710a",
    icon: `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2"><polygon points="3 11 22 2 13 21 11 13 3 11"/></svg>`,
    class: "navigator",
  },
  form_filler: {
    name: "Form Filler",
    color: "#34a853",
    icon: `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>`,
    class: "form-filler",
  },
  data_extractor: {
    name: "Data Extractor",
    color: "#ea4335",
    icon: `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/></svg>`,
    class: "data-extractor",
  },
  verifier: {
    name: "Verifier",
    color: "#f9ab00",
    icon: `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2"><path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg>`,
    class: "verifier",
  },
};

// ─── INITIALIZE ───────────────────────────────────────────────

function init() {
  console.log("[G-Axis] init() called");

  // Connect to backend
  safeSend({ type: MSG.CONNECT });

  // Input handling — multiple events for robustness
  const updateSendBtn = () => {
    els.sendBtn.disabled = !els.taskInput.value.trim();
  };
  els.taskInput.addEventListener("input", updateSendBtn);
  els.taskInput.addEventListener("keyup", updateSendBtn);
  els.taskInput.addEventListener("change", updateSendBtn);
  els.taskInput.addEventListener("focus", updateSendBtn);

  // Textarea: Enter sends, Shift+Enter newline
  els.taskInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (els.taskInput.value.trim()) runTask();
    }
  });

  // Auto-resize textarea as user types
  els.taskInput.addEventListener("input", () => {
    autoResizeTextarea();
  });

  els.sendBtn.addEventListener("click", runTask);
  els.stopBtn.addEventListener("click", stopTask);
  els.pauseBtn.addEventListener("click", pauseTask);
  els.resumeBtn.addEventListener("click", resumeTask);
  els.takeoverBtn.addEventListener("click", takeoverControl);
  els.givebackBtn.addEventListener("click", giveBackControl);
  els.voiceBtn.addEventListener("click", toggleVoice);

  // Dashboard
  if (els.dashboardBtn) {
    els.dashboardBtn.addEventListener("click", openDashboard);
  }
  if (els.dashCloseBtn) {
    els.dashCloseBtn.addEventListener("click", () => {
      els.dashboardSection.classList.add("hidden");
      els.welcomeSection.classList.remove("hidden");
    });
  }

  // Connector panel toggle
  els.connectorsBtn.addEventListener("click", toggleConnectorsPanel);
  els.connectorsPanelClose.addEventListener("click", () => {
    els.connectorsPanel.classList.add("hidden");
    els.connectorsBtn.classList.remove("active");
  });

  // Connector icon clicks — insert context into textarea
  els.connectorsIcons.addEventListener("click", (e) => {
    const btn = e.target.closest(".connector-icon-btn");
    if (!btn) return;
    const connector = btn.dataset.connector;
    btn.classList.toggle("selected");
    // Prepend connector hint to input if not already there
    const prefix = `@${connector} `;
    if (!els.taskInput.value.startsWith(prefix)) {
      els.taskInput.value = prefix + els.taskInput.value;
      els.taskInput.focus();
      autoResizeTextarea();
      updateSendBtn();
    }
  });
  els.approveBtn.addEventListener("click", () => sendApproval(true));
  els.denyBtn.addEventListener("click", () => sendApproval(false));
  els.newTaskBtn.addEventListener("click", resetUI);
  els.cleanupBtn.addEventListener("click", () => {
    safeSend({ type: MSG.CLEANUP_WORKSPACE });
    els.cleanupBtn.textContent = "Cleaned up!";
    els.cleanupBtn.disabled = true;
    addTimelineEntry("approved", "Workspace cleaned", "Closed all agent-created tabs");
    setTimeout(() => {
      els.cleanupBtn.classList.add("hidden");
      els.cleanupBtn.textContent = "Clean up workspace";
      els.cleanupBtn.disabled = false;
    }, 2000);
  });

  // Settings
  els.settingsBtn.addEventListener("click", openSettings);
  els.settingsCloseBtn.addEventListener("click", closeSettings);
  els.settingsOverlay.addEventListener("click", (e) => {
    if (e.target === els.settingsOverlay) closeSettings();
  });
  els.settingsSaveBtn.addEventListener("click", saveSettings);

  // Range input live values
  settingEls.temperature.addEventListener("input", () => {
    settingEls.temperatureValue.textContent = settingEls.temperature.value;
  });
  settingEls.maxSteps.addEventListener("input", () => {
    settingEls.maxStepsValue.textContent = settingEls.maxSteps.value;
  });
  settingEls.confidenceThreshold.addEventListener("input", () => {
    settingEls.confidenceThresholdValue.textContent = settingEls.confidenceThreshold.value;
  });

  // Suggestion buttons
  document.querySelectorAll(".suggestion-chip").forEach((btn) => {
    btn.addEventListener("click", () => {
      els.taskInput.value = btn.dataset.task;
      els.sendBtn.disabled = false;
      runTask();
    });
  });

  // Activity tracker
  initActivityTracker();

  // Listen for messages from background
  if (extOk()) {
    try { chrome.runtime.onMessage.addListener(handleMessage); } catch {}
  }
}

// ─── SETTINGS ─────────────────────────────────────────────────

function openSettings() {
  // Load current settings from storage
  safeSend({ type: MSG.GET_SETTINGS }, (response) => {
    if (response?.settings) {
      populateSettings(response.settings);
    }
  });

  els.settingsOverlay.classList.remove("hidden");
  // Force reflow then add visible class for animation
  void els.settingsOverlay.offsetWidth;
  els.settingsOverlay.classList.add("visible");
}

function closeSettings() {
  els.settingsOverlay.classList.remove("visible");
  setTimeout(() => {
    els.settingsOverlay.classList.add("hidden");
  }, 300);
}

function populateSettings(settings) {
  settingEls.backendUrl.value = settings.backendUrl || "http://localhost:8000";
  settingEls.model.value = settings.model || "gemini-2.5-flash";
  settingEls.temperature.value = settings.temperature ?? 0.2;
  settingEls.temperatureValue.textContent = settings.temperature ?? 0.2;
  settingEls.maxSteps.value = settings.maxSteps ?? 30;
  settingEls.maxStepsValue.textContent = settings.maxSteps ?? 30;
  settingEls.confidenceThreshold.value = settings.confidenceThreshold ?? 0.4;
  settingEls.confidenceThresholdValue.textContent = settings.confidenceThreshold ?? 0.4;

  settingEls.alwaysApprovePasswords.checked = settings.alwaysApprovePasswords ?? true;
  settingEls.alwaysApprovePayments.checked = settings.alwaysApprovePayments ?? true;
  settingEls.allowDownloads.checked = settings.allowDownloads ?? false;

  // Supervision mode radio
  const modeRadio = document.querySelector(
    `input[name="supervisionMode"][value="${settings.supervisionMode || "supervised"}"]`
  );
  if (modeRadio) modeRadio.checked = true;
}

function saveSettings() {
  const supervisionRadio = document.querySelector('input[name="supervisionMode"]:checked');

  const settings = {
    backendUrl: settingEls.backendUrl.value.trim(),
    model: settingEls.model.value,
    temperature: parseFloat(settingEls.temperature.value),
    maxSteps: parseInt(settingEls.maxSteps.value),
    supervisionMode: supervisionRadio?.value || "supervised",
    confidenceThreshold: parseFloat(settingEls.confidenceThreshold.value),
    alwaysApprovePasswords: settingEls.alwaysApprovePasswords.checked,
    alwaysApprovePayments: settingEls.alwaysApprovePayments.checked,
    allowDownloads: settingEls.allowDownloads.checked,
  };

  safeSend({ type: MSG.SAVE_SETTINGS, settings });

  // Visual feedback
  els.settingsSaveBtn.textContent = "Saved!";
  els.settingsSaveBtn.classList.add("saved");
  setTimeout(() => {
    els.settingsSaveBtn.textContent = "Save Settings";
    els.settingsSaveBtn.classList.remove("saved");
    closeSettings();
  }, 1000);
}

// ─── TASK EXECUTION ───────────────────────────────────────────

// Simple tasks go directly to execution (original flow).
// Complex tasks (shopping, booking, comparison) go through the planner first.
const COMPLEX_KEYWORDS = [
  "buy", "purchase", "order", "book", "reserve", "compare",
  "best", "recommend", "cheapest", "under", "budget",
  "grocery", "groceries", "shop", "shopping",
  "flight", "hotel", "ticket",
  "schedule", "meeting", "calendar", "event", "appointment",
  "email", "send", "compose", "research", "itinerary",
];

function isComplexTask(text) {
  const lower = text.toLowerCase();
  return COMPLEX_KEYWORDS.some((kw) => lower.includes(kw));
}

function runTask() {
  // If live mode is active, send text to the live session
  if (liveMode) {
    const text = els.taskInput.value.trim();
    if (!text) return;
    addChatMessage("user", text);
    safeSend({ type: MSG.LIVE_TEXT, text });
    els.taskInput.value = "";
    els.sendBtn.disabled = true;
    return;
  }


  // If waiting for user input (graceful handover during execution)
  if (appState === "needs_input") {
    sendUserInput();
    return;
  }

  // If in takeover mode, user can type "continue" to give back or send context
  if (appState === "takeover") {
    const text = els.taskInput.value.trim().toLowerCase();
    if (text === "continue" || text === "done" || text === "go ahead") {
      els.taskInput.value = "";
      giveBackControl();
    } else {
      sendUserInput();
    }
    return;
  }

  // If running, user is steering the agent mid-task
  if (appState === "running") {
    sendSteering();
    return;
  }

  // If in planning conversation, send as chat reply
  if (appState === "planning") {
    sendPlanChat();
    return;
  }

  const instruction = els.taskInput.value.trim();
  if (!instruction) return;

  // Always run conversational planner first — consistent UX for all tasks
  startPlanning(instruction);
}

// Original direct execution flow — untouched
function executeDirectly(instruction) {
  appState = "running";
  stepCount = 0;
  startTime = Date.now();
  currentAgent = null;

  safeSend({ type: MSG.RUN_TASK, instruction });

  // Update UI — exactly as before
  els.welcomeSection.classList.add("hidden");
  els.chatSection.classList.add("hidden");
  els.statusSection.classList.remove("hidden");
  showHandoverControls("running");
  els.completeSection.classList.add("hidden");
  els.timelineSection.classList.remove("hidden");
  els.taskInstructionCard.classList.remove("hidden");
  els.taskInstruction.textContent = instruction;
  els.timeline.innerHTML = "";
  els.loadingDots.classList.remove("hidden");

  setStatus("Starting", "", "Initializing task...");
  updateAgentAvatar(null);
  updateStepCounter();

  // Operator window: show inferred action plan
  const plan = inferOperatorPlan(instruction);
  if (plan.length > 0) {
    showOperatorWindow("Action Plan");
    plan.forEach((p) => addOperatorAction(p.label, p.value, "pending"));
    // Set first action as active
    if (operatorActions.length > 0) setOperatorActionActive(0);
  }

  addTimelineEntry("start", "Task started", instruction);

  // Clear input — keep enabled for mid-task steering
  els.taskInput.value = "";
  els.taskInput.placeholder = "Type to steer the agent (e.g. 'make it 11am')...";
  els.sendBtn.disabled = true; // Re-enabled on input
}

// Planning flow — for complex tasks that need clarification
function startPlanning(instruction) {
  appState = "planning";
  startTime = Date.now();

  // Show chat section alongside status
  els.welcomeSection.classList.add("hidden");
  els.completeSection.classList.add("hidden");
  els.chatSection.classList.remove("hidden");
  els.statusSection.classList.remove("hidden");
  showHandoverControls("running");
  els.chatMessages.innerHTML = "";

  setStatus("Thinking", "executing", "Understanding your request...");
  updateAgentAvatar("orchestrator");

  // Add user bubble
  addChatBubble("user", instruction);

  // Show typing indicator
  showTypingIndicator();

  // Send to planner
  safeSend({ type: MSG.PLAN_CHAT, text: instruction });

  // Fallback: if no response in 8s, skip planner and execute directly
  plannerTimeout = setTimeout(() => {
    if (appState === "planning") {
      removeTypingIndicator();
      addChatBubble("agent", "Let me help you with that right away.");
      executePlannedTask(instruction);
    }
  }, 8000);

  // Update input
  els.taskInput.value = "";
  els.taskInput.placeholder = "Reply to G-Axis...";
  els.sendBtn.disabled = true;
}

function sendPlanChat() {
  const text = els.taskInput.value.trim();
  if (!text) return;

  addChatBubble("user", text);
  showTypingIndicator();
  safeSend({ type: MSG.PLAN_CHAT, text });

  // Fallback timeout for follow-up messages too
  if (plannerTimeout) clearTimeout(plannerTimeout);
  plannerTimeout = setTimeout(() => {
    if (appState === "planning") {
      removeTypingIndicator();
      addChatBubble("agent", "Let me proceed with what I know.");
      executePlannedTask(text);
    }
  }, 8000);

  els.taskInput.value = "";
  els.sendBtn.disabled = true;
}

function handlePlanResponse(data) {
  // Clear fallback timeout
  if (plannerTimeout) { clearTimeout(plannerTimeout); plannerTimeout = null; }

  // Remove typing indicator
  removeTypingIndicator();

  // Add agent message
  const agentBubble = addChatBubble("agent", data.message);

  // Add recommendations if any
  if (data.recommendations && data.recommendations.length > 0) {
    const recsDiv = document.createElement("div");
    recsDiv.className = "chat-recommendations";
    data.recommendations.forEach((rec) => {
      const item = document.createElement("div");
      item.className = "chat-recommendation-item";
      item.textContent = rec;
      recsDiv.appendChild(item);
    });
    agentBubble.appendChild(recsDiv);
  }

  // Speak the response (TTS)
  speakText(data.message);

  if (data.ready_to_execute && data.plan) {
    // Show execute button
    const executeBtn = document.createElement("button");
    executeBtn.className = "chat-execute-btn";
    executeBtn.innerHTML = `
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg>
      Let's go
    `;
    planExecuteInstruction = data.refined_instruction || data.plan.refined_instruction || data.plan.action;
    executeBtn.addEventListener("click", () => {
      executeBtn.disabled = true;
      executeBtn.textContent = "Starting...";
      executePlannedTask(planExecuteInstruction);
    });
    els.chatMessages.appendChild(executeBtn);
  } else if (data.questions && data.questions.length > 0) {
    // Show quick reply chips for questions
    const chipsDiv = document.createElement("div");
    chipsDiv.className = "chat-quick-replies";
    data.questions.forEach((q) => {
      // Don't add chip for the question itself — it's already in the message
    });
  }

  scrollChatToBottom();
}

function executePlannedTask(instruction) {
  appState = "running";

  // Transition: hide chat, show execution UI
  els.chatSection.classList.add("hidden");
  els.statusSection.classList.remove("hidden");
  showHandoverControls("running");
  els.timelineSection.classList.remove("hidden");
  els.taskInstructionCard.classList.remove("hidden");
  els.taskInstruction.textContent = instruction;
  els.timeline.innerHTML = "";
  els.loadingDots.classList.remove("hidden");

  appState = "running";
  stepCount = 0;
  currentAgent = null;

  setStatus("Starting", "", "Initializing task...");
  updateAgentAvatar(null);
  updateStepCounter();

  // Operator window: show inferred action plan
  const plan = inferOperatorPlan(instruction);
  if (plan.length > 0) {
    showOperatorWindow("Action Plan");
    plan.forEach((p) => addOperatorAction(p.label, p.value, "pending"));
    if (operatorActions.length > 0) setOperatorActionActive(0);
  }

  addTimelineEntry("start", "Task started", instruction);

  // Keep input enabled for mid-task steering
  els.taskInput.placeholder = "Type to steer the agent (e.g. 'make it 11am')...";

  safeSend({ type: MSG.RUN_TASK, instruction });

  els.taskInput.value = "";
  els.sendBtn.disabled = true; // Re-enabled on input
}

function addChatBubble(role, text) {
  const bubble = document.createElement("div");
  bubble.className = `chat-bubble ${role}`;

  if (role === "agent") {
    bubble.innerHTML = `
      <div class="agent-label">
        <svg viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="10" fill="#e8f0fe"/><path d="M12 6L17 12L12 18L7 12Z" fill="#1a73e8"/></svg>
        G-Axis
      </div>
      <div class="agent-text">${escapeHtml(text)}</div>
    `;
  } else {
    bubble.textContent = text;
  }

  els.chatMessages.appendChild(bubble);
  scrollChatToBottom();
  return bubble;
}

function showTypingIndicator() {
  removeTypingIndicator();
  const typing = document.createElement("div");
  typing.className = "chat-typing";
  typing.id = "chat-typing";
  typing.innerHTML = "<span></span><span></span><span></span>";
  els.chatMessages.appendChild(typing);
  scrollChatToBottom();
}

function removeTypingIndicator() {
  const existing = document.getElementById("chat-typing");
  if (existing) existing.remove();
}

function scrollChatToBottom() {
  requestAnimationFrame(() => {
    els.contentArea.scrollTop = els.contentArea.scrollHeight;
  });
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

// ─── TEXT-TO-SPEECH (AGENT VOICE) ──────────────────────────
// Voice personality: warm, calm, friendly — like a trusted companion.
// Natural pacing with slight warmth. Never robotic.

let _selectedVoice = null;
let _voicesLoaded = false;

function _pickBestVoice() {
  if (_selectedVoice) return _selectedVoice;
  const voices = window.speechSynthesis.getVoices();
  if (!voices.length) return null;

  // Priority order: natural-sounding English voices
  // Prefer female voices for warmth (Samantha on macOS, Google UK on Chrome)
  const priorities = [
    (v) => v.name === "Samantha",                          // macOS — warm, natural
    (v) => v.name === "Karen",                             // macOS AU — friendly
    (v) => v.name.includes("Google UK English Female"),    // Chrome — clear, warm
    (v) => v.name.includes("Google US English"),           // Chrome — natural
    (v) => v.name === "Zarvox" ? false : v.name.includes("Natural"), // Any "Natural" voice
    (v) => v.lang.startsWith("en") && v.name.includes("Female"),
    (v) => v.lang.startsWith("en") && !v.name.includes("Whisper"),
  ];

  for (const test of priorities) {
    const match = voices.find(test);
    if (match) {
      _selectedVoice = match;
      console.log(`[G-Axis] Voice selected: ${match.name} (${match.lang})`);
      return match;
    }
  }

  // Fallback: first English voice
  _selectedVoice = voices.find((v) => v.lang.startsWith("en")) || voices[0];
  return _selectedVoice;
}

// Pre-load voices (they load asynchronously in Chrome)
if ("speechSynthesis" in window) {
  window.speechSynthesis.onvoiceschanged = () => {
    _voicesLoaded = true;
    _pickBestVoice();
  };
  // Try immediately too (Firefox loads sync)
  if (window.speechSynthesis.getVoices().length) {
    _voicesLoaded = true;
    _pickBestVoice();
  }
}

function speakText(text) {
  if (!("speechSynthesis" in window)) return;
  if (!text || text.trim().length === 0) return;

  // Cancel any ongoing speech
  window.speechSynthesis.cancel();

  // Clean up text for natural speech
  let speakable = text
    .replace(/https?:\/\/\S+/g, "")      // Remove URLs (sounds awful spoken)
    .replace(/[#*_`~]/g, "")              // Remove markdown formatting
    .replace(/\s{2,}/g, " ")             // Collapse whitespace
    .replace(/\n+/g, ". ")               // Newlines → pauses
    .trim();

  if (!speakable) return;

  // Truncate very long text (TTS shouldn't read an essay)
  if (speakable.length > 300) {
    speakable = speakable.slice(0, 300) + "... and more.";
  }

  const utterance = new SpeechSynthesisUtterance(speakable);
  utterance.rate = 1.0;    // Natural pace — not rushed
  utterance.pitch = 1.05;  // Slightly warm pitch
  utterance.volume = 0.85;

  const voice = _pickBestVoice();
  if (voice) utterance.voice = voice;

  window.speechSynthesis.speak(utterance);
}

function stopTask() {
  safeSend({ type: MSG.STOP_TASK });
  resetUI();
}

function pauseTask() {
  safeSend({ type: MSG.PAUSE_TASK });
  appState = "paused";
  showHandoverControls("paused");
  setStatus("Paused", "paused", "Agent paused — resume whenever you're ready");
  addTimelineEntry("agent", "Paused", "Agent paused by user", null, null, "orchestrator");
}

function resumeTask() {
  safeSend({ type: MSG.RESUME_TASK });
  appState = "running";
  showHandoverControls("running");
  setStatus("Resuming", "executing", "Picking up where we left off...");
  addTimelineEntry("action", "Resumed", "Agent resumed", null, null, "orchestrator");
}

function takeoverControl() {
  safeSend({ type: MSG.TAKEOVER });
  appState = "takeover";
  showHandoverControls("takeover");
  setStatus("You're in control", "takeover", "Do your thing — I'll wait right here");
  addTimelineEntry("agent", "Takeover", "Human took manual control", null, null, "orchestrator");
  // Enable input for user to chat while in control
  els.taskInput.placeholder = "Tell the agent what you did, or say 'continue'...";
  els.sendBtn.disabled = false;
}

function giveBackControl() {
  safeSend({ type: MSG.GIVE_BACK });
  appState = "running";
  showHandoverControls("running");
  setStatus("Back on it", "executing", "Continuing where you left off...");
  addTimelineEntry("action", "Handback", "User gave control back to agent", null, null, "orchestrator");
  els.taskInput.placeholder = "Type to steer the agent (e.g. 'make it 11am')...";
  els.sendBtn.disabled = true;
}

function showHandoverControls(state) {
  // state: "running" | "paused" | "takeover"
  const running = state === "running";
  const paused = state === "paused";
  const takeover = state === "takeover";

  els.pauseBtn.classList.toggle("hidden", !running);
  els.takeoverBtn.classList.toggle("hidden", !running);
  els.resumeBtn.classList.toggle("hidden", !paused);
  els.givebackBtn.classList.toggle("hidden", !takeover);
  els.stopBtn.classList.remove("hidden");
}

function sendApproval(approved) {
  safeSend({ type: approved ? MSG.APPROVE : MSG.DENY });
  els.approvalSection.classList.add("hidden");
  if (approved) {
    addTimelineEntry("approved", "Approved", "");
  } else {
    addTimelineEntry("denied", "Denied by operator", "");
  }
}

function showUserInputPrompt(message) {
  appState = "needs_input";
  // Re-enable input bar for user to respond
  els.taskInput.placeholder = "Type your guidance or 'continue' to keep going...";
  els.taskInput.focus();
  els.sendBtn.disabled = false;
  speakText(message || "I could use a little help here. What would you like me to do?");
}

function sendUserInput() {
  const text = els.taskInput.value.trim();
  if (!text) return;

  safeSend({ type: MSG.USER_INPUT, text });
  addTimelineEntry("approved", "Your guidance", text);
  setStatus("Resuming", "executing", "Agent is continuing with your guidance...");

  els.taskInput.value = "";
  els.taskInput.placeholder = "Assign a task or ask anything...";
  els.sendBtn.disabled = true;
  appState = "running";
}

/** Mid-task steering — user types guidance while agent is executing */
function sendSteering() {
  const text = els.taskInput.value.trim();
  if (!text) return;

  safeSend({ type: MSG.USER_INPUT, text, steering: true });
  addTimelineEntry("steer", "You guided", text);
  setStatus("Adjusting", "executing", "Applying your change...");

  els.taskInput.value = "";
  els.sendBtn.disabled = true;
}

// ─── MESSAGE HANDLER ──────────────────────────────────────────

function handleMessage(msg) {
  switch (msg.type) {
    case MSG.CONNECTION_STATUS:
      els.connectionStatus.className = `status-dot ${msg.data.connected ? "connected" : "disconnected"}`;
      els.connectionStatus.title = msg.data.connected ? "Connected" : "Disconnected";
      break;

    case MSG.TASK_STARTED:
      setStatus("Working on it", "executing", "Getting things ready...");
      els.loadingDots.classList.add("hidden");
      speakText("Alright, I'm on it!");
      // Activity tracker: show and add first step
      activitySteps = [];
      showActivityTracker();
      addActivityStep("Starting task", "active");
      break;

    case MSG.PERCEIVING: {
      setStatus("Looking at the page", "perceiving", msg.data?.url || "Understanding what's on screen...");
      updateAgentAvatar("perceiver");
      addTimelineEntry("eye", "Analyzing", msg.data?.url || "", null, null, "perceiver");
      // Activity tracker: mark previous active done, add perceiving step
      const prevPerceive = findLastActiveStep();
      if (prevPerceive >= 0) updateActivityStep(prevPerceive, "done");
      addActivityStep("Analyzing page", "active");
      break;
    }

    case MSG.PERCEPTION:
      if (msg.data?.screenshot) {
        els.screenshotContainer.classList.remove("hidden");
        els.screenshotImg.src = `data:image/jpeg;base64,${msg.data.screenshot}`;
      }
      if (msg.data?.page_summary) {
        addTimelineEntry("brain", "Understood", msg.data.page_summary, null, null, "orchestrator");
      }
      break;

    case MSG.ACTION_PLANNED: {
      const rawAction = msg.data?.action_type || "action";
      const n = narrativeDescription(rawAction, msg.data);
      setStatus(n.title, "executing", n.subtitle);
      updateAgentAvatar(n.agentType || "navigator");
      addTimelineEntry(
        "action",
        n.title,
        n.subtitle,
        msg.data?.risk_level,
        msg.data?.confidence,
        n.agentType || "navigator"
      );
      // Activity tracker: mark previous active done, add new action step
      const prevAction = findLastActiveStep();
      if (prevAction >= 0) updateActivityStep(prevAction, "done");
      addActivityStep(n.subtitle || n.title, "active");

      // Operator window: advance to next pending action
      advanceOperatorPlan(msg.data?.action_type, msg.data?.reasoning);
      break;
    }

    case MSG.ACTION_SUCCEEDED: {
      stepCount++;
      updateStepCounter();
      // Mark last timeline entry as success
      const entries = els.timeline.querySelectorAll(".timeline-entry");
      const lastEntry = entries[entries.length - 1];
      if (lastEntry) {
        lastEntry.classList.remove("active");
        const iconEl = lastEntry.querySelector(".timeline-icon");
        if (iconEl) {
          iconEl.className = "timeline-icon icon-success";
          iconEl.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M20 6L9 17l-5-5"/></svg>`;
        }
      }
      // Activity tracker: mark current active step as done
      const activeSucc = findLastActiveStep();
      if (activeSucc >= 0) updateActivityStep(activeSucc, "done");
      break;
    }

    case MSG.ACTION_FAILED:
      addTimelineEntry("error", "Failed", msg.data?.error || "Unknown error", null, null, "error");
      break;

    case MSG.APPROVAL_NEEDED:
      setStatus("Need your okay", "awaiting", "Quick confirmation needed");
      showApproval(msg.data);
      speakText("Hey, I need a quick okay from you before I continue.");
      break;

    case MSG.CONFIRM_ACTION:
      showConfirmation(msg.data);
      break;

    case MSG.STEERING_RECEIVED:
      addTimelineEntry("steer", "Steering received", msg.data?.text || "Adjusting...");
      setStatus("Adjusting", "executing", "Processing your guidance...");
      break;

    case MSG.STEERING_APPLIED: {
      const updates = msg.data?.updates || {};
      const summary = Object.entries(updates).map(([k, v]) => `${k}: ${v}`).join(", ");
      addTimelineEntry("approved", "Applied changes", summary);
      setStatus("Continuing", "executing", `Updated: ${summary}`);
      break;
    }

    case MSG.DOM_BLOCKER: {
      const bStatus = msg.data?.status || "blocked";
      const bText = (msg.data?.text || "").slice(0, 60);
      if (bStatus === "dismissed") {
        addTimelineEntry("approved", "Popup dismissed", bText || "Auto-dismissed");
      } else {
        addTimelineEntry("error", "Popup detected", bText || "Analyzing blocker...");
        setStatus("Handling popup", "executing", "Detected an overlay — resolving...");
      }
      break;
    }

    case MSG.TASK_COMPLETED: {
      // Handle duplicate task_completed — second one may have replay data
      if (appState === "idle" && msg.data?.replay) {
        initReplayPlayer(msg.data.replay);
        break;
      }
      appState = "idle";
      els.loadingDots.classList.add("hidden");
      // Activity tracker: mark all active as done, add final step
      const activeDone = findLastActiveStep();
      if (activeDone >= 0) updateActivityStep(activeDone, "done");
      addActivityStep("Done! Delivering results", "done");
      syncActivityBar();
      // Operator window: complete with summary
      completeOperatorWindow(msg.data?.summary || "Task completed successfully", true);
      showComplete(true, msg.data);
      els.taskInput.placeholder = "Assign a task or ask anything...";
      break;
    }

    case MSG.TASK_FAILED: {
      appState = "idle";
      els.loadingDots.classList.add("hidden");
      els.taskInput.placeholder = "Assign a task or ask anything...";
      // Activity tracker: mark current as failed
      const activeFail = findLastActiveStep();
      if (activeFail >= 0) updateActivityStep(activeFail, "failed");
      markCurrentActivityFailed();
      els.activityLabel.textContent = "Ran into an issue";
      // Operator window: mark failed
      completeOperatorWindow(msg.data?.error || "Task failed", false);
      showComplete(false, msg.data);
      break;
    }

    case MSG.TASK_STOPPED:
      appState = "idle";
      els.loadingDots.classList.add("hidden");
      addTimelineEntry("agent", "Stopped", msg.data?.message || "Task stopped", null, null, "orchestrator");
      speakText(msg.data?.message || "Got it, I've stopped.");
      showComplete(false, { error: msg.data?.message || "Task stopped by user" });
      break;

    case MSG.TASK_PAUSED:
      appState = "paused";
      showHandoverControls("paused");
      setStatus("Paused", "paused", msg.data?.message || "Agent paused");
      addTimelineEntry("agent", "Paused", msg.data?.message || "Agent paused", null, null, "orchestrator");
      speakText(msg.data?.message || "Sure, I'll pause here. Take your time.");
      break;

    case MSG.TASK_RESUMED:
      appState = "running";
      showHandoverControls("running");
      setStatus("Resuming", "executing", msg.data?.message || "Continuing...");
      addTimelineEntry("action", "Resumed", msg.data?.message || "Agent resumed", null, null, "orchestrator");
      speakText(msg.data?.message || "Thanks, I'll pick up right where we left off.");
      break;

    case MSG.HUMAN_TAKEOVER:
      appState = "takeover";
      showHandoverControls("takeover");
      setStatus("You're in control", "takeover", msg.data?.message || "Agent stepped aside");
      addTimelineEntry("agent", "Takeover", msg.data?.message || "Human took control", null, null, "orchestrator");
      speakText(msg.data?.message || "You've got it! I'll wait right here.");
      els.taskInput.placeholder = "Tell the agent what you did, or say 'continue'...";
      els.sendBtn.disabled = false;
      break;

    case MSG.AGENT_RESUMED:
      appState = "running";
      showHandoverControls("running");
      setStatus("Back on it", "executing", msg.data?.message || "Agent continuing...");
      addTimelineEntry("action", "Handback", msg.data?.message || "Agent resumed control", null, null, "orchestrator");
      speakText(msg.data?.message || "Thanks! I'll take it from here.");
      els.taskInput.placeholder = "Assign a task or ask anything...";
      els.sendBtn.disabled = true;
      break;

    case MSG.AGENT_ACTIVE: {
      const agentKey = msg.data?.agent || "";
      const config = AGENT_CONFIG[agentKey];
      const agentName = config?.name || msg.data?.agent || "Agent";

      setStatus(`${agentName} active`, "executing", msg.data?.subtask || "Working...");
      updateAgentAvatar(agentKey);

      if (msg.data?.subtask) {
        addTimelineEntry("agent", agentName, msg.data.subtask, null, null, agentKey);
      }
      break;
    }

    case MSG.MEMORY_LOADED:
      if (msg.data?.episodes > 0 || msg.data?.similar > 0) {
        addTimelineEntry(
          "brain",
          "Memory loaded",
          `${msg.data.episodes || 0} past visits, ${msg.data.patterns || 0} patterns, ${msg.data.similar || 0} similar tasks`,
          null,
          null,
          "orchestrator"
        );
      }
      break;

    case MSG.PLAN_RESPONSE:
      handlePlanResponse(msg.data || {});
      break;

    case MSG.NEEDS_INPUT:
      setStatus("Quick question", "awaiting", msg.data?.message || "Could use your input");
      addTimelineEntry("brain", "Asking you", msg.data?.message || "Need a little guidance", null, null, "orchestrator");
      showUserInputPrompt(msg.data?.message || "How would you like me to handle this?");
      break;

    case MSG.ERROR:
      addTimelineEntry("error", "Error", msg.data?.message || "Unknown error", null, null, "error");
      break;

    case MSG.RESEARCH_COMPLETE: {
      const md = msg.data?.markdown || "";
      const downloadUrl = msg.data?.download_url || "";
      const docTitle = msg.data?.title || "Research";
      showResearchInline(docTitle, md, downloadUrl);
      break;
    }

    // ── Live Audio ──
    case MSG.LIVE_AUDIO_OUT:
      if (liveMode && msg.data) {
        playLiveAudioChunk(msg.data);
        if (!els.voiceOrb.classList.contains("speaking")) {
          els.voiceOrb.className = "voice-orb speaking";
          els.voiceStatusText.textContent = "Speaking...";
          playVoiceSound("response");
        }
      }
      break;

    case MSG.LIVE_TRANSCRIPT_IN:
      if (msg.data?.text) {
        addVoiceBubble("user", msg.data.text);
        els.voiceTranscriptLive.textContent = "";
        els.voiceOrb.className = "voice-orb thinking";
        els.voiceStatusText.textContent = "Thinking...";
        playVoiceSound("thinking");
      }
      break;

    case MSG.LIVE_TRANSCRIPT_OUT:
      if (msg.data?.text) {
        addVoiceBubble("agent", msg.data.text);
        setTimeout(() => {
          if (liveMode && isRecording) {
            els.voiceOrb.className = "voice-orb listening";
            els.voiceStatusText.textContent = "Listening...";
          }
        }, 500);
      }
      break;

    case MSG.LIVE_STATUS: {
      const st = msg.data?.status;
      if (window._liveReconnectTimeout) { clearTimeout(window._liveReconnectTimeout); window._liveReconnectTimeout = null; }

      if (st === "connected") {
        els.voiceOrb.className = "voice-orb listening";
        els.voiceStatusText.textContent = "Listening...";
        if (els.voiceLiveBadge) els.voiceLiveBadge.className = "voice-live-badge";
        playVoiceSound("wake");
      } else if (st === "reconnecting") {
        els.voiceOrb.className = "voice-orb connecting";
        els.voiceStatusText.textContent = msg.data?.message || "Extending session...";
        if (els.voiceLiveBadge) els.voiceLiveBadge.className = "voice-live-badge paused";
        // Show error if reconnect takes >10s
        window._liveReconnectTimeout = setTimeout(() => {
          if (liveMode && els.voiceOrb.classList.contains("connecting")) {
            els.voiceOrb.className = "voice-orb error";
            els.voiceStatusText.textContent = "Reconnection failed — click New";
            if (els.voiceLiveBadge) els.voiceLiveBadge.className = "voice-live-badge paused";
          }
        }, 10000);
      } else if (st === "error") {
        els.voiceOrb.className = "voice-orb error";
        els.voiceStatusText.textContent = msg.data?.message || "Connection failed";
        if (els.voiceLiveBadge) els.voiceLiveBadge.className = "voice-live-badge paused";
        playVoiceSound("error");
      } else if (st === "disconnected") {
        els.voiceOrb.className = "voice-orb idle";
        els.voiceStatusText.textContent = "Session ended";
        if (els.voiceLiveBadge) els.voiceLiveBadge.className = "voice-live-badge paused";
        playVoiceSound("end");
      }
      break;
    }
  }
}

// ─── UI HELPERS ───────────────────────────────────────────────

function setStatus(text, className, subtitle) {
  els.statusText.textContent = text;
  els.statusText.className = className || "";
  if (subtitle !== undefined) {
    els.agentSubtitle.textContent = subtitle;
  }
}

function updateAgentAvatar(agentKey) {
  const config = AGENT_CONFIG[agentKey];
  // Remove all agent classes
  els.agentAvatar.className = "agent-avatar";
  if (config) {
    els.agentAvatar.classList.add(config.class);
    els.agentAvatar.innerHTML = `<div class="agent-pulse-ring"></div>${config.icon}`;
  } else {
    els.agentAvatar.innerHTML = `<div class="agent-pulse-ring"></div><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg>`;
  }
  currentAgent = agentKey;
}

// ─── NARRATIVE ENGINE ─────────────────────────────────────────
// Transforms raw action types into human-friendly step descriptions

function narrativeDescription(actionType, data) {
  const url = data?.url || "";
  const text = data?.text || "";
  const fields = data?.fields || [];
  const key = data?.key || "";
  const elementDesc = data?.element_description || "";
  const reasoning = data?.reasoning || "";

  switch (actionType) {
    case "navigate": {
      let dest = "a new page";
      if (url.includes("calendar.google.com/calendar")) {
        if (url.includes("eventedit")) dest = "Calendar event editor";
        else dest = "Google Calendar";
      } else if (url.includes("mail.google.com")) dest = "Gmail";
      else if (url.includes("docs.google.com")) dest = "Google Docs";
      else if (url.includes("sheets.google.com")) dest = "Google Sheets";
      else if (url.includes("meet.google.com")) dest = "Google Meet";
      else if (url.includes("drive.google.com")) dest = "Google Drive";
      else if (url.includes("youtube.com")) dest = "YouTube";
      else if (url) {
        try { dest = new URL(url).hostname.replace("www.", ""); } catch {}
      }
      return { title: "Opening workspace", subtitle: `Navigating to ${dest}`, group: "navigate", agentType: "navigator" };
    }
    case "fill_form": {
      const fieldNames = fields.map(f =>
        f.label || f.field || f.name
        || (f.hints && (f.hints.aria || f.hints.placeholder || f.hints.text))
        || ""
      ).filter(Boolean);
      let subtitle = "Filling in form details";
      if (fieldNames.length === 1) {
        subtitle = `Adding ${fieldNames[0].toLowerCase()}`;
      } else if (fieldNames.length > 1) {
        subtitle = `Adding ${fieldNames.map(n => n.toLowerCase()).join(", ")}`;
      }
      return { title: "Filling details", subtitle, group: "fill_form", agentType: "form_filler" };
    }
    case "type_text":
    case "type": {
      const target = elementDesc || reasoning || "field";
      return { title: "Entering information", subtitle: `Typing into ${target}`, group: "fill_form", agentType: "form_filler" };
    }
    case "click": {
      const target = elementDesc || reasoning || "element";
      return { title: "Selecting option", subtitle: `Clicking ${target}`, group: "click", agentType: "navigator" };
    }
    case "press_key": {
      const keyName = key === "Enter" ? "confirm" : key === "Tab" ? "move to next field" : key === "Escape" ? "dismiss" : `press ${key}`;
      return { title: "Confirming action", subtitle: `Pressing ${key} to ${keyName}`, group: "press_key", agentType: "navigator" };
    }
    case "scroll": {
      const dir = data?.direction || "down";
      return { title: "Browsing content", subtitle: `Scrolling ${dir} to find more`, group: "scroll", agentType: "navigator" };
    }
    case "select_all_and_type": {
      const target = elementDesc || reasoning || "field";
      return { title: "Updating field", subtitle: `Replacing text in ${target}`, group: "fill_form", agentType: "form_filler" };
    }
    case "wait":
      return { title: "Waiting", subtitle: "Giving the page a moment to load", group: "wait", agentType: "navigator" };
    case "workspace_tab":
      return { title: "Opening workspace", subtitle: reasoning || "Setting up the workspace", group: "navigate", agentType: "orchestrator" };
    default: {
      const fallback = reasoning || `Performing ${actionType.replace(/_/g, " ")}`;
      return { title: actionType.replace(/_/g, " "), subtitle: fallback, group: actionType, agentType: "navigator" };
    }
  }
}

function shouldGroupWithPrevious(actionType, data) {
  const narrative = narrativeDescription(actionType, data);
  // Group consecutive actions with the same group (e.g., fill_form + fill_form, fill_form + type_text)
  return lastActionGroup === narrative.group && narrative.group === "fill_form";
}

function updateGroupedEntry(narrative) {
  // Update the last timeline entry's subtitle to reflect accumulated work
  const entries = els.timeline.querySelectorAll(".timeline-entry");
  const lastEntry = entries[entries.length - 1];
  if (lastEntry) {
    const reasoningEl = lastEntry.querySelector(".reasoning");
    if (reasoningEl) {
      reasoningEl.textContent = narrative.subtitle;
    }
  }
}

// ─── EXECUTION REPLAY PLAYER ──────────────────────────────────

let replayData = null;
let replayIndex = 0;
let replayPlaying = false;
let replayTimer = null;

function initReplayPlayer(data) {
  if (!data || !data.steps || data.steps.length === 0) return;
  replayData = data;
  replayIndex = 0;
  replayPlaying = false;

  els.replayPlayer.classList.remove("hidden");
  els.replayDuration.textContent = formatDuration(data.duration_ms);

  // Render step dots on timeline
  els.replayDots.innerHTML = "";
  data.steps.forEach((s, i) => {
    const dot = document.createElement("div");
    dot.className = `replay-dot ${s.success ? "" : "failed"}`;
    dot.title = `Step ${i + 1}: ${s.action}`;
    dot.onclick = () => replayGoTo(i);
    els.replayDots.appendChild(dot);
  });

  // Bind controls
  els.replayPrev.onclick = () => replayGoTo(replayIndex - 1);
  els.replayNext.onclick = () => replayGoTo(replayIndex + 1);
  els.replayPlay.onclick = toggleReplayPlayback;
  els.replayProgressFill.parentElement.onclick = (e) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const pct = (e.clientX - rect.left) / rect.width;
    const idx = Math.round(pct * (replayData.steps.length - 1));
    replayGoTo(idx);
  };

  renderReplayStep(0);
}

function replayGoTo(idx) {
  if (!replayData) return;
  replayIndex = Math.max(0, Math.min(idx, replayData.steps.length - 1));
  renderReplayStep(replayIndex);
}

function toggleReplayPlayback() {
  if (replayPlaying) {
    replayPlaying = false;
    clearInterval(replayTimer);
    els.replayPlayIcon.classList.remove("hidden");
    els.replayPauseIcon.classList.add("hidden");
  } else {
    replayPlaying = true;
    els.replayPlayIcon.classList.add("hidden");
    els.replayPauseIcon.classList.remove("hidden");
    if (replayIndex >= replayData.steps.length - 1) replayIndex = -1;
    replayTimer = setInterval(() => {
      replayIndex++;
      if (replayIndex >= replayData.steps.length) {
        replayIndex = replayData.steps.length - 1;
        toggleReplayPlayback(); // Stop at end
        return;
      }
      renderReplayStep(replayIndex);
    }, 1500);
  }
}

function renderReplayStep(idx) {
  const step = replayData.steps[idx];
  if (!step) return;

  const narrative = narrativeDescription(step.action, {
    action_type: step.action,
    url: step.args?.url || step.url_after || "",
    text: step.args?.text || "",
    fields: step.args?.fields || [],
    key: step.args?.key || "",
    element_description: step.description || step.args?.element_description || "",
    reasoning: step.description || "",
  });

  // Screenshot (cinematic view)
  if (step.screenshot) {
    els.replayScreenshot.src = `data:image/jpeg;base64,${step.screenshot}`;
    els.replayScreenshot.classList.remove("hidden");
    els.replayNoScreenshot.classList.add("hidden");
    // Overlay with step info
    els.replayOverlayStep.textContent = `Step ${idx + 1}`;
    els.replayOverlayAction.textContent = narrative.title;
    els.replayScreenshotOverlay.classList.remove("hidden");
    // Cinematic transition
    els.replayScreenshot.classList.remove("replay-screenshot-enter");
    void els.replayScreenshot.offsetHeight;
    els.replayScreenshot.classList.add("replay-screenshot-enter");
  } else {
    els.replayScreenshot.classList.add("hidden");
    els.replayScreenshotOverlay.classList.add("hidden");
    els.replayNoScreenshot.classList.remove("hidden");
  }

  // Step icon
  const iconMap = {
    navigate: `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polygon points="10 8 16 12 10 16 10 8" fill="currentColor"/></svg>`,
    click: `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 3l1 14 4-4 5 7 2-1-5-7h6z"/></svg>`,
    fill_form: `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 20h9M16.5 3.5a2.12 2.12 0 013 3L7 19l-4 1 1-4L16.5 3.5z"/></svg>`,
    type_text: `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="4" width="20" height="16" rx="2"/><path d="M6 8h.01M10 8h8"/></svg>`,
    press_key: `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="4" width="20" height="16" rx="2"/><path d="M7 15h10"/></svg>`,
    scroll: `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 5v14M5 12l7 7 7-7"/></svg>`,
  };

  els.replayStepIcon.innerHTML = iconMap[step.action] || iconMap.click;
  els.replayStepTitle.textContent = narrative.title;
  els.replayStepDetail.textContent = narrative.subtitle;

  // URL
  if (step.url_after) {
    try {
      const hostname = new URL(step.url_after).hostname.replace("www.", "");
      els.replayStepUrl.textContent = hostname;
      els.replayStepUrl.classList.remove("hidden");
    } catch { els.replayStepUrl.classList.add("hidden"); }
  } else {
    els.replayStepUrl.classList.add("hidden");
  }

  // Status
  els.replayStepStatus.innerHTML = step.success
    ? `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#34a853" stroke-width="2.5"><path d="M20 6L9 17l-5-5"/></svg>`
    : `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#ea4335" stroke-width="2.5"><path d="M18 6L6 18M6 6l12 12"/></svg>`;

  // Indicator
  els.replayStepIndicator.textContent = `${idx + 1} / ${replayData.steps.length}`;

  // Progress bar
  const pct = ((idx + 1) / replayData.steps.length) * 100;
  els.replayProgressFill.style.width = `${pct}%`;

  // Update dot highlights
  els.replayDots.querySelectorAll(".replay-dot").forEach((d, i) => {
    d.classList.toggle("active", i === idx);
    d.classList.toggle("done", i < idx);
  });

  // Duration display
  if (step.duration_ms) {
    els.replayDuration.textContent = `${step.duration_ms}ms`;
  }

  // Animate card entrance
  els.replayCard.classList.remove("replay-card-enter");
  void els.replayCard.offsetHeight;
  els.replayCard.classList.add("replay-card-enter");
}

function formatDuration(ms) {
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function updateStepCounter() {
  if (stepCount > 0) {
    els.stepCounter.textContent = `${stepCount} step${stepCount !== 1 ? "s" : ""}`;
  } else {
    els.stepCounter.textContent = "";
  }
}

function addTimelineEntry(icon, actionType, reasoning, riskLevel, confidence, agentType) {
  const iconSvgs = {
    start: `<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"/></svg>`,
    eye: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M2 12s4-8 10-8 10 8 10 8-4 8-10 8-10-8-10-8z"/></svg>`,
    brain: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2a7 7 0 0 1 7 7c0 2.38-1.19 4.47-3 5.74V17a2 2 0 0 1-2 2h-4a2 2 0 0 1-2-2v-2.26C6.19 13.47 5 11.38 5 9a7 7 0 0 1 7-7z"/><path d="M9 21h6M10 17h4"/></svg>`,
    action: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>`,
    agent: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg>`,
    approved: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M20 6L9 17l-5-5"/></svg>`,
    denied: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 6L6 18M6 6l12 12"/></svg>`,
    error: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>`,
    complete: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M20 6L9 17l-5-5"/></svg>`,
    steer: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/></svg>`,
  };

  // Determine the agent class for the timeline entry border
  let agentClass = "agent-default";
  if (agentType === "error") {
    agentClass = "agent-error";
  } else if (icon === "start") {
    agentClass = "agent-start";
  } else if (icon === "approved" || icon === "complete") {
    agentClass = "agent-success";
  } else if (icon === "steer") {
    agentClass = "agent-steering";
  } else if (AGENT_CONFIG[agentType]) {
    agentClass = `agent-${AGENT_CONFIG[agentType].class}`;
  }

  const entry = document.createElement("div");
  entry.className = `timeline-entry ${agentClass} active`;

  let metaHtml = "";
  if (riskLevel) {
    metaHtml += `<span class="risk-badge ${riskLevel}">${riskLevel}</span>`;
  }
  if (confidence != null) {
    metaHtml += `<span style="font-size:11px;color:var(--md-on-surface-variant)">${Math.round(confidence * 100)}%</span>`;
  }

  entry.innerHTML = `
    <div class="timeline-icon icon-${icon}">${iconSvgs[icon] || iconSvgs.agent}</div>
    <div class="timeline-content">
      <div style="display:flex;align-items:center;gap:6px">
        <span class="action-type">${actionType}</span>
        ${metaHtml ? `<div class="timeline-meta">${metaHtml}</div>` : ""}
      </div>
      ${reasoning ? `<div class="reasoning">${reasoning}</div>` : ""}
    </div>
    <span class="timeline-time">${formatTime()}</span>
  `;

  // Remove active shimmer from previous entries
  els.timeline.querySelectorAll(".timeline-entry.active").forEach((e) => {
    e.classList.remove("active");
  });

  els.timeline.appendChild(entry);

  // Scroll to bottom
  requestAnimationFrame(() => {
    els.contentArea.scrollTop = els.contentArea.scrollHeight;
  });
}

function showApproval(data) {
  els.approvalSection.classList.remove("hidden");
  els.approvalAction.textContent = `${data.action_type?.toUpperCase()}: ${data.reasoning || ""}`;
  els.approvalReason.textContent = data.reason || "";
  els.approvalRisk.textContent = data.risk_level || "medium";
  els.approvalRisk.className = `risk-badge ${data.risk_level || "medium"}`;
  els.approvalConfidence.textContent =
    data.confidence != null ? `${Math.round(data.confidence * 100)}% confidence` : "";
}

// ─── CONFIRMATION CARD (Manus-style) ─────────────────────────

const CONFIRM_ICONS = {
  calendar: `<svg width="24" height="24" viewBox="0 0 24 24" fill="none"><path d="M18 3h-2V2h-1v1H9V2H8v1H6C4.9 3 4 3.9 4 5v14c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2z" fill="#fff"/><path d="M18 3h-2V2h-1v1H9V2H8v1H6C4.9 3 4 3.9 4 5v14c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2z" fill="none" stroke="#4285f4" stroke-width="0.5"/><rect x="4" y="8" width="16" height="11" rx="0" fill="#4285f4"/><rect x="4" y="3" width="16" height="5" fill="#4285f4" rx="2"/><text x="12" y="16.5" text-anchor="middle" fill="#fff" font-size="8" font-weight="bold" font-family="Google Sans, sans-serif">${new Date().getDate()}</text><rect x="7.5" y="4.5" width="2" height="2" rx="0.5" fill="#fff" opacity="0.6"/><rect x="14.5" y="4.5" width="2" height="2" rx="0.5" fill="#fff" opacity="0.6"/></svg>`,
  email: `<svg width="24" height="24" viewBox="0 0 24 24" fill="none"><path d="M2 6c0-1.1.9-2 2-2h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6z" fill="#ea4335"/><path d="M2 6l10 7 10-7" stroke="#fff" stroke-width="1.5" stroke-linecap="round"/><path d="M2 18l7-5M22 18l-7-5" stroke="#fff" stroke-width="1" opacity="0.5"/></svg>`,
  sheet: `<svg width="24" height="24" viewBox="0 0 24 24" fill="none"><rect x="3" y="3" width="18" height="18" rx="2" fill="#34a853"/><path d="M3 9h18M3 15h18M9 3v18" stroke="#fff" stroke-width="1.2" opacity="0.6"/><rect x="10" y="10" width="7" height="4" rx="0.5" fill="#fff" opacity="0.9"/></svg>`,
  doc: `<svg width="24" height="24" viewBox="0 0 24 24" fill="none"><path d="M6 2h8l6 6v12c0 1.1-.9 2-2 2H6c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2z" fill="#4285f4"/><path d="M14 2v6h6" fill="#3367d6"/><path d="M8 13h8M8 16h6" stroke="#fff" stroke-width="1.2" stroke-linecap="round"/></svg>`,
  default: `<svg width="24" height="24" viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="10" fill="#1a73e8"/><path d="M12 8v4l3 3" stroke="#fff" stroke-width="1.5" stroke-linecap="round"/></svg>`,
};

const FIELD_ICONS = {
  title: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7"/></svg>`,
  date: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/></svg>`,
  time: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg>`,
  duration: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 6v6"/><path d="M16.24 7.76l-2.12 2.12"/></svg>`,
  location: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0118 0z"/><circle cx="12" cy="10" r="3"/></svg>`,
  person: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>`,
  link: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10 13a5 5 0 007.54.54l3-3a5 5 0 00-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 00-7.54-.54l-3 3a5 5 0 007.07 7.07l1.71-1.71"/></svg>`,
  to: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/><path d="M22 6l-10 7L2 6"/></svg>`,
  subject: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 7h16M4 12h16M4 17h10"/></svg>`,
  description: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><path d="M14 2v6h6M16 13H8M16 17H8M10 9H8"/></svg>`,
  default: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="1"/></svg>`,
};

function showConfirmation(data) {
  const actionType = data.action_type || "action";
  const icon = CONFIRM_ICONS[data.icon || actionType] || CONFIRM_ICONS.default;
  const title = data.title || "New Action";
  const buttonLabel = data.button_label || "Create";
  const fields = data.fields || [];

  // Reset drag position for fresh card
  resetConfirmPosition();

  els.confirmIcon.innerHTML = icon;
  els.confirmTitle.textContent = title;
  els.confirmCreateBtn.textContent = buttonLabel;

  // Render EDITABLE fields — user can click to modify before confirming
  let fieldsHtml = "";
  for (const field of fields) {
    const fieldIcon = FIELD_ICONS[field.icon || field.key] || FIELD_ICONS.default;
    const isPrimary = field.primary === true;
    const key = escapeHtml(field.key || "");
    const val = escapeHtml(field.value || "");

    // field_id is the actual backend key (e.g. "start_date", "start_time")
    const fieldId = escapeHtml(field.field_id || field.key || "");

    // Determine input type based on field key (icon type)
    let inputType = "text";
    let inputVal = val;
    if (key === "date") {
      inputType = "date";
      // Convert display date (e.g. "Mar 12, 2026") to ISO format for date picker
      try {
        const d = new Date(field.value);
        if (!isNaN(d.getTime())) {
          inputVal = d.toISOString().split("T")[0];
        }
      } catch (_) {}
    } else if (key === "time") {
      inputType = "time";
      // Convert "10:00am – 11:00am" or "10:00am" → "10:00" for time picker
      try {
        const firstTime = (field.value || "").split("–")[0].trim().replace(/\s/g, "").toLowerCase();
        const m = firstTime.match(/^(\d{1,2}):(\d{2})(am|pm)$/);
        if (m) {
          let h = parseInt(m[1]);
          if (m[3] === "pm" && h < 12) h += 12;
          if (m[3] === "am" && h === 12) h = 0;
          inputVal = `${h.toString().padStart(2,"0")}:${m[2]}`;
        }
      } catch (_) {}
    }

    if (isPrimary) {
      fieldsHtml += `
        <div class="confirm-field" data-key="${key}">
          <input type="text" class="confirm-field-edit primary" value="${val}" data-field-key="${fieldId}" />
        </div>`;
    } else {
      fieldsHtml += `
        <div class="confirm-field" data-key="${key}">
          <div class="confirm-field-icon">${fieldIcon}</div>
          <div class="confirm-field-value-wrap">
            <input type="${inputType}" class="confirm-field-edit" value="${inputVal}" data-field-key="${fieldId}" />
            ${field.label ? `<span class="label">${escapeHtml(field.label)}</span>` : ""}
          </div>
        </div>`;
    }
  }
  els.confirmFields.innerHTML = fieldsHtml;

  // Show
  els.confirmSection.classList.remove("hidden");
  els.approvalSection.classList.add("hidden");

  setStatus("Awaiting confirmation", "awaiting", "Review and confirm the action");

  // Announce confirmation via TTS — warm, concise
  const primaryField = fields.find(f => f.primary);
  const primaryName = primaryField ? primaryField.value : title;
  speakText(`Here's what I've got for you — ${primaryName}. Take a look and let me know!`);
}

// Confirm/Cancel button handlers + drag + pin
try {
  if (els.confirmCreateBtn) {
    els.confirmCreateBtn.addEventListener("click", () => {
      // Collect edited field values, converting date/time back to expected formats
      const edits = {};
      els.confirmFields.querySelectorAll(".confirm-field-edit").forEach((input) => {
        const key = input.dataset.fieldKey;
        if (!key) return;

        let val = input.value.trim();
        if (input.type === "date" && val) {
          // Convert "2026-03-12" → "Mar 12, 2026"
          try {
            const d = new Date(val + "T00:00:00");
            const months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
            val = `${months[d.getMonth()]} ${d.getDate()}, ${d.getFullYear()}`;
          } catch (_) {}
        } else if (input.type === "time" && val) {
          // Convert "10:00" → "10:00am", "14:30" → "2:30pm"
          try {
            const [hStr, mStr] = val.split(":");
            let h = parseInt(hStr);
            const ampm = h >= 12 ? "pm" : "am";
            if (h > 12) h -= 12;
            if (h === 0) h = 12;
            val = `${h}:${mStr}${ampm}`;
          } catch (_) {}
        }
        edits[key] = val;
      });

      els.confirmSection.classList.add("hidden");
      resetConfirmPosition();
      // Send approval WITH any user edits
      safeSend({ type: MSG.APPROVE, edits });
      setStatus("Executing", "executing", "Creating...");
      addTimelineEntry("action", "Confirmed", "User approved the action", null, null, "navigator");
    });
  }

  if (els.confirmCancelBtn) {
    els.confirmCancelBtn.addEventListener("click", () => {
      els.confirmSection.classList.add("hidden");
      resetConfirmPosition();
      safeSend({ type: MSG.DENY });
      setStatus("Cancelled", "error", "Action cancelled by user");
      addTimelineEntry("error", "Cancelled", "User cancelled the action", null, null, "error");
    });
  }

  // ── Pin button ──
  let confirmPinned = false;
  if (els.confirmPinBtn) {
    els.confirmPinBtn.addEventListener("click", () => {
      confirmPinned = !confirmPinned;
      els.confirmPinBtn.classList.toggle("pinned", confirmPinned);
      els.confirmCard.classList.toggle("pinned", confirmPinned);
    });
  }

  // ── Drag logic ──
  if (els.confirmDragHandle && els.confirmCard) {
    let isDragging = false;
    let dragStartX = 0, dragStartY = 0;
    let cardStartX = 0, cardStartY = 0;
    let hasMoved = false;

    els.confirmDragHandle.addEventListener("mousedown", (e) => {
      // Don't drag if clicking pin button
      if (e.target.closest(".confirm-pin-btn")) return;

      isDragging = true;
      hasMoved = false;
      dragStartX = e.clientX;
      dragStartY = e.clientY;

      const rect = els.confirmCard.getBoundingClientRect();
      const parentRect = els.confirmCard.parentElement.getBoundingClientRect();
      cardStartX = rect.left - parentRect.left;
      cardStartY = rect.top - parentRect.top;

      els.confirmCard.classList.add("dragging");
      e.preventDefault();
    });

    document.addEventListener("mousemove", (e) => {
      if (!isDragging) return;
      hasMoved = true;

      const dx = e.clientX - dragStartX;
      const dy = e.clientY - dragStartY;

      els.confirmCard.style.position = "relative";
      els.confirmCard.style.left = dx + "px";
      els.confirmCard.style.top = dy + "px";
    });

    document.addEventListener("mouseup", () => {
      if (!isDragging) return;
      isDragging = false;
      els.confirmCard.classList.remove("dragging");
    });
  }
} catch (e) {
  console.error("[G-Axis] Error setting up confirm card:", e);
}

function resetConfirmPosition() {
  if (els.confirmCard) {
    els.confirmCard.style.position = "";
    els.confirmCard.style.left = "";
    els.confirmCard.style.top = "";
  }
}

function showResearchInline(title, markdown, downloadUrl) {
  // Add research card to the chat/timeline area
  const card = document.createElement("div");
  card.className = "research-card";

  // Simple markdown → HTML conversion
  const htmlContent = markdownToHtml(markdown);

  // Preview (first 300 chars of plain text)
  const plainPreview = markdown.replace(/[#*|☐\[\]]/g, "").substring(0, 200).trim();

  card.innerHTML = `
    <div class="research-card-header">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
        <polyline points="14 2 14 8 20 8"/>
        <line x1="16" y1="13" x2="8" y2="13"/>
        <line x1="16" y1="17" x2="8" y2="17"/>
        <polyline points="10 9 9 9 8 9"/>
      </svg>
      <span class="research-card-title">${escapeHtml(title)}</span>
      <button class="research-expand-btn" title="Expand">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>
      </button>
    </div>
    <div class="research-card-preview">${escapeHtml(plainPreview)}...</div>
    <div class="research-card-content hidden">${htmlContent}</div>
    <div class="research-card-actions">
      ${downloadUrl ? `<a href="${escapeHtml(downloadUrl)}" class="research-download-btn" download>
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/>
          <polyline points="7 10 12 15 17 10"/>
          <line x1="12" y1="15" x2="12" y2="3"/>
        </svg>
        Download .docx
      </a>` : ""}
    </div>
  `;

  // Bind expand/collapse via addEventListener (CSP compliant)
  const expandBtn = card.querySelector(".research-expand-btn");
  const contentEl = card.querySelector(".research-card-content");
  const previewEl = card.querySelector(".research-card-preview");
  expandBtn.addEventListener("click", () => {
    const isCollapsed = contentEl.classList.contains("hidden");
    contentEl.classList.toggle("hidden");
    previewEl.classList.toggle("hidden");
    expandBtn.innerHTML = isCollapsed
      ? `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="18 15 12 9 6 15"/></svg>`
      : `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>`;
    expandBtn.title = isCollapsed ? "Collapse" : "Expand";
  });

  // Insert before the complete section or at end of timeline
  if (els.timeline) {
    els.timeline.appendChild(card);
  }
  requestAnimationFrame(() => {
    els.contentArea.scrollTop = els.contentArea.scrollHeight;
  });
}

function markdownToHtml(md) {
  let html = escapeHtml(md);
  // Headings
  html = html.replace(/^### (.+)$/gm, '<h4>$1</h4>');
  html = html.replace(/^## (.+)$/gm, '<h3>$1</h3>');
  html = html.replace(/^# (.+)$/gm, '<h2>$1</h2>');
  // Bold
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  // Bullets
  html = html.replace(/^[•\-\*] (.+)$/gm, '<li>$1</li>');
  html = html.replace(/(<li>.*<\/li>\n?)+/g, '<ul>$&</ul>');
  // Checklists
  html = html.replace(/^☐ (.+)$/gm, '<div class="checklist-item">☐ $1</div>');
  html = html.replace(/^\[ \] (.+)$/gm, '<div class="checklist-item">☐ $1</div>');
  // Tables (pipe-separated)
  html = html.replace(/((?:^.+\|.+$\n?){2,})/gm, (match) => {
    const rows = match.trim().split("\n");
    let table = '<table class="research-table">';
    rows.forEach((row, idx) => {
      const cells = row.split("|").map(c => c.trim()).filter(Boolean);
      const tag = idx === 0 ? "th" : "td";
      table += "<tr>" + cells.map(c => `<${tag}>${c}</${tag}>`).join("") + "</tr>";
    });
    return table + "</table>";
  });
  // Callouts
  html = html.replace(/^(TIP|WARNING|NOTE): (.+)$/gm, (_, type, text) => {
    const cls = type.toLowerCase();
    return `<div class="callout callout-${cls}"><strong>${type}:</strong> ${text}</div>`;
  });
  // Paragraphs (double newlines)
  html = html.replace(/\n\n/g, '</p><p>');
  html = '<p>' + html + '</p>';
  // Clean up empty paragraphs
  html = html.replace(/<p>\s*<\/p>/g, '');
  return html;
}

function showComplete(success, data) {
  els.statusSection.classList.add("hidden");
  els.stopBtn.classList.add("hidden");
  els.pauseBtn.classList.add("hidden");
  els.resumeBtn.classList.add("hidden");
  els.takeoverBtn.classList.add("hidden");
  els.givebackBtn.classList.add("hidden");
  els.completeSection.classList.remove("hidden");
  els.approvalSection.classList.add("hidden");
  els.confirmSection.classList.add("hidden");

  const duration = ((Date.now() - startTime) / 1000).toFixed(1);

  const checkmarkSvg = els.completeIcon.querySelector(".checkmark-svg");
  const errorSvg = els.completeIcon.querySelector(".error-svg");

  // Show cleanup button (hides workspace tabs if any were created)
  els.cleanupBtn.classList.remove("hidden");

  if (success) {
    checkmarkSvg.classList.remove("hidden");
    errorSvg.classList.add("hidden");
    // Re-trigger animation by cloning
    const circle = checkmarkSvg.querySelector(".checkmark-circle");
    const check = checkmarkSvg.querySelector(".checkmark-check");
    resetAnimation(circle);
    resetAnimation(check);

    const summary = data?.summary || "Task completed successfully";
    els.completeSummary.innerHTML = escapeHtml(summary) + "<br><br><small>Want me to do anything else?</small>";

    // Initialize replay player if data available
    if (data?.replay) {
      initReplayPlayer(data.replay);
    }
    setStatus("Complete", "success", "");
    addTimelineEntry("complete", "Done", summary, null, null, "success");
    speakText("All done! " + summary + " Want me to do anything else?");
  } else {
    checkmarkSvg.classList.add("hidden");
    errorSvg.classList.remove("hidden");
    // Re-trigger error animation
    errorSvg.querySelectorAll("circle, path").forEach(resetAnimation);

    const errorMsg = data?.error || "Task failed";
    els.completeSummary.textContent = errorMsg;
    setStatus("Failed", "failed", "");
    speakText("Hmm, that didn't quite work out. " + errorMsg + " Want me to try again?");
  }

  els.completeStats.textContent = `${stepCount} action${stepCount !== 1 ? "s" : ""} \u00B7 ${duration}s`;

  requestAnimationFrame(() => {
    els.contentArea.scrollTop = els.contentArea.scrollHeight;
  });
}

function resetAnimation(el) {
  if (!el) return;
  el.style.animation = "none";
  void el.offsetHeight;
  el.style.animation = "";
}

function resetUI() {
  appState = "idle";
  planExecuteInstruction = "";
  if (plannerTimeout) { clearTimeout(plannerTimeout); plannerTimeout = null; }
  currentAgent = null;
  els.welcomeSection.classList.remove("hidden");
  els.statusSection.classList.add("hidden");
  els.completeSection.classList.add("hidden");
  els.approvalSection.classList.add("hidden");
  els.chatSection.classList.add("hidden");
  els.screenshotContainer.classList.add("hidden");
  els.stopBtn.classList.add("hidden");
  els.pauseBtn.classList.add("hidden");
  els.resumeBtn.classList.add("hidden");
  els.takeoverBtn.classList.add("hidden");
  els.givebackBtn.classList.add("hidden");
  els.timelineSection.classList.add("hidden");
  els.taskInstructionCard.classList.add("hidden");
  els.loadingDots.classList.add("hidden");
  els.cleanupBtn.classList.add("hidden");
  // Reset replay player
  els.replayPlayer.classList.add("hidden");
  replayData = null; replayIndex = 0; replayPlaying = false;
  if (replayTimer) { clearInterval(replayTimer); replayTimer = null; }
  hideActivityTracker();
  hideOperatorWindow();
  els.taskInput.value = "";
  els.taskInput.placeholder = "Assign a task or ask anything...";
  els.taskInput.style.height = "auto";
  els.sendBtn.disabled = true;
  els.connectorsPanel.classList.add("hidden");
  els.connectorsBtn.classList.remove("active");
  els.timeline.innerHTML = "";
  els.chatMessages.innerHTML = "";
  els.stepCounter.textContent = "";
  updateAgentAvatar(null);
  // Stop any speech
  if ("speechSynthesis" in window) window.speechSynthesis.cancel();
}

function formatTime() {
  return new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

// ─── ACTIVITY TRACKER (Manus-style) ──────────────────────────

const ACTIVITY_ICONS = {
  done: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6L9 17l-5-5"/></svg>`,
  active: `<svg class="spinner-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><path d="M12 2a10 10 0 0 1 10 10"/></svg>`,
  pending: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" opacity="0.4"><circle cx="12" cy="12" r="4"/></svg>`,
  failed: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><path d="M18 6L6 18M6 6l12 12"/></svg>`,
};

function initActivityTracker() {
  if (els.activityBar) {
    els.activityBar.addEventListener("click", toggleActivityExpanded);
  }
  if (els.activityToggle) {
    els.activityToggle.addEventListener("click", (e) => {
      e.stopPropagation();
      toggleActivityExpanded();
    });
  }
}

function toggleActivityExpanded() {
  activityExpanded = !activityExpanded;
  els.activityTracker.classList.toggle("expanded", activityExpanded);
}

function showActivityTracker() {
  els.activityTracker.classList.remove("hidden");
}

function hideActivityTracker() {
  els.activityTracker.classList.add("hidden");
  els.activityTracker.classList.remove("expanded");
  activityExpanded = false;
  activitySteps = [];
}

function addActivityStep(label, status = "pending") {
  activitySteps.push({ label, status });
  renderActivitySteps();
  // If this step is active, update the compact bar
  if (status === "active") {
    setCurrentActivity(label);
  }
  return activitySteps.length - 1;
}

function updateActivityStep(index, status, newLabel) {
  if (index < 0 || index >= activitySteps.length) return;
  activitySteps[index].status = status;
  if (newLabel) activitySteps[index].label = newLabel;
  renderActivitySteps();
  // Update compact bar to show the current active step
  syncActivityBar();
}

function setCurrentActivity(label) {
  els.activityLabel.textContent = label;
  // Update icon to spinner (active)
  els.activityIcon.className = "activity-icon active";
  els.activityIcon.innerHTML = ACTIVITY_ICONS.active;
}

function markCurrentActivityDone() {
  els.activityIcon.className = "activity-icon done";
  els.activityIcon.innerHTML = ACTIVITY_ICONS.done;
}

function markCurrentActivityFailed() {
  els.activityIcon.className = "activity-icon failed";
  els.activityIcon.innerHTML = ACTIVITY_ICONS.failed;
}

function syncActivityBar() {
  const activeStep = activitySteps.find((s) => s.status === "active");
  const doneCount = activitySteps.filter((s) => s.status === "done").length;
  const total = activitySteps.length;

  els.activityCounter.textContent = `${doneCount} / ${total}`;

  if (activeStep) {
    els.activityLabel.textContent = activeStep.label;
    els.activityIcon.className = "activity-icon active";
    els.activityIcon.innerHTML = ACTIVITY_ICONS.active;
  } else {
    // All done or no active — check if all done
    const allDone = activitySteps.length > 0 && activitySteps.every((s) => s.status === "done");
    if (allDone) {
      els.activityLabel.textContent = "All steps completed";
      markCurrentActivityDone();
    }
  }
}

function renderActivitySteps() {
  const doneCount = activitySteps.filter((s) => s.status === "done").length;
  const total = activitySteps.length;
  els.activityCounter.textContent = `${doneCount} / ${total}`;

  els.activitySteps.innerHTML = activitySteps
    .map(
      (step, i) => `
    <div class="activity-step ${step.status}">
      <span class="activity-step-icon ${step.status}">${ACTIVITY_ICONS[step.status] || ACTIVITY_ICONS.pending}</span>
      <span class="activity-step-label">${escapeHtml(step.label)}</span>
    </div>`
    )
    .join("");
}

/** Find the index of the last step with the given status */
function findLastActiveStep() {
  for (let i = activitySteps.length - 1; i >= 0; i--) {
    if (activitySteps[i].status === "active") return i;
  }
  return -1;
}

// ─── TEXTAREA AUTO-RESIZE ─────────────────────────────────────

function autoResizeTextarea() {
  const el = els.taskInput;
  el.style.height = "auto";
  el.style.height = Math.min(el.scrollHeight, 160) + "px";
}

function toggleConnectorsPanel() {
  const isHidden = els.connectorsPanel.classList.contains("hidden");
  els.connectorsPanel.classList.toggle("hidden", !isHidden);
  els.connectorsBtn.classList.toggle("active", isHidden);
}

// ─── OPERATOR WINDOW ──────────────────────────────────────────

const OPERATOR_ICONS = {
  pending: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#9aa0a6" stroke-width="2"><circle cx="12" cy="12" r="9"/></svg>`,
  active: `<svg class="spinner-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#1a73e8" stroke-width="2.5" stroke-linecap="round"><path d="M12 2a10 10 0 0 1 10 10"/></svg>`,
  done: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#34a853" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6L9 17l-5-5"/></svg>`,
  failed: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#ea4335" stroke-width="2.5" stroke-linecap="round"><path d="M18 6L6 18M6 6l12 12"/></svg>`,
};

function showOperatorWindow(title) {
  operatorActions = [];
  els.operatorWindow.classList.remove("hidden");
  els.operatorTitle.textContent = title || "Action Plan";
  els.operatorStatusBadge.textContent = "Running";
  els.operatorStatusBadge.className = "operator-status-badge running";
  els.operatorActions.innerHTML = "";
  els.operatorMessage.classList.add("hidden");
}

function hideOperatorWindow() {
  els.operatorWindow.classList.add("hidden");
  operatorActions = [];
}

function addOperatorAction(label, value, status = "pending") {
  operatorActions.push({ label, value, status });
  renderOperatorActions();
  return operatorActions.length - 1;
}

function updateOperatorAction(index, status, newValue) {
  if (index < 0 || index >= operatorActions.length) return;
  operatorActions[index].status = status;
  if (newValue !== undefined) operatorActions[index].value = newValue;
  renderOperatorActions();
}

function setOperatorActionActive(index) {
  // Mark all prior as done, this one as active
  for (let i = 0; i < operatorActions.length; i++) {
    if (i < index && operatorActions[i].status !== "failed") {
      operatorActions[i].status = "done";
    } else if (i === index) {
      operatorActions[i].status = "active";
    }
  }
  renderOperatorActions();
}

function completeOperatorWindow(message, success = true) {
  if (operatorActions.length === 0) return;

  // Update Status row value
  const statusIdx = operatorActions.findIndex((a) => a.label === "Status");
  if (statusIdx >= 0) {
    operatorActions[statusIdx].value = success ? "Completed" : "Failed";
  }

  // Mark all remaining as done (or failed)
  operatorActions.forEach((a) => {
    if (a.status === "active" || a.status === "pending") {
      a.status = success ? "done" : "failed";
    }
  });
  renderOperatorActions();

  els.operatorStatusBadge.textContent = success ? "Completed" : "Failed";
  els.operatorStatusBadge.className = `operator-status-badge ${success ? "completed" : "failed"}`;

  if (message) {
    els.operatorMessageText.textContent = message;
    els.operatorMessage.classList.remove("hidden");
  }
}

function renderOperatorActions() {
  els.operatorActions.innerHTML = operatorActions
    .map((a) => `
      <div class="operator-action-row ${a.status}">
        <span class="operator-action-icon">${OPERATOR_ICONS[a.status] || OPERATOR_ICONS.pending}</span>
        <span class="operator-action-label">${escapeHtml(a.label)}</span>
        <span class="operator-action-value">${escapeHtml(a.value || "")}</span>
      </div>
    `)
    .join("");
}

/**
 * Infer high-level operator actions from the task instruction.
 * Returns array of { label, value } for the operator window.
 */
function inferOperatorPlan(instruction) {
  const lower = instruction.toLowerCase();
  const plan = [];

  // Calendar / Meeting tasks
  if (lower.match(/\b(meeting|event|calendar|schedule|standup|scrum|appointment)\b/)) {
    plan.push({ label: "Action", value: "Open Calendar" });
    plan.push({ label: "Action", value: "Create Event" });

    // Extract title
    const titleMatch = instruction.match(/(?:for|called|named|titled?)\s+["']?([^"'\n,.]+)/i)
      || instruction.match(/(?:schedule|create|block|set up)\s+(?:a\s+)?(.+?)(?:\s+(?:at|on|for|tomorrow|today|next))/i);
    if (titleMatch) {
      plan.push({ label: "Title", value: titleMatch[1].trim() });
    }

    // Extract time
    const timeMatch = instruction.match(/(?:at|@)\s*(\d{1,2}(?::\d{2})?\s*(?:AM|PM|am|pm)?)/i);
    if (timeMatch) {
      plan.push({ label: "Time", value: timeMatch[1].trim() });
    }

    // Extract date context
    if (lower.includes("tomorrow")) {
      plan.push({ label: "Date", value: "Tomorrow" });
    } else if (lower.includes("today")) {
      plan.push({ label: "Date", value: "Today" });
    }

    plan.push({ label: "Status", value: "Pending" });
    return plan;
  }

  // Email tasks
  if (lower.match(/\b(email|mail|send|compose|write to)\b/)) {
    plan.push({ label: "Action", value: "Open Gmail" });
    plan.push({ label: "Action", value: "Compose Email" });

    const toMatch = instruction.match(/(?:to|email)\s+([A-Za-z\s]+?)(?:\s+(?:about|saying|with|regarding))/i);
    if (toMatch) plan.push({ label: "To", value: toMatch[1].trim() });

    const aboutMatch = instruction.match(/(?:about|regarding|saying)\s+["']?(.+?)["']?$/i);
    if (aboutMatch) plan.push({ label: "Subject", value: aboutMatch[1].trim() });

    plan.push({ label: "Status", value: "Pending" });
    return plan;
  }

  // Document tasks
  if (lower.match(/\b(document|doc|write|draft|create a doc|google doc)\b/)) {
    plan.push({ label: "Action", value: "Open Google Docs" });
    plan.push({ label: "Action", value: "Create Document" });
    plan.push({ label: "Action", value: "Write Content" });
    plan.push({ label: "Status", value: "Pending" });
    return plan;
  }

  // Research tasks
  if (lower.match(/\b(research|compare|find|search|look up|itinerary|guide)\b/)) {
    plan.push({ label: "Action", value: "Research & Gather Data" });
    plan.push({ label: "Action", value: "Analyze Sources" });
    plan.push({ label: "Action", value: "Create Report" });
    plan.push({ label: "Status", value: "Pending" });
    return plan;
  }

  // Spreadsheet tasks
  if (lower.match(/\b(spreadsheet|sheet|table|data|csv)\b/)) {
    plan.push({ label: "Action", value: "Open Google Sheets" });
    plan.push({ label: "Action", value: "Create Spreadsheet" });
    plan.push({ label: "Action", value: "Populate Data" });
    plan.push({ label: "Status", value: "Pending" });
    return plan;
  }

  // Navigation / search tasks
  if (lower.match(/\b(go to|navigate|open|visit|search)\b/)) {
    plan.push({ label: "Action", value: "Navigate to Page" });
    plan.push({ label: "Action", value: "Execute Task" });
    plan.push({ label: "Status", value: "Pending" });
    return plan;
  }

  // Generic fallback
  plan.push({ label: "Action", value: "Execute Task" });
  plan.push({ label: "Status", value: "Pending" });
  return plan;
}

/**
 * Advance operator plan based on the current action.
 * Matches action types to operator plan rows and progresses them.
 */
function advanceOperatorPlan(actionType, reasoning) {
  if (operatorActions.length === 0) return;

  const type = (actionType || "").toLowerCase();
  const desc = (reasoning || "").toLowerCase();

  // Find the first pending "Action" row and mark it active
  // Also try to match by content for smarter progression
  let matched = false;
  for (let i = 0; i < operatorActions.length; i++) {
    const a = operatorActions[i];
    if (a.status !== "pending") continue;

    // Smart matching: if the action/reasoning matches the plan value
    const val = a.value.toLowerCase();
    if (
      (type === "navigate" && val.includes("open")) ||
      (type === "navigate" && val.includes("navigate")) ||
      (type === "click" && (val.includes("create") || val.includes("compose"))) ||
      (type === "type_text" && (val.includes("write") || val.includes("content") || val.includes("populate"))) ||
      (desc.includes("calendar") && val.includes("calendar")) ||
      (desc.includes("gmail") && val.includes("gmail")) ||
      (desc.includes("doc") && val.includes("doc")) ||
      (desc.includes("sheet") && val.includes("sheet")) ||
      (a.label === "Action" && a.status === "pending")
    ) {
      setOperatorActionActive(i);
      matched = true;
      break;
    }
  }

  // Fallback: just advance to next pending
  if (!matched) {
    const nextPending = operatorActions.findIndex((a) => a.status === "pending");
    if (nextPending >= 0) setOperatorActionActive(nextPending);
  }

  // Update the Status row if it exists
  const statusIdx = operatorActions.findIndex((a) => a.label === "Status");
  if (statusIdx >= 0) {
    operatorActions[statusIdx].value = "In Progress";
    operatorActions[statusIdx].status = "active";
    renderOperatorActions();
  }
}

// ─── VOICE INPUT / GEMINI LIVE AUDIO ─────────────────────────

let voiceTranscriptHistory = []; // Save all transcripts for export

function toggleVoice() {
  if (isRecording) {
    stopMic();
  } else if (liveMode) {
    startMic();
  } else {
    startLiveMode();
  }
}

// ── Gemini Live Mode ──
// Bidirectional session with Gemini: supports voice (mic streaming) AND text.
// Gemini responds with audio and can call browser tools mid-conversation.

/** Start the Gemini Live session (backend) + audio playback. No mic required. */
async function startLiveSession() {
  if (liveMode) return; // Already active

  // Playback context at 24kHz (Gemini output rate)
  livePlayCtx = new AudioContext({ sampleRate: 24000 });
  // Browsers suspend AudioContext until user gesture — resume it now
  if (livePlayCtx.state === "suspended") {
    await livePlayCtx.resume();
    console.log("[G-Axis] AudioContext resumed for playback");
  }
  livePlayQueue = [];
  livePlayingSource = null;
  livePlayNextTime = 0;

  // Tell backend to start Gemini Live session
  safeSend({ type: MSG.LIVE_START, persona: els.personaSelect?.value || "friend" });

  liveMode = true;
  window._voiceSessionStart = Date.now();
  window._currentPersona = els.personaSelect?.value || "friend";
  voiceTranscriptHistory = [];

  // Show voice UI
  els.voiceSection.classList.remove("hidden");
  els.welcomeSection.classList.add("hidden");
  els.chatSection.classList.add("hidden");
  els.completeSection.classList.add("hidden");
  els.statusSection.classList.add("hidden");
  els.voiceOrb.className = "voice-orb connecting";
  els.voiceStatusText.textContent = "Connecting...";
  playVoiceSound("wake");
  els.voiceTranscript.innerHTML = "";
  els.voiceTranscriptLive.textContent = "";

  let streamPaused = false;

  // Bind buttons
  els.voiceEndBtn.onclick = () => endVoiceSession();

  // ── Persona switch — live reconnect with new persona ──
  els.personaSelect.onchange = async () => {
    if (!liveMode) return;
    const newPersona = els.personaSelect.value;
    const personaLabel = els.personaSelect.selectedOptions[0]?.text || newPersona;
    els.voiceOrb.className = "voice-orb connecting";
    els.voiceStatusText.textContent = `Switching to ${personaLabel}...`;

    // Save current session before switching
    const durationSecs = Math.round((Date.now() - (window._voiceSessionStart || Date.now())) / 1000);
    if (voiceTranscriptHistory.length >= 4) {
      const prevPersona = window._currentPersona || "friend";
      let markdown = "";
      for (const entry of voiceTranscriptHistory) {
        const label = entry.role === "user" ? "**You**" : "**G-Axis**";
        markdown += `${label}: ${entry.text}\n\n`;
      }
      // Fire and forget — don't block switch
      fetch("http://localhost:8000/api/analyze-session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: `session_${Date.now()}`,
          persona: prevPersona,
          started_at: new Date(window._voiceSessionStart || Date.now()).toISOString(),
          ended_at: new Date().toISOString(),
          duration_secs: durationSecs,
          transcript: markdown,
        }),
      }).catch(() => {});
    }

    // Clear transcript for new persona session
    voiceTranscriptHistory = [];
    els.voiceTranscript.innerHTML = "";
    els.voiceTranscriptLive.textContent = "";
    _lastBubbleRole = null;
    _lastBubbleEl = null;
    window._voiceSessionStart = Date.now();
    window._currentPersona = newPersona;

    // Stop current, start new
    safeSend({ type: MSG.LIVE_STOP });
    setTimeout(() => {
      safeSend({ type: MSG.LIVE_START, persona: newPersona });
    }, 500);
  };

  // ── Stream play/pause — pauses/resumes the Gemini Live session ──
  els.voiceStreamBtn.onclick = () => {
    if (!streamPaused) {
      // Pause stream — stop Gemini session AND mic
      safeSend({ type: MSG.LIVE_STOP });
      safeSend({ type: "gaxis:restart_mic_stop" });
      streamPaused = true;
      els.streamPauseIcon.style.display = "none";
      els.streamPlayIcon.style.display = "inline";
      els.voiceStreamBtn.className = "voice-control-btn stream-off";
      els.voiceOrb.className = "voice-orb idle";
      els.voiceStatusText.textContent = "Stream paused";
      els.voiceLiveBadge.className = "voice-live-badge paused";
    } else {
      // Resume stream — restart Gemini session (keeps conversation transcript)
      safeSend({ type: MSG.LIVE_START, persona: els.personaSelect?.value || "friend" });
      streamPaused = false;
      els.streamPauseIcon.style.display = "inline";
      els.streamPlayIcon.style.display = "none";
      els.voiceStreamBtn.className = "voice-control-btn stream-on";
      els.voiceOrb.className = "voice-orb listening";
      els.voiceStatusText.textContent = "Listening...";
      els.voiceLiveBadge.className = "voice-live-badge";
    }
  };

  // ── Mic mute/unmute — independent of stream ──
  els.voiceMicBtn.onclick = () => {
    if (streamPaused) return; // Can't toggle mic when stream is paused
    if (isRecording) {
      safeSend({ type: "gaxis:restart_mic_stop" });
      isRecording = false;
      els.micIconOn.style.display = "none";
      els.micIconOff.style.display = "inline";
      els.voiceMicBtn.className = "voice-control-btn mic-off";
      els.voiceOrb.className = "voice-orb idle";
      els.voiceStatusText.textContent = "Mic muted — stream live";
    } else {
      safeSend({ type: "gaxis:restart_mic" });
      isRecording = true;
      els.micIconOn.style.display = "inline";
      els.micIconOff.style.display = "none";
      els.voiceMicBtn.className = "voice-control-btn mic-on";
      els.voiceOrb.className = "voice-orb listening";
      els.voiceStatusText.textContent = "Listening...";
    }
  };

  // ── Refresh — new conversation with fresh context ──
  els.voiceNewBtn.onclick = () => {
    safeSend({ type: MSG.LIVE_STOP });
    voiceTranscriptHistory = [];
    els.voiceTranscript.innerHTML = "";
    els.voiceTranscriptLive.textContent = "";
    els.voiceOrb.className = "voice-orb connecting";
    els.voiceStatusText.textContent = "Starting new conversation...";
    streamPaused = false;
    els.streamPauseIcon.style.display = "inline";
    els.streamPlayIcon.style.display = "none";
    els.voiceStreamBtn.className = "voice-control-btn stream-on";
    els.voiceLiveBadge.className = "voice-live-badge";
    // Fresh Gemini session after brief delay
    setTimeout(() => {
      safeSend({ type: MSG.LIVE_START, persona: els.personaSelect?.value || "friend" });
      liveMode = true;
      isRecording = true;
      els.micIconOn.style.display = "inline";
      els.micIconOff.style.display = "none";
      els.voiceMicBtn.className = "voice-control-btn mic-on";
      els.voiceOrb.className = "voice-orb listening";
      els.voiceStatusText.textContent = "Listening...";
    }, 500);
  };
}

/** Start mic streaming into the live session.
 *  Mic capture is handled by the offscreen document via the service worker.
 *  The service worker creates the offscreen doc and starts mic on LIVE_START.
 *  If resuming (liveMode already true), tell service worker to restart mic.
 */
async function startMic() {
  if (!liveMode) {
    await startLiveSession();
    // LIVE_START sent inside startLiveSession → service worker creates offscreen → starts mic
  } else {
    // Resuming from pause — ask service worker to restart offscreen mic
    safeSend({ type: "gaxis:restart_mic" });
  }

  isRecording = true;
  els.voiceBtn.classList.add("recording", "live-mode");
  els.voiceBtn.title = "Stop microphone";
  els.voiceOrb.className = "voice-orb listening";
  els.voiceStatusText.textContent = "Listening...";
  playVoiceSound("listening");
}

/** Stop mic but keep live session active (can still type). */
function stopMic() {
  isRecording = false;
  // Stop direct mic if active
  if (liveMicStream) {
    liveMicStream.getTracks().forEach((t) => t.stop());
    liveMicStream = null;
  }
  if (liveAudioCtx) {
    liveAudioCtx.close().catch(() => {});
    liveAudioCtx = null;
  }
  // Also stop offscreen mic in case that path was used
  chrome.runtime.sendMessage({ type: "offscreen:stop_mic" }).catch(() => {});
  els.voiceBtn.classList.remove("recording", "live-mode");
  els.voiceBtn.title = "Start microphone";
  if (liveMode) {
    els.voiceOrb.className = "voice-orb idle";
    els.voiceStatusText.textContent = "Mic paused — tap mic to resume";
  }
}

/** Backward-compatible wrapper — starts live session + mic. */
async function startLiveMode() {
  await startMic();
}

// ── Voice Sound Effects (Web Audio API — no external files) ──

function playVoiceSound(type) {
  try {
    const ctx = new AudioContext();
    const gain = ctx.createGain();
    gain.connect(ctx.destination);

    switch (type) {
      case "wake": {
        // Soft ascending chime
        const o = ctx.createOscillator();
        o.type = "sine";
        o.frequency.setValueAtTime(523, ctx.currentTime); // C5
        o.frequency.linearRampToValueAtTime(784, ctx.currentTime + 0.15); // G5
        gain.gain.setValueAtTime(0.15, ctx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.4);
        o.connect(gain);
        o.start();
        o.stop(ctx.currentTime + 0.4);
        break;
      }
      case "listening": {
        // Light rising tone
        const o = ctx.createOscillator();
        o.type = "sine";
        o.frequency.setValueAtTime(440, ctx.currentTime); // A4
        o.frequency.linearRampToValueAtTime(660, ctx.currentTime + 0.2); // E5
        gain.gain.setValueAtTime(0.12, ctx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.35);
        o.connect(gain);
        o.start();
        o.stop(ctx.currentTime + 0.35);
        break;
      }
      case "thinking": {
        // Subtle ambient pulse
        const o = ctx.createOscillator();
        o.type = "triangle";
        o.frequency.setValueAtTime(330, ctx.currentTime);
        o.frequency.linearRampToValueAtTime(350, ctx.currentTime + 0.5);
        gain.gain.setValueAtTime(0.06, ctx.currentTime);
        gain.gain.linearRampToValueAtTime(0.08, ctx.currentTime + 0.25);
        gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.6);
        o.connect(gain);
        o.start();
        o.stop(ctx.currentTime + 0.6);
        break;
      }
      case "response": {
        // Pleasant ding
        const o = ctx.createOscillator();
        o.type = "sine";
        o.frequency.setValueAtTime(880, ctx.currentTime); // A5
        gain.gain.setValueAtTime(0.12, ctx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.5);
        o.connect(gain);
        o.start();
        o.stop(ctx.currentTime + 0.5);
        break;
      }
      case "success": {
        // Uplifting two-note chime
        const o1 = ctx.createOscillator();
        const o2 = ctx.createOscillator();
        o1.type = "sine";
        o2.type = "sine";
        o1.frequency.value = 523; // C5
        o2.frequency.value = 784; // G5
        const g1 = ctx.createGain();
        const g2 = ctx.createGain();
        g1.gain.setValueAtTime(0.12, ctx.currentTime);
        g1.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.4);
        g2.gain.setValueAtTime(0, ctx.currentTime);
        g2.gain.setValueAtTime(0.12, ctx.currentTime + 0.15);
        g2.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.6);
        o1.connect(g1).connect(ctx.destination);
        o2.connect(g2).connect(ctx.destination);
        o1.start();
        o2.start(ctx.currentTime + 0.15);
        o1.stop(ctx.currentTime + 0.4);
        o2.stop(ctx.currentTime + 0.6);
        break;
      }
      case "error": {
        // Soft descending tone
        const o = ctx.createOscillator();
        o.type = "sine";
        o.frequency.setValueAtTime(440, ctx.currentTime); // A4
        o.frequency.linearRampToValueAtTime(280, ctx.currentTime + 0.3);
        gain.gain.setValueAtTime(0.1, ctx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.4);
        o.connect(gain);
        o.start();
        o.stop(ctx.currentTime + 0.4);
        break;
      }
      case "end": {
        // Gentle descending chime
        const o = ctx.createOscillator();
        o.type = "sine";
        o.frequency.setValueAtTime(659, ctx.currentTime); // E5
        o.frequency.linearRampToValueAtTime(440, ctx.currentTime + 0.3); // A4
        gain.gain.setValueAtTime(0.1, ctx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.5);
        o.connect(gain);
        o.start();
        o.stop(ctx.currentTime + 0.5);
        break;
      }
    }

    // Auto-close context
    setTimeout(() => ctx.close().catch(() => {}), 1000);
  } catch (_) {}
}

let _lastBubbleRole = null;
let _lastBubbleEl = null;
let _transcriptBuffer = { role: null, text: "" };
let _transcriptFlushTimer = null;

function addVoiceBubble(role, text) {
  // Buffer chunks and flush after 400ms of no new chunks
  if (_transcriptBuffer.role === role) {
    _transcriptBuffer.text += text;
  } else {
    flushTranscriptBuffer();
    _transcriptBuffer.role = role;
    _transcriptBuffer.text = text;
  }

  if (_transcriptFlushTimer) clearTimeout(_transcriptFlushTimer);
  _transcriptFlushTimer = setTimeout(flushTranscriptBuffer, 400);

  // Update live preview immediately
  if (els.voiceTranscriptLive) {
    els.voiceTranscriptLive.textContent = _transcriptBuffer.text;
  }
}

function flushTranscriptBuffer() {
  if (_transcriptFlushTimer) { clearTimeout(_transcriptFlushTimer); _transcriptFlushTimer = null; }
  if (!_transcriptBuffer.text || !_transcriptBuffer.role) return;

  const role = _transcriptBuffer.role;
  const text = _transcriptBuffer.text;
  _transcriptBuffer = { role: null, text: "" };

  // Clear live preview
  if (els.voiceTranscriptLive) els.voiceTranscriptLive.textContent = "";

  // Merge into last bubble if same role
  if (role === _lastBubbleRole && _lastBubbleEl && _lastBubbleEl.parentNode) {
    const contentSpan = _lastBubbleEl.querySelector(".bubble-content");
    if (contentSpan) {
      contentSpan.textContent += text;
    }
    const lastEntry = voiceTranscriptHistory[voiceTranscriptHistory.length - 1];
    if (lastEntry && lastEntry.role === role) {
      lastEntry.text += text;
    }
  } else {
    const bubble = document.createElement("div");
    bubble.className = `voice-bubble ${role}`;
    const label = role === "user" ? "You" : "G-Axis";
    bubble.innerHTML = `<div class="bubble-label">${label}</div><span class="bubble-content">${escapeHtml(text)}</span>`;
    els.voiceTranscript.appendChild(bubble);
    _lastBubbleRole = role;
    _lastBubbleEl = bubble;

    voiceTranscriptHistory.push({ role, text, timestamp: new Date().toISOString() });
  }
  els.voiceTranscript.scrollTop = els.voiceTranscript.scrollHeight;
}

async function endVoiceSession() {
  const sessionStartTime = window._voiceSessionStart || Date.now();
  const durationSecs = Math.round((Date.now() - sessionStartTime) / 1000);
  const persona = els.personaSelect?.value || "friend";

  stopLiveMode();

  // Hide voice UI, show welcome
  els.voiceSection.classList.add("hidden");
  els.welcomeSection.classList.remove("hidden");

  // Analyze if conversation was substantive
  const MIN_TURNS = 4;
  const MIN_TOTAL_CHARS = 100;

  if (voiceTranscriptHistory.length >= MIN_TURNS) {
    const totalChars = voiceTranscriptHistory.reduce((sum, e) => sum + (e.text?.length || 0), 0);
    if (totalChars >= MIN_TOTAL_CHARS) {
      try {
        const title = `G-Axis Conversation — ${new Date().toLocaleDateString()}`;
        let markdown = `# ${title}\n\n`;
        for (const entry of voiceTranscriptHistory) {
          const label = entry.role === "user" ? "**You**" : "**G-Axis**";
          markdown += `${label}: ${entry.text}\n\n`;
        }

        // Analyze session — skills, XP, insights
        const analyzeResp = await fetch(`http://localhost:8000/api/analyze-session`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            session_id: `session_${Date.now()}`,
            persona,
            started_at: new Date(sessionStartTime).toISOString(),
            ended_at: new Date().toISOString(),
            duration_secs: durationSecs,
            transcript: markdown,
          }),
        }).catch(() => null);

        if (analyzeResp?.ok) {
          const analysis = await analyzeResp.json();
          if (!analysis.skipped) {
            // Show brief session summary
            console.log("[G-Axis] Session analyzed:", analysis);
            // TODO: Show XP toast / session summary card
          }
        }

        // Save transcript as .docx
        const resp = await fetch(`http://localhost:8000/api/save-transcript`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ title, content: markdown }),
        }).catch(() => null);

        if (resp?.ok) {
          const result = await resp.json();
          if (result.download_url) {
            safeSend({
              type: "research_complete_internal",
              data: { title, download_url: result.download_url, filename: result.filename },
            });
          }
        }
      } catch (err) {
        console.error("[G-Axis] Transcript save failed:", err);
      }
    }
  }
}

function stopLiveMode() {
  // 1. Reset playback state
  livePlayQueue = [];
  livePlayNextTime = 0;

  // 2. Stop current playback with state guard
  if (livePlayingSource) {
    try {
      if (livePlayCtx && livePlayCtx.state !== "closed") {
        livePlayingSource.stop();
      }
    } catch (_) {}
    livePlayingSource = null;
  }

  // 3. Close playback context
  if (livePlayCtx && livePlayCtx.state !== "closed") {
    livePlayCtx.close().catch(() => {});
  }
  livePlayCtx = null;

  // 4. Stop mic
  stopMic();

  // 5. Flush transcript buffer
  if (typeof flushTranscriptBuffer === "function") flushTranscriptBuffer();

  liveMode = false;

  // Tell backend to close Gemini Live session
  safeSend({ type: MSG.LIVE_STOP });

  els.voiceBtn.classList.remove("recording", "live-mode");
  els.voiceBtn.title = "Voice input";
  els.voiceOrb.className = "voice-orb idle";
  els.voiceStatusText.textContent = "Session ended";
  playVoiceSound("end");
}

// ── Gapless audio playback using scheduled start times ──
// Instead of onended callbacks (which have ~5-20ms gaps), we schedule
// each chunk to start exactly when the previous one ends.
let livePlayNextTime = 0; // AudioContext time for next chunk

function playLiveAudioChunk(base64Pcm) {
  if (!livePlayCtx || livePlayCtx.state === "closed") return;
  if (livePlayCtx.state === "suspended") {
    livePlayCtx.resume().catch(() => {});
  }

  // Decode base64 → Int16 PCM → Float32
  const binaryStr = atob(base64Pcm);
  const bytes = new Uint8Array(binaryStr.length);
  for (let i = 0; i < binaryStr.length; i++) bytes[i] = binaryStr.charCodeAt(i);
  const int16 = new Int16Array(bytes.buffer);
  const float32 = new Float32Array(int16.length);
  for (let i = 0; i < int16.length; i++) {
    float32[i] = int16[i] / (int16[i] < 0 ? 0x8000 : 0x7FFF);
  }

  try {
    const buffer = livePlayCtx.createBuffer(1, float32.length, 24000);
    buffer.getChannelData(0).set(float32);

    const source = livePlayCtx.createBufferSource();
    source.buffer = buffer;
    source.connect(livePlayCtx.destination);

    // Schedule gapless: start exactly when previous chunk ends
    const now = livePlayCtx.currentTime;
    const startTime = Math.max(now, livePlayNextTime);
    source.start(startTime);
    livePlayNextTime = startTime + buffer.duration;
    livePlayingSource = source;
  } catch (e) {
    console.error("[G-Axis] Playback error:", e.message);
    livePlayingSource = null;
    livePlayNextTime = 0;
  }
}

// Chat message helper for transcripts
async function openDashboard() {
  els.welcomeSection.classList.add("hidden");
  els.dashboardSection.classList.remove("hidden");

  try {
    const resp = await fetch(`http://localhost:8000/api/dashboard`);
    if (!resp.ok) return;
    const data = await resp.json();
    const stats = data.stats || {};
    const recent = data.recent_sessions || [];

    const emptyEl = document.getElementById("dash-empty");
    const contentEl = document.getElementById("dash-content");

    // Show empty state if no sessions
    if ((stats.total_sessions || 0) === 0) {
      if (emptyEl) emptyEl.classList.remove("hidden");
      if (contentEl) contentEl.classList.add("hidden");
      return;
    }
    if (emptyEl) emptyEl.classList.add("hidden");
    if (contentEl) contentEl.classList.remove("hidden");

    const $v = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };

    // Level card
    const level = stats.level || 1;
    const xp = stats.xp || 0;
    const xpInLevel = xp % 500;
    const xpForNext = 500;
    $v("dash-level", level);
    $v("dash-level-num", level);
    $v("dash-xp", xp);
    $v("dash-xp-next", level * 500);
    const xpFill = document.getElementById("dash-xp-fill");
    if (xpFill) xpFill.style.width = `${(xpInLevel / xpForNext) * 100}%`;

    // Stats
    $v("dash-streak", stats.current_streak || 0);
    $v("dash-sessions", stats.total_sessions || 0);
    $v("dash-minutes", stats.total_duration_mins || 0);

    // Skills
    const skills = stats.skill_scores || {};
    const skillValues = Object.values(skills);
    const avgSkill = skillValues.length ? Math.round(skillValues.reduce((a, b) => a + b, 0) / skillValues.length) : 0;
    $v("dash-avg-skill", avgSkill ? `${avgSkill}/100` : "--");

    for (const [key, val] of Object.entries(skills)) {
      const fill = document.getElementById(`skill-${key}`);
      const valEl = document.getElementById(`skill-${key}-val`);
      if (fill) fill.style.width = `${val}%`;
      if (valEl) valEl.textContent = val;
    }

    // Weekly activity (GitHub-style dots)
    const weekEl = document.getElementById("dash-activity-week");
    if (weekEl) {
      const activity = stats.daily_activity || [];
      const activityMap = {};
      for (const d of activity) activityMap[d.date] = d.minutes;

      const days = ["M", "T", "W", "T", "F", "S", "S"];
      const today = new Date();
      let html = "";
      for (let i = 6; i >= 0; i--) {
        const d = new Date(today);
        d.setDate(d.getDate() - i);
        const dateStr = d.toISOString().split("T")[0];
        const mins = activityMap[dateStr] || 0;
        const level = mins === 0 ? "empty" : mins < 5 ? "low" : mins < 15 ? "med" : "high";
        const isToday = i === 0;
        html += `<div class="activity-day ${isToday ? "today" : ""}">
          <div class="activity-dot ${level}" title="${dateStr}: ${mins}min"></div>
          <span class="activity-day-label">${days[d.getDay() === 0 ? 6 : d.getDay() - 1]}</span>
        </div>`;
      }
      weekEl.innerHTML = html;
    }

    // Recent sessions
    const listEl = document.getElementById("dash-recent-list");
    if (listEl) {
      if (recent.length === 0) {
        listEl.innerHTML = '<div class="dash-recent-item"><div class="dash-recent-summary">Start a conversation to see it here</div></div>';
      } else {
        listEl.innerHTML = recent.slice().reverse().map(s => {
          const mins = Math.round((s.duration_secs || 0) / 60);
          const skillTags = Object.entries(s.skills || {})
            .filter(([, v]) => v > 60)
            .map(([k]) => `<span class="dash-recent-skill">${k}</span>`)
            .join("");
          return `<div class="dash-recent-item">
            <div class="dash-recent-top">
              <span class="dash-recent-persona">${s.persona || "friend"}</span>
              <span class="dash-recent-meta">${mins}min</span>
            </div>
            <div class="dash-recent-summary">${s.summary || s.topics?.join(", ") || "Conversation"}</div>
            ${skillTags ? `<div class="dash-recent-skills">${skillTags}</div>` : ""}
          </div>`;
        }).join("");
      }
    }
  } catch (e) {
    console.error("[G-Axis] Dashboard load failed:", e);
  }
}

function addChatMessage(role, text) {
  els.chatSection.classList.remove("hidden");
  const div = document.createElement("div");
  div.className = `chat-message chat-${role}`;
  div.textContent = text;
  els.chatMessages.appendChild(div);
  els.chatMessages.scrollTop = els.chatMessages.scrollHeight;
}

// ─── START ────────────────────────────────────────────────────

// Global error handler to catch any unhandled errors
window.addEventListener("error", (e) => {
  console.error("[G-Axis] Unhandled error:", e.message, e.filename, e.lineno);
});

try {
  init();
  console.log("[G-Axis] init() completed successfully");
} catch (e) {
  console.error("[G-Axis] init() failed:", e);
}
