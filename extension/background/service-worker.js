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

// ─── TAB-BOUND AGENT + WORKSPACE SANDBOX ─────────────────────
// G-Axis binds to the tab where it was opened. All actions run on
// THAT tab only. Sidepanel only shows for the bound tab — switching
// to another tab hides it. User's other tabs are never touched.
//
// If the agent needs additional tabs (cross-origin navigates), they
// are created inside a Chrome tab group called "G-Axis Workspace".
// This sandbox isolates agent tabs from user tabs.
let agentTabId = null;
let originalTabId = null;       // The tab where G-Axis was first opened
let workspaceGroupId = null;    // Chrome tab group ID
const workspaceTabs = new Set(); // All tab IDs managed by G-Axis

/** Bind G-Axis to the current active tab. Called when sidepanel opens or task starts. */
async function bindToCurrentTab() {
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (tab?.id) {
      agentTabId = tab.id;
      originalTabId = tab.id;
      workspaceTabs.add(tab.id);
      console.log("[G-Axis] Bound to tab:", agentTabId, tab.url?.substring(0, 60));
    }
  } catch (e) {
    console.error("[G-Axis] Failed to bind:", e);
  }
  return agentTabId;
}

/** Enable the side panel for a specific workspace tab. */
async function enablePanelForTab(tabId) {
  try {
    await chrome.sidePanel.setOptions({ tabId, path: "sidepanel/index.html", enabled: true });
    console.log("[G-Axis] Panel enabled for tab:", tabId);
  } catch (e) {
    console.error("[G-Axis] Failed to enable panel for tab:", tabId, e);
  }
}


/** Create or reuse the "G-Axis Workspace" tab group for sandbox isolation. */
async function ensureWorkspaceGroup() {
  // Verify existing group still exists
  if (workspaceGroupId != null) {
    try {
      await chrome.tabGroups.get(workspaceGroupId);
      return workspaceGroupId;
    } catch (_) {
      workspaceGroupId = null; // Group was closed/deleted by user
    }
  }

  // Create group from existing workspace tabs
  const tabIds = [...workspaceTabs].filter(id => id != null);
  if (tabIds.length === 0) return null;

  try {
    workspaceGroupId = await chrome.tabs.group({ tabIds });
    await chrome.tabGroups.update(workspaceGroupId, {
      title: "G-Axis Workspace",
      color: "blue",
      collapsed: false,
    });
    console.log("[G-Axis] Created workspace group:", workspaceGroupId);
  } catch (e) {
    console.error("[G-Axis] Failed to create tab group:", e);
  }
  return workspaceGroupId;
}

/** Open a new tab inside the workspace sandbox. */
async function openWorkspaceTab(url) {
  await ensureWorkspaceGroup();

  const newTab = await chrome.tabs.create({ url, active: true });
  workspaceTabs.add(newTab.id);

  // Enable sidepanel for this new workspace tab
  await enablePanelForTab(newTab.id);

  // Add to the workspace group
  if (workspaceGroupId != null) {
    try {
      await chrome.tabs.group({ tabIds: [newTab.id], groupId: workspaceGroupId });
    } catch (e) {
      console.error("[G-Axis] Failed to add tab to group:", e);
    }
  }

  // Switch agent target to the new tab
  agentTabId = newTab.id;
  console.log("[G-Axis] Opened workspace tab:", newTab.id, url?.substring(0, 60));
  return newTab;
}

/** Clean up workspace — close all agent-created tabs except the original. */
async function cleanupWorkspace() {
  const tabsToClose = [...workspaceTabs].filter(id => id !== originalTabId);
  for (const tabId of tabsToClose) {
    try {
      await chrome.tabs.remove(tabId);
    } catch (_) {} // Tab may already be closed
    workspaceTabs.delete(tabId);
  }

  // Ungroup the original tab
  if (originalTabId != null) {
    try {
      await chrome.tabs.ungroup(originalTabId);
    } catch (_) {}
  }

  // Reset state
  agentTabId = originalTabId;
  workspaceGroupId = null;

  console.log("[G-Axis] Workspace cleaned up, back to original tab:", originalTabId);
}

/** Send a message to the bound agent tab. Only targets workspace tabs. */
async function sendToAgentTab(msg) {
  if (agentTabId == null || !workspaceTabs.has(agentTabId)) return;
  try {
    await chrome.tabs.sendMessage(agentTabId, msg).catch(() => {});
  } catch (_) {}
}

// When a workspace tab is closed, update tracking
chrome.tabs.onRemoved.addListener((tabId) => {
  workspaceTabs.delete(tabId);

  if (tabId === agentTabId) {
    console.log("[G-Axis] Active agent tab closed");
    // Fall back to original tab or another workspace tab
    if (originalTabId != null && originalTabId !== tabId && workspaceTabs.has(originalTabId)) {
      agentTabId = originalTabId;
    } else {
      agentTabId = workspaceTabs.size > 0 ? [...workspaceTabs][0] : null;
    }
  }

  if (tabId === originalTabId) {
    console.log("[G-Axis] Original bound tab closed");
    originalTabId = null;
  }

  // If all workspace tabs are gone, reset and re-enable panel globally
  if (workspaceTabs.size === 0) {
    workspaceGroupId = null;
    agentTabId = null;
    originalTabId = null;
  }
});

// ─── EXTENSION LIFECYCLE ──────────────────────────────────────

// Global default: panel disabled. Only opened per-tab via icon click.
chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: false }).catch(() => {});

chrome.runtime.onInstalled.addListener(() => {
  chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: false }).catch(() => {});
  console.log("[G-Axis] Extension installed");
});

// Icon click: bind panel to THIS tab only and open it.
// No await — preserves user gesture context for sidePanel.open().
chrome.action.onClicked.addListener((tab) => {
  chrome.sidePanel.setOptions({
    tabId: tab.id,
    path: "sidepanel/index.html",
    enabled: true
  });
  chrome.sidePanel.open({ tabId: tab.id });

  agentTabId = tab.id;
  originalTabId = tab.id;
  workspaceTabs.add(tab.id);
  console.log("[G-Axis] Panel opened for workspace tab:", tab.id);
});

// Keep service worker alive using alarms (MV3 workaround)
chrome.alarms.create("keepalive", { periodInMinutes: 0.4 });
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === "keepalive") {
    // Reconnect if needed
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      connectToBackend();
    }
  }
});

// Keep alive via long-lived port from side panel
const activePorts = new Set();
chrome.runtime.onConnect.addListener((port) => {
  if (port.name === "keepalive") {
    activePorts.add(port);
    port.onDisconnect.addListener(() => {
      activePorts.delete(port);
    });
    // Side panel just opened. Only bind if not already bound by onClicked.
    if (agentTabId == null) {
      bindToCurrentTab();
    }
  }
});

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
  if (ws && ws.readyState === WebSocket.CONNECTING) return;

  // Close stale connection
  if (ws) {
    try { ws.close(); } catch (e) { /* ignore */ }
    ws = null;
  }

  const wsUrl = settings.backendUrl.replace(/^http/, "ws") + "/ws";

  try {
    ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      isConnected = true;
      console.log("WebSocket connected to backend");
      safeBroadcast({ type: MSG.CONNECTION_STATUS, data: { connected: true } });
      if (wsReconnectTimer) {
        clearTimeout(wsReconnectTimer);
        wsReconnectTimer = null;
      }
    };

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        if (msg.type !== "pong") {
          console.log("WS received:", msg.type);
        }
        handleBackendMessage(msg);
      } catch (e) {
        console.error("Failed to parse backend message:", e);
      }
    };

    ws.onclose = () => {
      isConnected = false;
      ws = null;
      console.log("WebSocket disconnected");
      safeBroadcast({ type: MSG.CONNECTION_STATUS, data: { connected: false } });
      scheduleReconnect();
    };

    ws.onerror = (e) => {
      console.error("WebSocket error");
      isConnected = false;
    };
  } catch (e) {
    console.error("WebSocket connection failed:", e);
    ws = null;
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
  } else {
    console.warn("WebSocket not open, can't send:", msg.type);
  }
}

// Send a ping every 20s to keep WebSocket alive
setInterval(() => {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: "ping" }));
  }
}, 20000);

// ─── SAFE BROADCAST ──────────────────────────────────────────

function safeBroadcast(msg) {
  // Send to side panel via ports (reliable, no "receiving end" errors)
  // Only use ports — do NOT also use runtime.sendMessage, as the side panel
  // listens on both channels and would process every message twice.
  let sentViaPort = false;
  for (const port of activePorts) {
    try {
      port.postMessage(msg);
      sentViaPort = true;
    } catch (e) {
      activePorts.delete(port);
    }
  }
  // Fallback to runtime.sendMessage ONLY if no ports are connected
  if (!sentViaPort) {
    try {
      chrome.runtime.sendMessage(msg).catch(() => {});
    } catch (e) {
      // No listeners — that's fine
    }
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
    plan_response: MSG.PLAN_RESPONSE,
    needs_input: MSG.NEEDS_INPUT,
    error: MSG.ERROR,
    agent_active: MSG.AGENT_ACTIVE,
    memory_loaded: MSG.MEMORY_LOADED,
    confirm_action: MSG.CONFIRM_ACTION,
    steering_received: MSG.STEERING_RECEIVED,
    steering_applied: MSG.STEERING_APPLIED,
    task_stopped: MSG.TASK_STOPPED,
    task_paused: MSG.TASK_PAUSED,
    task_resumed: MSG.TASK_RESUMED,
    human_takeover: MSG.HUMAN_TAKEOVER,
    agent_resumed: MSG.AGENT_RESUMED,
    // Live Audio
    live_audio_out: MSG.LIVE_AUDIO_OUT,
    live_transcript_in: MSG.LIVE_TRANSCRIPT_IN,
    live_transcript_out: MSG.LIVE_TRANSCRIPT_OUT,
    live_status: MSG.LIVE_STATUS,
  };

  // Backend requesting a screenshot
  if (msg.type === "request_screenshot") {
    console.log("Backend requested screenshot — capturing...");
    captureAndSendScreenshot();
    return;
  }

  // Backend requesting DOM snapshot
  if (msg.type === "request_dom_snapshot") {
    console.log("Backend requested DOM snapshot");
    requestDomSnapshot();
    return;
  }

  // Backend requesting action execution in the active tab
  if (msg.type === "execute_action") {
    console.log("Backend requested action:", msg.data?.action_type);

    // Navigate actions — same-origin reuses bound tab, cross-origin opens workspace tab
    if (msg.data?.action_type === "navigate" && msg.data?.url) {
      console.log("[G-Axis] Navigate request:", msg.data.url);
      safeBroadcast({ type: MSG.ACTION_PLANNED, data: msg.data, task_id: msg.task_id });

      (async () => {
        try {
          if (agentTabId == null) {
            await bindToCurrentTab();
          }
          if (agentTabId == null) {
            throw new Error("No bound tab");
          }

          // Decide: same-origin → reuse tab, cross-origin → new workspace tab
          let sameOrigin = true;
          try {
            const currentTab = await chrome.tabs.get(agentTabId);
            const currentOrigin = currentTab.url ? new URL(currentTab.url).origin : "";
            const targetOrigin = new URL(msg.data.url).origin;
            sameOrigin = currentOrigin === targetOrigin || !currentOrigin;
          } catch (_) {
            sameOrigin = true; // Default to reuse on parse errors
          }

          if (sameOrigin) {
            await chrome.tabs.update(agentTabId, { url: msg.data.url });
          } else {
            // Cross-origin: open in a new workspace tab (sandboxed)
            await openWorkspaceTab(msg.data.url);
            safeBroadcast({
              type: MSG.ACTION_PLANNED,
              data: { action_type: "workspace_tab", url: msg.data.url, reasoning: "Opened in G-Axis Workspace" },
            });
          }

          // Wait for page to load, then capture + confirm success
          setTimeout(() => {
            captureAndSendScreenshot();
            requestDomSnapshot();
            sendToBackend({
              type: "action_result",
              result: { success: true, url: msg.data.url },
            });
          }, 2500);
        } catch (e) {
          sendToBackend({
            type: "action_result",
            result: { success: false, error: e.message },
          });
        }
      })();
      return;
    }

    // All other actions — send to content script and wait for result
    sendToAgentTab({
      type: MSG.SHOW_OVERLAY,
      data: {
        action_type: msg.data?.action_type,
        x: msg.data?.x,
        y: msg.data?.y,
        element_description: msg.data?.element_description,
        reasoning: msg.data?.reasoning || msg.data?.element_description,
      },
    });
    safeBroadcast({ type: MSG.ACTION_PLANNED, data: msg.data, task_id: msg.task_id });

    // Send action to the bound tab
    const targetTabId = agentTabId;
    (async () => {
      if (!targetTabId) {
        sendToBackend({ type: "action_result", result: { success: false, error: "No agent tab" } });
        return;
      }
      let tab;
      try { tab = await chrome.tabs.get(targetTabId); } catch (_) {
        sendToBackend({ type: "action_result", result: { success: false, error: "Agent tab closed" } });
        return;
      }

      try {
        chrome.tabs.sendMessage(targetTabId, { type: MSG.EXECUTE_ACTION, data: msg.data }, (response) => {
          if (chrome.runtime.lastError) {
            console.error("Action execution error:", chrome.runtime.lastError.message);
            sendToBackend({
              type: "action_result",
              result: { success: false, error: chrome.runtime.lastError.message },
            });
          } else {
            console.log("Action result from content script:", response?.success);
            const result = {
              success: response?.success || false,
              error: response?.error || null,
              element: response?.element || null,
              url: tab.url || "",
            };
            // Pass through batch fill details (per-field results)
            if (response?.results) result.results = response.results;
            if (response?.filled != null) result.filled = response.filled;
            if (response?.total != null) result.total = response.total;
            sendToBackend({
              type: "action_result",
              result,
            });
          }

          // After action completes, capture fresh screenshot + DOM
          setTimeout(() => {
            sendToAgentTab({ type: MSG.CLEAR_OVERLAY });
            captureAndSendScreenshot();
            requestDomSnapshot();
          }, 300);
        });
      } catch (e) {
        console.error("Failed to send action to content script:", e);
        sendToBackend({
          type: "action_result",
          result: { success: false, error: e.message },
        });
      }
    })();
    return;
  }

  // Backend requesting page data (cookies, storage)
  if (msg.type === "request_page_data") {
    sendToAgentTab({ type: MSG.GET_PAGE_DATA });
    return;
  }

  // Track task lifecycle for re-sending to new pages
  if (msg.type === "task_started") {
    currentTaskData = msg.data || {};
  } else if (msg.type === "task_completed" || msg.type === "task_failed") {
    currentTaskData = null;
  }

  // Pong — ignore
  if (msg.type === "pong") return;

  const extType = typeMap[msg.type] || MSG.ERROR;
  safeBroadcast({ type: extType, data: msg.data, task_id: msg.task_id });

  // Visual feedback to content script
  if (msg.type === "perceiving") {
    sendToAgentTab({ type: MSG.PERCEIVING });
  }

  if (msg.type === "perception") {
    sendToAgentTab({ type: MSG.PERCEPTION });
  }

  if (msg.type === "action_succeeded" || msg.type === "task_completed" || msg.type === "task_failed") {
    sendToAgentTab({ type: MSG.CLEAR_OVERLAY });
  }

  // Perception overlay — highlight detected elements
  if (msg.type === "perception" && msg.data && msg.data.elements) {
    sendToAgentTab({
      type: MSG.HIGHLIGHT_ELEMENT,
      data: { elements: msg.data.elements },
    });
  }

  // Forward events to content script for the floating control bar
  const controlBarEvents = [
    "task_started", "agent_active", "action_planned",
    "action_succeeded", "task_completed", "task_failed", "needs_input",
    "task_stopped", "task_paused", "task_resumed", "human_takeover", "agent_resumed",
  ];
  if (controlBarEvents.includes(msg.type)) {
    sendToAgentTab({ type: typeMap[msg.type], data: msg.data, task_id: msg.task_id });
  }
}

// Side Panel / Content Script -> Background -> Backend
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  // ── Guard: reject content-script messages from non-workspace tabs ──
  // Side panel messages have no sender.tab; content scripts do.
  // Only process content script messages from tabs in our workspace.
  const senderTabId = sender?.tab?.id;
  const isContentScript = senderTabId != null;
  if (isContentScript && workspaceTabs.size > 0 && !workspaceTabs.has(senderTabId)) {
    // Not a workspace tab — ignore silently
    sendResponse({ ignored: true });
    return;
  }

  switch (message.type) {
    case MSG.CONNECT:
      connectToBackend();
      sendResponse({ connected: isConnected });
      break;

    case MSG.RUN_TASK:
      // Bind to the current tab where user opened G-Axis
      bindToCurrentTab().then(() => {
        sendToBackend({ type: "run_task", instruction: message.instruction, mode: "extension" });
      });
      sendResponse({ ok: true });
      break;

    case MSG.PLAN_CHAT:
      sendToBackend({ type: "plan_chat", message: message.text || "" });
      sendResponse({ ok: true });
      break;

    case MSG.APPROVE:
      sendToBackend({ type: "approve", edits: message.edits || null });
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

    case MSG.PAUSE_TASK:
      sendToBackend({ type: "pause" });
      sendResponse({ ok: true });
      break;

    case MSG.RESUME_TASK:
      sendToBackend({ type: "resume" });
      sendResponse({ ok: true });
      break;

    case MSG.TAKEOVER:
      sendToBackend({ type: "takeover" });
      sendResponse({ ok: true });
      break;

    case MSG.GIVE_BACK:
      sendToBackend({ type: "give_back" });
      sendResponse({ ok: true });
      break;

    case MSG.USER_INPUT:
      sendToBackend({ type: "user_input", text: message.text || "", steering: !!message.steering });
      sendResponse({ ok: true });
      break;

    case "gaxis:focus_agent_tab":
      // Tab-bound: agent runs on user's current tab, no separate tab to focus
      if (agentTabId != null) {
        chrome.tabs.update(agentTabId, { active: true }).catch(() => {});
      }
      sendResponse({ ok: true });
      break;

    // ── Live Audio passthrough ──
    case MSG.LIVE_START:
      sendToBackend({ type: "live_start" });
      sendResponse({ ok: true });
      break;

    case MSG.LIVE_STOP:
      sendToBackend({ type: "live_stop" });
      sendResponse({ ok: true });
      break;

    case MSG.LIVE_AUDIO_IN:
      // High-frequency — send raw audio chunk to backend, no logging
      sendToBackend({ type: "live_audio_in", data: message.data });
      // No sendResponse — fire and forget for performance
      break;

    case MSG.LIVE_TEXT:
      sendToBackend({ type: "live_text", text: message.text || "" });
      sendResponse({ ok: true });
      break;

    case "gaxis:type_cdp": {
      // CDP typing for Google Docs and other canvas-based editors
      const cdpTabId = agentTabId;
      if (!cdpTabId) {
        sendResponse({ success: false, error: "No agent tab bound" });
        break;
      }
      typeViaCDP(cdpTabId, message.text || "").then(result => {
        sendResponse(result);
      });
      return true; // async response
    }

    case MSG.CLEANUP_WORKSPACE:
      cleanupWorkspace().then(() => {
        safeBroadcast({ type: MSG.CLEANUP_WORKSPACE, data: { cleaned: true } });
      });
      sendResponse({ ok: true });
      break;

    case MSG.GET_SETTINGS:
      sendResponse({ settings });
      break;

    case MSG.SAVE_SETTINGS:
      settings = { ...DEFAULT_SETTINGS, ...message.settings };
      chrome.storage.local.set({ gaxis_settings: settings });
      if (ws) {
        try { ws.close(); } catch (e) { /* ignore */ }
        ws = null;
      }
      setTimeout(() => connectToBackend(), 500);
      sendResponse({ ok: true });
      break;

    case MSG.CAPTURE_SCREENSHOT:
      // Capture the bound tab screenshot
      (async () => {
        try {
          const wId = agentTabId != null
            ? (await chrome.tabs.get(agentTabId)).windowId
            : (await chrome.windows.getCurrent()).id;
          const dataUrl = await chrome.tabs.captureVisibleTab(wId, { format: "jpeg", quality: 75 });
          sendResponse({ screenshot: dataUrl });
        } catch (e) {
          sendResponse({ screenshot: "" });
        }
      })();
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

    // Content script detected a blocking overlay/dialog/popover
    case MSG.DOM_BLOCKER:
      sendToBackend({
        type: "dom_blocker",
        ...message.data,
      });
      // Also forward to sidepanel for timeline display
      safeBroadcast({
        type: MSG.DOM_BLOCKER,
        data: message.data,
      });
      sendResponse({ ok: true });
      break;

    default:
      sendResponse({ error: "Unknown message type" });
  }
});

// ─── CDP TYPING (for Google Docs and other canvas-based editors) ──────

/**
 * Type text into the focused element via Chrome Debugger Protocol.
 * Produces isTrusted=true events — works with Google Docs, Sheets, etc.
 *
 * @param {number} tabId - The tab to type into
 * @param {string} text - The text to insert
 * @returns {Promise<{success: boolean, error?: string}>}
 */
async function typeViaCDP(tabId, text) {
  const target = { tabId };

  try {
    await chrome.debugger.attach(target, "1.3");
  } catch (e) {
    // May already be attached
    if (!e.message?.includes("Already attached")) {
      return { success: false, error: `Debugger attach failed: ${e.message}` };
    }
  }

  try {
    // Insert text in chunks to avoid overwhelming the editor
    const CHUNK_SIZE = 2000;
    for (let i = 0; i < text.length; i += CHUNK_SIZE) {
      const chunk = text.slice(i, i + CHUNK_SIZE);
      await chrome.debugger.sendCommand(target, "Input.insertText", { text: chunk });
      // Small delay between chunks for the editor to process
      if (i + CHUNK_SIZE < text.length) {
        await new Promise(r => setTimeout(r, 100));
      }
    }
    return { success: true };
  } catch (e) {
    return { success: false, error: `CDP insertText failed: ${e.message}` };
  } finally {
    try {
      await chrome.debugger.detach(target);
    } catch (_) {}
  }
}

// ─── HELPERS ──────────────────────────────────────────────────

// NOTE: sendToAgentTab is defined above with the agent tab system.
// The old sendToActiveTab (queried active tab) is removed.

let _lastCaptureTime = 0;
const _MIN_CAPTURE_INTERVAL = 600; // ms — Chrome allows ~2/sec, stay safe

async function captureAndSendScreenshot() {
  // Throttle: Chrome enforces MAX_CAPTURE_VISIBLE_TAB_CALLS_PER_SECOND
  const now = Date.now();
  const elapsed = now - _lastCaptureTime;
  if (elapsed < _MIN_CAPTURE_INTERVAL) {
    await new Promise(r => setTimeout(r, _MIN_CAPTURE_INTERVAL - elapsed));
  }
  _lastCaptureTime = Date.now();

  try {
    // Get the bound tab (user's current tab where G-Axis was opened)
    let tab;
    if (agentTabId != null) {
      try { tab = await chrome.tabs.get(agentTabId); } catch (_) { tab = null; }
    }
    if (!tab) {
      sendToBackend({ type: "screenshot", screenshot: "", url: "", title: "" });
      return;
    }

    // Internal pages can't be captured
    if (tab.url?.startsWith("chrome://") || tab.url?.startsWith("chrome-extension://") ||
        tab.url?.startsWith("edge://") || tab.url?.startsWith("about:")) {
      sendToBackend({ type: "screenshot", screenshot: "", url: tab.url, title: tab.title || "" });
      return;
    }

    // Ensure the bound tab is active so captureVisibleTab works
    await chrome.tabs.update(agentTabId, { active: true });
    await new Promise(r => setTimeout(r, 80));

    const dataUrl = await chrome.tabs.captureVisibleTab(tab.windowId, {
      format: "jpeg",
      quality: 75,
    });

    if (!dataUrl) {
      sendToBackend({ type: "screenshot", screenshot: "", url: tab.url || "", title: tab.title || "" });
      return;
    }

    const b64 = dataUrl.replace(/^data:image\/\w+;base64,/, "");
    sendToBackend({ type: "screenshot", screenshot: b64, url: tab.url || "", title: tab.title || "" });
    console.log("[G-Axis] Screenshot from tab", tab.id, (tab.url || "").substring(0, 60));
  } catch (e) {
    console.error("[G-Axis] captureAndSendScreenshot failed:", e.message);
    sendToBackend({ type: "screenshot", screenshot: "", url: "", title: "" });
  }
}

async function requestDomSnapshot() {
  try {
    // Only target the workspace agent tab — never touch other tabs
    const tabId = agentTabId;
    if (tabId == null || !workspaceTabs.has(tabId)) return;

    let tabUrl = "";
    try {
      const t = await chrome.tabs.get(tabId);
      tabUrl = t?.url || "";
    } catch (_) { return; }

    if (!tabUrl.startsWith("chrome://") && !tabUrl.startsWith("chrome-extension://")) {
      chrome.tabs.sendMessage(tabId, { type: MSG.GET_DOM_SNAPSHOT }, (response) => {
        if (chrome.runtime.lastError) return;
        if (response?.elements) {
          latestDomSnapshot = response.elements;
          sendToBackend({
            type: "dom_snapshot",
            elements: latestDomSnapshot,
            url: tabUrl,
          });
        }
      });
    }
  } catch (e) {
    // Content script may not be injected
  }
}

// Track current task state for re-sending to new pages after navigation
let currentTaskData = null;

// Listen for workspace tab navigation to refresh DOM snapshots
chrome.webNavigation?.onCompleted?.addListener((details) => {
  // Only track workspace tabs — never touch user's other tabs
  if (details.frameId === 0 && workspaceTabs.has(details.tabId)) {
    setTimeout(() => {
      requestDomSnapshot();
      if (currentTaskData) {
        sendToAgentTab({ type: MSG.TASK_STARTED, data: currentTaskData });
      }
    }, 1000);
  }
});
