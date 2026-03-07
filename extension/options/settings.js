/**
 * G-Axis Settings Page
 */

import { MSG, DEFAULT_SETTINGS } from "../shared/types.js";

const $ = (id) => document.getElementById(id);

let settings = { ...DEFAULT_SETTINGS };

// ─── LOAD ─────────────────────────────────────────────────────

async function loadSettings() {
  return new Promise((resolve) => {
    chrome.runtime.sendMessage({ type: MSG.GET_SETTINGS }, (response) => {
      if (response?.settings) {
        settings = { ...DEFAULT_SETTINGS, ...response.settings };
      }
      populateUI();
      resolve();
    });
  });
}

function populateUI() {
  $("backend-url").value = settings.backendUrl;
  $("model-select").value = settings.model;
  $("temperature").value = settings.temperature;
  $("temperature-value").textContent = settings.temperature;
  $("max-steps").value = settings.maxSteps;
  $("confidence-threshold").value = settings.confidenceThreshold;
  $("confidence-value").textContent = `${Math.round(settings.confidenceThreshold * 100)}%`;
  $("blocked-domains").value = (settings.blockedDomains || []).join("\n");
  $("approve-passwords").checked = settings.alwaysApprovePasswords;
  $("approve-payments").checked = settings.alwaysApprovePayments;
  $("allow-downloads").checked = settings.allowDownloads;
  $("voice-enabled").checked = settings.voiceEnabled;
  $("voice-language").value = settings.voiceLanguage;

  // Set supervision mode radio
  const radio = document.querySelector(`input[name="supervision"][value="${settings.supervisionMode}"]`);
  if (radio) radio.checked = true;

  // Agent identity
  const baseUrl = settings.backendUrl || "https://gaxis-xxxxx.run.app";
  $("agent-card-url").textContent = `${baseUrl}/.well-known/agent.json`;
  $("mcp-endpoint").textContent = `${baseUrl.replace(/^http/, "ws")}/mcp`;
}

// ─── SAVE ─────────────────────────────────────────────────────

function gatherSettings() {
  return {
    backendUrl: $("backend-url").value.replace(/\/+$/, ""),
    model: $("model-select").value,
    temperature: parseFloat($("temperature").value),
    maxSteps: parseInt($("max-steps").value),
    supervisionMode: document.querySelector('input[name="supervision"]:checked')?.value || "supervised",
    confidenceThreshold: parseFloat($("confidence-threshold").value),
    blockedDomains: $("blocked-domains").value.split("\n").map((d) => d.trim()).filter(Boolean),
    alwaysApprovePasswords: $("approve-passwords").checked,
    alwaysApprovePayments: $("approve-payments").checked,
    allowDownloads: $("allow-downloads").checked,
    voiceEnabled: $("voice-enabled").checked,
    voiceLanguage: $("voice-language").value,
  };
}

async function saveSettings() {
  const newSettings = gatherSettings();
  chrome.runtime.sendMessage({ type: MSG.SAVE_SETTINGS, settings: newSettings }, () => {
    $("save-status").textContent = "Saved!";
    setTimeout(() => ($("save-status").textContent = ""), 2000);
  });
}

// ─── TEST CONNECTION ──────────────────────────────────────────

async function testConnection() {
  const url = $("backend-url").value.replace(/\/+$/, "");
  const result = $("connection-result");
  result.textContent = "Testing...";
  result.style.color = "var(--text-dim)";

  try {
    const resp = await fetch(`${url}/health`, { signal: AbortSignal.timeout(5000) });
    if (resp.ok) {
      result.textContent = "Connected successfully!";
      result.style.color = "var(--success)";
    } else {
      result.textContent = `Failed: HTTP ${resp.status}`;
      result.style.color = "var(--danger)";
    }
  } catch (e) {
    result.textContent = `Failed: ${e.message}`;
    result.style.color = "var(--danger)";
  }
}

// ─── EVENT LISTENERS ──────────────────────────────────────────

$("save-btn").addEventListener("click", saveSettings);
$("test-connection").addEventListener("click", testConnection);

$("temperature").addEventListener("input", (e) => {
  $("temperature-value").textContent = e.target.value;
});

$("confidence-threshold").addEventListener("input", (e) => {
  $("confidence-value").textContent = `${Math.round(e.target.value * 100)}%`;
});

$("backend-url").addEventListener("input", () => {
  const url = $("backend-url").value.replace(/\/+$/, "");
  $("agent-card-url").textContent = `${url}/.well-known/agent.json`;
  $("mcp-endpoint").textContent = `${url.replace(/^http/, "ws")}/mcp`;
});

$("clear-history").addEventListener("click", () => {
  if (confirm("Clear all task history? This cannot be undone.")) {
    chrome.storage.local.remove("gaxis_history");
    $("task-count").textContent = "0 tasks";
  }
});

// ─── INIT ─────────────────────────────────────────────────────

loadSettings();
