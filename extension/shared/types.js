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
  PLAN_CHAT: "gaxis:plan_chat",
  APPROVE: "gaxis:approve",
  DENY: "gaxis:deny",
  STOP_TASK: "gaxis:stop_task",
  PAUSE_TASK: "gaxis:pause_task",
  RESUME_TASK: "gaxis:resume_task",
  TAKEOVER: "gaxis:takeover",
  GIVE_BACK: "gaxis:give_back",
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
  TASK_STOPPED: "gaxis:task_stopped",
  TASK_PAUSED: "gaxis:task_paused",
  TASK_RESUMED: "gaxis:task_resumed",
  HUMAN_TAKEOVER: "gaxis:human_takeover",
  AGENT_RESUMED: "gaxis:agent_resumed",
  PLAN_RESPONSE: "gaxis:plan_response",
  NEEDS_INPUT: "gaxis:needs_input",
  USER_INPUT: "gaxis:user_input",
  CONNECTION_STATUS: "gaxis:connection_status",
  ERROR: "gaxis:error",
  AGENT_ACTIVE: "gaxis:agent_active",
  MEMORY_LOADED: "gaxis:memory_loaded",
  CONFIRM_ACTION: "gaxis:confirm_action",
  STEERING_RECEIVED: "gaxis:steering_received",
  STEERING_APPLIED: "gaxis:steering_applied",
  RESEARCH_COMPLETE: "gaxis:research_complete",

  // Background <-> Content Script
  CAPTURE_SCREENSHOT: "gaxis:capture_screenshot",
  EXECUTE_ACTION: "gaxis:execute_action",
  SHOW_OVERLAY: "gaxis:show_overlay",
  CLEAR_OVERLAY: "gaxis:clear_overlay",
  SCAN_OVERLAY: "gaxis:scan_overlay",
  HIGHLIGHT_ELEMENT: "gaxis:highlight_element",

  // DOM intelligence
  GET_DOM_SNAPSHOT: "gaxis:get_dom_snapshot",
  DOM_SNAPSHOT: "gaxis:dom_snapshot",
  DOM_CHANGED: "gaxis:dom_changed",
  DOM_BLOCKER: "gaxis:dom_blocker",
  GET_PAGE_DATA: "gaxis:get_page_data",

  // Workspace management
  CLEANUP_WORKSPACE: "gaxis:cleanup_workspace",

  // Live Audio (Gemini Live API — bidirectional voice)
  LIVE_START: "gaxis:live_start",
  LIVE_STOP: "gaxis:live_stop",
  LIVE_AUDIO_IN: "gaxis:live_audio_in",
  LIVE_TEXT: "gaxis:live_text",
  LIVE_AUDIO_OUT: "gaxis:live_audio_out",
  LIVE_TRANSCRIPT_IN: "gaxis:live_transcript_in",
  LIVE_TRANSCRIPT_OUT: "gaxis:live_transcript_out",
  LIVE_STATUS: "gaxis:live_status",
};

// Default settings
export const DEFAULT_SETTINGS = {
  backendUrl: "http://localhost:8000",
  model: "gemini-3-flash-preview",
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
