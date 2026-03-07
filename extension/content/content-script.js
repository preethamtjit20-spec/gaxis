/**
 * G-Axis Content Script
 *
 * Injected into every page. Handles:
 *   - Visual overlays (action dots, element highlights, scanning bar)
 *   - Screenshot capture via chrome.tabs API
 *   - Direct action execution on the page (click, type, scroll)
 */

// Content scripts cannot use ES modules — inline the message constants
const MSG = {
  PERCEIVING: "gaxis:perceiving",
  PERCEPTION: "gaxis:perception",
  ACTION_PLANNED: "gaxis:action_planned",
  EXECUTE_ACTION: "gaxis:execute_action",
  SHOW_OVERLAY: "gaxis:show_overlay",
  CLEAR_OVERLAY: "gaxis:clear_overlay",
  HIGHLIGHT_ELEMENT: "gaxis:highlight_element",
};

let overlayContainer = null;

// ─── OVERLAY MANAGEMENT ──────────────────────────────────────

function ensureOverlay() {
  if (overlayContainer && document.body.contains(overlayContainer)) return overlayContainer;

  overlayContainer = document.createElement("div");
  overlayContainer.id = "gaxis-overlay-root";
  overlayContainer.className = "gaxis-overlay";
  document.body.appendChild(overlayContainer);
  return overlayContainer;
}

function clearOverlay() {
  if (overlayContainer) {
    overlayContainer.innerHTML = "";
  }
  // Remove scanning bar
  const scanBar = document.getElementById("gaxis-scan-bar");
  if (scanBar) scanBar.remove();
}

function showActionOverlay(data) {
  const overlay = ensureOverlay();
  clearOverlay();

  if (data.x == null || data.y == null) return;

  // Pulsing red dot at action coordinates
  const dot = document.createElement("div");
  dot.className = "gaxis-action-dot";
  dot.style.left = `${data.x}px`;
  dot.style.top = `${data.y}px`;
  overlay.appendChild(dot);

  // Label showing what the agent is doing
  const label = document.createElement("div");
  label.className = "gaxis-action-label";
  label.style.left = `${data.x}px`;
  label.style.top = `${data.y}px`;

  const actionText = data.action_type?.toUpperCase() || "ACTION";
  const reasoning = data.reasoning || "";
  label.textContent = `${actionText}: ${reasoning}`.slice(0, 60);
  overlay.appendChild(label);
}

function showScanningBar() {
  if (document.getElementById("gaxis-scan-bar")) return;
  const bar = document.createElement("div");
  bar.id = "gaxis-scan-bar";
  bar.className = "gaxis-scanning";
  document.body.appendChild(bar);
}

function showSuccessFlash() {
  const flash = document.createElement("div");
  flash.className = "gaxis-success-flash";
  document.body.appendChild(flash);
  setTimeout(() => flash.remove(), 500);
}

function highlightElements(elements) {
  const overlay = ensureOverlay();

  // Remove old highlights only
  overlay.querySelectorAll(".gaxis-element-highlight").forEach((el) => el.remove());

  if (!elements || !Array.isArray(elements)) return;

  for (const el of elements.slice(0, 20)) {
    if (!el.x || !el.y || !el.width || !el.height) continue;

    const box = document.createElement("div");
    box.className = `gaxis-element-highlight ${el.is_sensitive ? "sensitive" : ""}`;
    box.style.left = `${el.x - el.width / 2}px`;
    box.style.top = `${el.y - el.height / 2}px`;
    box.style.width = `${el.width}px`;
    box.style.height = `${el.height}px`;

    if (el.id) {
      const lbl = document.createElement("div");
      lbl.className = "gaxis-element-label";
      lbl.textContent = el.id;
      box.appendChild(lbl);
    }

    overlay.appendChild(box);
  }
}

// ─── ACTION EXECUTION ─────────────────────────────────────────

async function executeAction(data) {
  try {
    switch (data.action_type) {
      case "click":
        if (data.x != null && data.y != null) {
          const target = document.elementFromPoint(data.x, data.y);
          if (target) {
            target.click();
            showSuccessFlash();
          }
        }
        break;

      case "type":
      case "select_all_and_type":
        if (data.x != null && data.y != null) {
          const input = document.elementFromPoint(data.x, data.y);
          if (input) {
            input.focus();
            if (data.action_type === "select_all_and_type") {
              input.select?.();
            }
            if (data.text) {
              // Use execCommand for contenteditable, value for inputs
              if (input.value !== undefined) {
                input.value = data.text;
                input.dispatchEvent(new Event("input", { bubbles: true }));
                input.dispatchEvent(new Event("change", { bubbles: true }));
              } else {
                document.execCommand("insertText", false, data.text);
              }
            }
          }
        }
        break;

      case "scroll":
        const delta = data.direction === "up" ? -(data.pixels || 300) : (data.pixels || 300);
        window.scrollBy({ top: delta, behavior: "smooth" });
        break;

      case "press_key":
        if (data.key) {
          document.activeElement?.dispatchEvent(
            new KeyboardEvent("keydown", { key: data.key, bubbles: true })
          );
          document.activeElement?.dispatchEvent(
            new KeyboardEvent("keyup", { key: data.key, bubbles: true })
          );
        }
        break;
    }

    return { success: true };
  } catch (e) {
    return { success: false, error: e.message };
  }
}

// ─── MESSAGE HANDLER ──────────────────────────────────────────

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  switch (message.type) {
    case MSG.SHOW_OVERLAY:
      showActionOverlay(message.data);
      sendResponse({ ok: true });
      break;

    case MSG.CLEAR_OVERLAY:
      clearOverlay();
      sendResponse({ ok: true });
      break;

    case MSG.HIGHLIGHT_ELEMENT:
      highlightElements(message.data?.elements);
      sendResponse({ ok: true });
      break;

    case MSG.EXECUTE_ACTION:
      executeAction(message.data).then((result) => sendResponse(result));
      return true; // async

    default:
      break;
  }
});

// Show scanning bar when perceiving
chrome.runtime.onMessage.addListener((message) => {
  if (message.type === MSG.PERCEIVING) {
    showScanningBar();
  }
  if (message.type === MSG.PERCEPTION || message.type === MSG.ACTION_PLANNED) {
    const scanBar = document.getElementById("gaxis-scan-bar");
    if (scanBar) scanBar.remove();
  }
});
