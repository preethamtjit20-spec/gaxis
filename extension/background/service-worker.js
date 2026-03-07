/**
 * G-Axis Background Service Worker
 *
 * Central hub that connects:
 *   Side Panel ↔ Backend (WebSocket)
 *   Side Panel ↔ Content Script
 *
 * Manages WebSocket lifecycle, message routing, and settings.
 */

import { MSG, DEFAULT_SETTINGS } from "../shared/types.js";

let ws = null;
let wsReconnectTimer = null;
let settings = { ...DEFAULT_SETTINGS };
let isConnected = false;

// ─── EXTENSION LIFECYCLE ──────────────────────────────────────

// Open side panel when extension icon is clicked
chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true });

// Load settings on startup
chrome.storage.local.get("gaxis_settings", (result) => {
  if (result.gaxis_settings) {
    settings = { ...DEFAULT_SETTINGS, ...result.gaxis_settings };
  }
  connectToBackend();
});

// ─── WEBSOCKET CONNECTION ─────────────────────────────────────

function connectToBackend() {
  if (ws && ws.readyState === WebSocket.OPEN) return;

  const wsUrl = settings.backendUrl.replace(/^http/, "ws") + "/ws";

  try {
    ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      isConnected = true;
      broadcastToSidePanel({ type: MSG.CONNECTION_STATUS, data: { connected: true } });
      if (wsReconnectTimer) {
        clearTimeout(wsReconnectTimer);
        wsReconnectTimer = null;
      }
    };

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        handleBackendMessage(msg);
      } catch (e) {
        console.error("Failed to parse backend message:", e);
      }
    };

    ws.onclose = () => {
      isConnected = false;
      broadcastToSidePanel({ type: MSG.CONNECTION_STATUS, data: { connected: false } });
      scheduleReconnect();
    };

    ws.onerror = () => {
      isConnected = false;
    };
  } catch (e) {
    console.error("WebSocket connection failed:", e);
    scheduleReconnect();
  }
}

function scheduleReconnect() {
  if (wsReconnectTimer) return;
  wsReconnectTimer = setTimeout(() => {
    wsReconnectTimer = null;
    connectToBackend();
  }, 5000);
}

function sendToBackend(msg) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(msg));
  }
}

// ─── MESSAGE ROUTING ──────────────────────────────────────────

// Backend → Side Panel + Content Script
function handleBackendMessage(msg) {
  // Map backend event types to extension message types
  const typeMap = {
    task_started: MSG.TASK_STARTED,
    perceiving: MSG.PERCEIVING,
    perception: MSG.PERCEPTION,
    action_planned: MSG.ACTION_PLANNED,
    action_succeeded: MSG.ACTION_SUCCEEDED,
    action_failed: MSG.ACTION_FAILED,
    approval_needed: MSG.APPROVAL_NEEDED,
    task_completed: MSG.TASK_COMPLETED,
    task_failed: MSG.TASK_FAILED,
    error: MSG.ERROR,
  };

  // Handle backend requesting a screenshot from the extension
  if (msg.type === "request_screenshot") {
    captureAndSendScreenshot();
    return;
  }

  // Handle backend requesting action execution in the active tab
  if (msg.type === "execute_action") {
    sendToActiveTab({ type: MSG.EXECUTE_ACTION, data: msg.data });
    // After action, send fresh screenshot back
    setTimeout(() => captureAndSendScreenshot(), 800);
    // Also forward to side panel
    broadcastToSidePanel({ type: MSG.ACTION_PLANNED, data: msg.data, task_id: msg.task_id });
    return;
  }

  const extType = typeMap[msg.type] || MSG.ERROR;
  broadcastToSidePanel({ type: extType, data: msg.data, task_id: msg.task_id });

  // Also send visual feedback to content script
  if (msg.type === "action_planned" && msg.data) {
    sendToActiveTab({
      type: MSG.SHOW_OVERLAY,
      data: {
        action_type: msg.data.action_type,
        x: msg.data.x,
        y: msg.data.y,
        element_id: msg.data.element_id,
        reasoning: msg.data.reasoning,
      },
    });
  }

  if (msg.type === "action_succeeded" || msg.type === "task_completed" || msg.type === "task_failed") {
    sendToActiveTab({ type: MSG.CLEAR_OVERLAY });
  }

  // Show perception overlay — highlight detected elements
  if (msg.type === "perception" && msg.data && msg.data.elements) {
    sendToActiveTab({
      type: MSG.HIGHLIGHT_ELEMENT,
      data: { elements: msg.data.elements },
    });
  }
}

// Side Panel → Background → Backend/Content Script
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  switch (message.type) {
    case MSG.CONNECT:
      connectToBackend();
      sendResponse({ connected: isConnected });
      break;

    case MSG.RUN_TASK:
      sendToBackend({ type: "run_task", instruction: message.instruction, mode: "extension" });
      sendResponse({ ok: true });
      break;

    case MSG.APPROVE:
      sendToBackend({ type: "approve" });
      sendResponse({ ok: true });
      break;

    case MSG.DENY:
      sendToBackend({ type: "deny" });
      sendResponse({ ok: true });
      break;

    case MSG.STOP_TASK:
      sendToBackend({ type: "stop" });
      sendResponse({ ok: true });
      break;

    case MSG.GET_SETTINGS:
      sendResponse({ settings });
      break;

    case MSG.SAVE_SETTINGS:
      settings = { ...DEFAULT_SETTINGS, ...message.settings };
      chrome.storage.local.set({ gaxis_settings: settings });
      // Reconnect if backend URL changed
      if (ws) {
        ws.close();
      }
      connectToBackend();
      sendResponse({ ok: true });
      break;

    case MSG.CAPTURE_SCREENSHOT:
      captureActiveTab().then((dataUrl) => sendResponse({ screenshot: dataUrl }));
      return true; // async response

    default:
      sendResponse({ error: "Unknown message type" });
  }
});

// ─── HELPERS ──────────────────────────────────────────────────

function broadcastToSidePanel(msg) {
  chrome.runtime.sendMessage(msg).catch(() => {
    // Side panel may not be open — ignore
  });
}

async function sendToActiveTab(msg) {
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (tab?.id) {
      chrome.tabs.sendMessage(tab.id, msg).catch(() => {});
    }
  } catch (e) {
    // No active tab — ignore
  }
}

async function captureActiveTab() {
  try {
    const dataUrl = await chrome.tabs.captureVisibleTab(null, {
      format: "jpeg",
      quality: 75,
    });
    return dataUrl;
  } catch (e) {
    console.error("Screenshot capture failed:", e);
    return null;
  }
}

async function captureAndSendScreenshot() {
  try {
    const dataUrl = await captureActiveTab();
    if (!dataUrl) return;

    // Strip data:image/jpeg;base64, prefix
    const b64 = dataUrl.replace(/^data:image\/\w+;base64,/, "");

    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    const url = tab?.url || "";
    const title = tab?.title || "";

    sendToBackend({
      type: "screenshot",
      screenshot: b64,
      url,
      title,
    });
  } catch (e) {
    console.error("captureAndSendScreenshot failed:", e);
  }
}
