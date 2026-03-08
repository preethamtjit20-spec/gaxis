/**
 * G-Axis Background Service Worker
 *
 * Central hub that connects:
 *   Side Panel <-> Backend (WebSocket)
 *   Side Panel <-> Content Script
 *
 * Manages WebSocket lifecycle, message routing, DOM snapshots, and settings.
 */

import { MSG, DEFAULT_SETTINGS } from "../shared/types.js";

let ws = null;
let wsReconnectTimer = null;
let settings = { ...DEFAULT_SETTINGS };
let isConnected = false;
let latestDomSnapshot = [];

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

// Backend -> Side Panel + Content Script
function handleBackendMessage(msg) {
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
    agent_active: MSG.AGENT_ACTIVE,
    memory_loaded: MSG.MEMORY_LOADED,
  };

  // Backend requesting a screenshot
  if (msg.type === "request_screenshot") {
    captureAndSendScreenshot();
    return;
  }

  // Backend requesting DOM snapshot
  if (msg.type === "request_dom_snapshot") {
    requestDomSnapshot();
    return;
  }

  // Backend requesting action execution in the active tab
  if (msg.type === "execute_action") {
    sendToActiveTab({ type: MSG.EXECUTE_ACTION, data: msg.data });
    // After action, send fresh screenshot + DOM snapshot
    setTimeout(() => {
      captureAndSendScreenshot();
      requestDomSnapshot();
    }, 800);
    broadcastToSidePanel({ type: MSG.ACTION_PLANNED, data: msg.data, task_id: msg.task_id });
    return;
  }

  // Backend requesting page data (cookies, storage)
  if (msg.type === "request_page_data") {
    sendToActiveTab({ type: MSG.GET_PAGE_DATA });
    return;
  }

  const extType = typeMap[msg.type] || MSG.ERROR;
  broadcastToSidePanel({ type: extType, data: msg.data, task_id: msg.task_id });

  // Visual feedback to content script
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

  // Perception overlay — highlight detected elements
  if (msg.type === "perception" && msg.data && msg.data.elements) {
    sendToActiveTab({
      type: MSG.HIGHLIGHT_ELEMENT,
      data: { elements: msg.data.elements },
    });
  }
}

// Side Panel / Content Script -> Background -> Backend
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  switch (message.type) {
    case MSG.CONNECT:
      connectToBackend();
      sendResponse({ connected: isConnected });
      break;

    case MSG.RUN_TASK:
      // Before running task, get a DOM snapshot
      requestDomSnapshot();
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
      if (ws) ws.close();
      connectToBackend();
      sendResponse({ ok: true });
      break;

    case MSG.CAPTURE_SCREENSHOT:
      captureActiveTab().then((dataUrl) => sendResponse({ screenshot: dataUrl }));
      return true; // async

    // Content script sending DOM snapshot
    case MSG.DOM_SNAPSHOT:
      latestDomSnapshot = message.data?.elements || [];
      sendToBackend({
        type: "dom_snapshot",
        elements: latestDomSnapshot,
        url: message.data?.url || "",
      });
      sendResponse({ ok: true });
      break;

    // Content script reporting DOM mutations
    case MSG.DOM_CHANGED:
      sendToBackend({
        type: "dom_changed",
        changes: message.data?.changes || [],
        url: message.data?.url || "",
      });
      sendResponse({ ok: true });
      break;

    default:
      sendResponse({ error: "Unknown message type" });
  }
});

// ─── HELPERS ──────────────────────────────────────────────────

function broadcastToSidePanel(msg) {
  chrome.runtime.sendMessage(msg).catch(() => {});
}

async function sendToActiveTab(msg) {
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (tab?.id) {
      chrome.tabs.sendMessage(tab.id, msg).catch(() => {});
    }
  } catch (e) {
    // No active tab
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
    const b64 = dataUrl.replace(/^data:image\/\w+;base64,/, "");
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    const url = tab?.url || "";
    const title = tab?.title || "";
    sendToBackend({ type: "screenshot", screenshot: b64, url, title });
  } catch (e) {
    console.error("captureAndSendScreenshot failed:", e);
  }
}

async function requestDomSnapshot() {
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (tab?.id) {
      chrome.tabs.sendMessage(tab.id, { type: MSG.GET_DOM_SNAPSHOT }, (response) => {
        if (response?.elements) {
          latestDomSnapshot = response.elements;
          sendToBackend({
            type: "dom_snapshot",
            elements: latestDomSnapshot,
            url: tab.url || "",
          });
        }
      });
    }
  } catch (e) {
    // Content script may not be injected
  }
}

// Listen for tab navigation to refresh DOM snapshots
chrome.webNavigation?.onCompleted?.addListener((details) => {
  if (details.frameId === 0) {
    // Main frame navigation complete — get fresh DOM snapshot
    setTimeout(() => requestDomSnapshot(), 1000);
  }
});
