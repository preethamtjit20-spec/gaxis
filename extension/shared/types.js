/**
 * Shared types and constants for G-Axis extension.
 *
 * Message types for communication between:
 *   Side Panel <-> Background <-> Content Script <-> Backend
 */

// Message types: Extension internal
export const MSG = {
  // Side Panel -> Background
  CONNECT: "gaxis:connect",
  RUN_TASK: "gaxis:run_task",
  APPROVE: "gaxis:approve",
  DENY: "gaxis:deny",
  STOP_TASK: "gaxis:stop_task",
  GET_SETTINGS: "gaxis:get_settings",
  SAVE_SETTINGS: "gaxis:save_settings",

  // Background -> Side Panel (forwarded from backend)
  TASK_STARTED: "gaxis:task_started",
  PERCEIVING: "gaxis:perceiving",
  PERCEPTION: "gaxis:perception",
  ACTION_PLANNED: "gaxis:action_planned",
  ACTION_SUCCEEDED: "gaxis:action_succeeded",
  ACTION_FAILED: "gaxis:action_failed",
  APPROVAL_NEEDED: "gaxis:approval_needed",
  TASK_COMPLETED: "gaxis:task_completed",
  TASK_FAILED: "gaxis:task_failed",
  CONNECTION_STATUS: "gaxis:connection_status",
  ERROR: "gaxis:error",
  AGENT_ACTIVE: "gaxis:agent_active",
  MEMORY_LOADED: "gaxis:memory_loaded",

  // Background <-> Content Script
  CAPTURE_SCREENSHOT: "gaxis:capture_screenshot",
  EXECUTE_ACTION: "gaxis:execute_action",
  SHOW_OVERLAY: "gaxis:show_overlay",
  CLEAR_OVERLAY: "gaxis:clear_overlay",
  HIGHLIGHT_ELEMENT: "gaxis:highlight_element",

  // DOM intelligence
  GET_DOM_SNAPSHOT: "gaxis:get_dom_snapshot",
  DOM_SNAPSHOT: "gaxis:dom_snapshot",
  DOM_CHANGED: "gaxis:dom_changed",
  GET_PAGE_DATA: "gaxis:get_page_data",
};

// Default settings
export const DEFAULT_SETTINGS = {
  backendUrl: "http://localhost:8000",
  model: "gemini-2.5-pro-preview-06-05",
  temperature: 0.2,
  maxSteps: 30,
  supervisionMode: "supervised", // supervised | semi-auto | autonomous
  confidenceThreshold: 0.4,
  blockedDomains: [],
  alwaysApprovePasswords: true,
  alwaysApprovePayments: true,
  allowDownloads: false,
  voiceEnabled: true,
  voiceLanguage: "en-US",
};
