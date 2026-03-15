/**
 * G-Axis Content Script
 *
 * Injected into every page. Handles:
 *   - Visual overlays (action dots, element highlights, scanning bar)
 *   - DOM snapshot extraction (precise element coordinates)
 *   - MutationObserver for dynamic DOM change detection
 *   - Human-like action execution (anti-bot resilient)
 *   - Cookie and storage access
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
  GET_DOM_SNAPSHOT: "gaxis:get_dom_snapshot",
  DOM_SNAPSHOT: "gaxis:dom_snapshot",
  DOM_CHANGED: "gaxis:dom_changed",
  DOM_BLOCKER: "gaxis:dom_blocker",
  GET_PAGE_DATA: "gaxis:get_page_data",
};

let overlayContainer = null;
let mutationBuffer = [];
let mutationFlushTimer = null;

/**
 * Check if the extension context is still valid.
 * chrome.runtime becomes undefined when the extension reloads/updates
 * while a content script is still running on a page.
 */
function isExtensionValid() {
  return !!(chrome.runtime && chrome.runtime.id);
}

/** Safe wrapper for chrome.runtime.sendMessage */
function safeSendMessage(msg) {
  if (!isExtensionValid()) return Promise.resolve();
  try {
    return chrome.runtime.sendMessage(msg).catch(() => {});
  } catch {
    return Promise.resolve();
  }
}

/** Safe wrapper for chrome.runtime.onMessage.addListener */
function safeAddListener(callback) {
  if (!isExtensionValid()) return;
  try {
    chrome.runtime.onMessage.addListener((...args) => {
      if (!isExtensionValid()) return;
      return callback(...args);
    });
  } catch {
    // Extension context invalidated
  }
}

// ─── DOM SNAPSHOT ─────────────────────────────────────────────

/**
 * Extract a structured snapshot of all interactive elements on the page.
 * Provides precise coordinates that supplement Gemini's visual estimates.
 */
function getDOMSnapshot() {
  const selectors = [
    "a", "button", "input", "select", "textarea",
    '[role="button"]', '[role="link"]', '[role="tab"]',
    '[role="menuitem"]', '[role="checkbox"]', '[role="radio"]',
    '[role="option"]', '[role="listbox"]', '[role="combobox"]',
    '[role="switch"]', '[role="slider"]',
    "[onclick]", "[tabindex]",
    'label[for]', '[contenteditable="true"]',
    '[data-value]', 'summary',
  ];

  const elements = document.querySelectorAll(selectors.join(", "));

  return Array.from(elements)
    .map((el) => {
      const rect = el.getBoundingClientRect();
      // Skip invisible elements
      if (rect.width === 0 && rect.height === 0) return null;
      // Skip elements fully off-screen
      if (rect.bottom < 0 || rect.top > window.innerHeight) return null;
      if (rect.right < 0 || rect.left > window.innerWidth) return null;

      const style = window.getComputedStyle(el);
      if (style.display === "none" || style.visibility === "hidden" || style.opacity === "0") {
        return null;
      }

      return {
        tag: el.tagName.toLowerCase(),
        type: el.type || null,
        text: (el.textContent || "").trim().slice(0, 100),
        placeholder: el.placeholder || null,
        name: el.name || null,
        id: el.id || null,
        className: (el.className || "").toString().slice(0, 100),
        href: el.href || null,
        value: el.value ? el.value.slice(0, 50) : null,
        x: Math.round(rect.x + rect.width / 2),
        y: Math.round(rect.y + rect.height / 2),
        width: Math.round(rect.width),
        height: Math.round(rect.height),
        visible: true,
        ariaLabel: el.getAttribute("aria-label") || null,
        ariaRole: el.getAttribute("role") || null,
        disabled: el.disabled || false,
        readonly: el.readOnly || false,
        required: el.required || false,
        isSensitive: isSensitiveField(el),
      };
    })
    .filter(Boolean);
}

function isSensitiveField(el) {
  if (el.type === "password") return true;
  const nameAndId = ((el.name || "") + (el.id || "") + (el.placeholder || "")).toLowerCase();
  const sensitiveWords = ["password", "passwd", "secret", "credit", "card", "cvv", "ssn", "social"];
  return sensitiveWords.some((w) => nameAndId.includes(w));
}

// ─── MUTATION OBSERVER + BLOCKER DETECTION ───────────────────

/**
 * Watch for DOM changes — detects dynamic content loading,
 * popup appearances, form validation errors, etc.
 *
 * Layer 1 of the DOM monitor: MutationObserver fires on every DOM
 * change. If a dialog/popover/overlay appears, we detect it instantly
 * and try to dismiss it deterministically (Layer 2). If we can't,
 * we send a DOM_BLOCKER event to the backend for Gemini vision (Layer 3).
 */

// Selectors that identify blocking overlays / dialogs / popovers
const BLOCKER_SELECTORS = [
  'dialog[open]',
  '[role="dialog"]', '[role="alertdialog"]',
  '[aria-modal="true"]',
  '.modal.show', '.modal.in', '.modal-backdrop',
  '[class*="popover"]', '[class*="popup"]',
  '[class*="overlay"]:not(#gaxis-overlay-root)',
  '[class*="toast"]', '[class*="snackbar"]',
  // Google-specific
  // '[data-eventid]', // DISABLED — matches calendar events on grid, causes false positives
  '.Kj-JD', // Google Workspace dialog
  '.RnGBXc', // Gmail compose popover
];

// Known blocker patterns we can dismiss deterministically (Layer 2)
const KNOWN_BLOCKER_HANDLERS = [
  // Google Calendar "Send invitations?" → click "Send"
  { match: (el) => el.textContent?.includes("Send") && el.closest('[role="dialog"]'),
    action: (el) => { const btn = el.closest('[role="dialog"]')?.querySelector('button[name="send"], [data-mdc-dialog-action="ok"], button:last-child'); if (btn) { btn.click(); return true; } return false; } },
  // Google Calendar "Don't send" / "Save" dialogs
  { match: (el) => el.querySelector?.('button[name="save"], [data-mdc-dialog-action="save"]'),
    action: (el) => { const btn = el.querySelector('button[name="save"], [data-mdc-dialog-action="save"]'); if (btn) { btn.click(); return true; } return false; } },
  // Generic "OK" / "Got it" / "Done" buttons inside dialogs
  { match: (el) => el.querySelector?.('button'),
    action: (el) => {
      const btns = el.querySelectorAll('button');
      for (const btn of btns) {
        const t = btn.textContent?.trim().toLowerCase() || "";
        if (["ok", "got it", "done", "yes", "accept", "confirm", "send", "allow"].includes(t)) {
          btn.click();
          console.log("[G-Axis] Dismissed known blocker via button:", t);
          return true;
        }
      }
      return false;
    }
  },
  // Close button (X) in top-right
  { match: (el) => el.querySelector?.('[aria-label="Close" i], [aria-label="Dismiss" i], .close-btn, .modal-close'),
    action: (el) => { const btn = el.querySelector('[aria-label="Close" i], [aria-label="Dismiss" i], .close-btn, .modal-close'); if (btn) { btn.click(); return true; } return false; } },
];

let lastBlockerCheck = 0;

/**
 * Check if a newly added node is a blocking overlay.
 * If found: try deterministic dismiss (Layer 2).
 * If can't dismiss: send DOM_BLOCKER event to backend (Layer 3 — Gemini vision).
 */
function checkForBlocker(addedNode) {
  if (!addedNode || !addedNode.nodeType || addedNode.nodeType !== 1) return;
  if (addedNode.id?.startsWith("gaxis-")) return;

  // Throttle: don't fire more than once per second
  const now = Date.now();
  if (now - lastBlockerCheck < 1000) return;

  // Check if the added node itself or any child matches blocker selectors
  let blockerEl = null;
  for (const sel of BLOCKER_SELECTORS) {
    try {
      if (addedNode.matches?.(sel)) { blockerEl = addedNode; break; }
      const child = addedNode.querySelector?.(sel);
      if (child) { blockerEl = child; break; }
    } catch (_) {}
  }
  if (!blockerEl) return;

  // Also check z-index — high z-index = likely overlay
  const style = window.getComputedStyle(blockerEl);
  const zIndex = parseInt(style.zIndex) || 0;
  const isVisible = blockerEl.offsetWidth > 0 && blockerEl.offsetHeight > 0;
  if (!isVisible) return;

  lastBlockerCheck = now;
  console.log("[G-Axis] Blocker detected:", describeElement(blockerEl), "z-index:", zIndex);

  // Layer 2: Try known deterministic handlers
  for (const handler of KNOWN_BLOCKER_HANDLERS) {
    try {
      if (handler.match(blockerEl) && handler.action(blockerEl)) {
        console.log("[G-Axis] Blocker dismissed deterministically");
        safeSendMessage({
          type: MSG.DOM_BLOCKER,
          data: {
            status: "dismissed",
            element: describeElement(blockerEl),
            text: (blockerEl.textContent || "").slice(0, 200).trim(),
            url: window.location.href,
            timestamp: now,
          },
        });
        return;
      }
    } catch (_) {}
  }

  // Layer 3: Can't dismiss — send to backend for Gemini vision recovery
  console.log("[G-Axis] Unknown blocker — requesting Gemini vision recovery");
  safeSendMessage({
    type: MSG.DOM_BLOCKER,
    data: {
      status: "blocked",
      element: describeElement(blockerEl),
      role: blockerEl.getAttribute("role") || "",
      text: (blockerEl.textContent || "").slice(0, 300).trim(),
      buttons: Array.from(blockerEl.querySelectorAll("button")).map(b => ({
        text: b.textContent?.trim().slice(0, 50),
        ariaLabel: b.getAttribute("aria-label") || "",
      })),
      zIndex,
      rect: blockerEl.getBoundingClientRect(),
      url: window.location.href,
      timestamp: now,
    },
  });
}

const observer = new MutationObserver((mutations) => {
  const significant = mutations.filter((m) => {
    const targetId = typeof m.target.id === "string" ? m.target.id : "";
    if (targetId.startsWith("gaxis-")) return false;
    if (m.target.closest && m.target.closest("#gaxis-overlay-root")) return false;
    return true;
  });

  if (significant.length === 0) return;

  // Check added nodes for blockers (instant — no buffering)
  for (const m of significant) {
    if (m.type === "childList" && m.addedNodes.length > 0) {
      for (const node of m.addedNodes) {
        checkForBlocker(node);
      }
    }
  }

  // Buffer general mutations for the standard DOM_CHANGED event
  const changes = significant.slice(0, 10).map((m) => ({
    type: m.type,
    target: describeElement(m.target),
    addedNodes: m.addedNodes.length,
    removedNodes: m.removedNodes.length,
    attributeName: m.attributeName || null,
  }));

  mutationBuffer.push(...changes);

  if (!mutationFlushTimer) {
    mutationFlushTimer = setTimeout(() => {
      if (mutationBuffer.length > 0) {
        safeSendMessage({
          type: MSG.DOM_CHANGED,
          data: {
            changes: mutationBuffer.slice(0, 20),
            timestamp: Date.now(),
            url: window.location.href,
          },
        });
        mutationBuffer = [];
      }
      mutationFlushTimer = null;
    }, 500);
  }
});

function describeElement(el) {
  if (!el || !el.tagName) return "text";
  const tag = el.tagName.toLowerCase();
  const id = el.id ? `#${el.id}` : "";
  const cls = el.className ? `.${el.className.toString().split(" ")[0]}` : "";
  return `${tag}${id}${cls}`;
}

// Start observing after page is ready
if (document.body) {
  observer.observe(document.body, {
    childList: true,
    subtree: true,
    attributes: true,
    attributeFilter: ["class", "style", "disabled", "hidden", "aria-hidden"],
  });
}

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
  const scanBar = document.getElementById("gaxis-scan-bar");
  if (scanBar) scanBar.remove();
}

function showScanOverlay(text) {
  removeScanOverlay();
  const scan = document.createElement("div");
  scan.id = "gaxis-scan-fullscreen";
  scan.innerHTML = `
    <div style="
      position: fixed; inset: 0; z-index: 2147483646;
      background: rgba(26, 115, 232, 0.08);
      backdrop-filter: blur(1px);
      display: flex; flex-direction: column;
      align-items: center; justify-content: center;
      pointer-events: none;
      animation: gaxis-scan-pulse 2s ease-in-out infinite;
    ">
      <div style="
        background: rgba(26, 115, 232, 0.12);
        border: 2px solid rgba(26, 115, 232, 0.3);
        border-radius: 16px;
        padding: 20px 32px;
        display: flex; align-items: center; gap: 14px;
        box-shadow: 0 4px 24px rgba(26, 115, 232, 0.15);
      ">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#1a73e8" stroke-width="2" style="animation: gaxis-scan-spin 1.5s linear infinite;">
          <circle cx="12" cy="12" r="10" stroke-dasharray="40 20"/>
        </svg>
        <span style="
          font-family: 'Google Sans', -apple-system, sans-serif;
          font-size: 15px; font-weight: 500;
          color: #1a73e8;
        ">${text}</span>
      </div>
    </div>
    <div style="
      position: fixed; top: 0; left: 0; right: 0; height: 3px;
      z-index: 2147483647;
      background: linear-gradient(90deg, transparent, #1a73e8, transparent);
      animation: gaxis-scan-line 2s ease-in-out infinite;
    "></div>
    <style>
      @keyframes gaxis-scan-pulse {
        0%, 100% { background: rgba(26, 115, 232, 0.06); }
        50% { background: rgba(26, 115, 232, 0.12); }
      }
      @keyframes gaxis-scan-spin {
        to { transform: rotate(360deg); }
      }
      @keyframes gaxis-scan-line {
        0% { transform: translateX(-100%); }
        100% { transform: translateX(100%); }
      }
    </style>
  `;
  document.body.appendChild(scan);
}

function removeScanOverlay() {
  const el = document.getElementById("gaxis-scan-fullscreen");
  if (el) el.remove();
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

// ─── ACTION EXECUTION ENGINE ─────────────────────────────────

// FAST_MODE: minimal delays for maximum speed. Set false for human-like stealth.
const FAST_MODE = true;

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function randomDelay(min = 30, max = 100) {
  if (FAST_MODE) return Math.max(2, min * 0.1); // ~10% of normal delay
  return min + Math.random() * (max - min);
}

// Track virtual cursor position for smooth transitions
let cursorX = window.innerWidth / 2;
let cursorY = window.innerHeight / 2;

/**
 * DOM-Vision coordinate reconciliation.
 * Given vision-estimated (x, y) and an element description,
 * find the best matching DOM element and return its precise center coordinates.
 */
function reconcileCoordinates(x, y, elementDescription) {
  // First check what's actually at the vision coordinates
  const directTarget = document.elementFromPoint(x, y);

  // If description is provided, try to find the best DOM match
  if (elementDescription) {
    const desc = elementDescription.toLowerCase();
    const candidates = [];

    // Search for matching interactive elements
    const selectors = "a, button, input, select, textarea, [role='button'], [type='submit']";
    document.querySelectorAll(selectors).forEach((el) => {
      const rect = el.getBoundingClientRect();
      if (rect.width === 0 || rect.height === 0) return;

      const text = (el.textContent || "").toLowerCase().trim();
      const ariaLabel = (el.getAttribute("aria-label") || "").toLowerCase();
      const title = (el.getAttribute("title") || "").toLowerCase();
      const placeholder = (el.placeholder || "").toLowerCase();
      const value = (el.value || "").toLowerCase();

      // Score how well this element matches the description
      let score = 0;
      const allText = `${text} ${ariaLabel} ${title} ${placeholder} ${value}`;

      // Check if description words appear in element text
      const descWords = desc.split(/\s+/).filter((w) => w.length > 2);
      for (const word of descWords) {
        if (allText.includes(word)) score += 2;
      }

      // Proximity bonus — closer to vision coordinates = higher score
      const centerX = rect.x + rect.width / 2;
      const centerY = rect.y + rect.height / 2;
      const distance = Math.sqrt((centerX - x) ** 2 + (centerY - y) ** 2);
      if (distance < 100) score += 3;
      else if (distance < 200) score += 1;

      if (score > 0) {
        candidates.push({
          element: el,
          x: Math.round(centerX),
          y: Math.round(centerY),
          score,
          distance,
          text: text.slice(0, 50),
        });
      }
    });

    // Sort by score (desc), then distance (asc)
    candidates.sort((a, b) => b.score - a.score || a.distance - b.distance);

    if (candidates.length > 0) {
      const best = candidates[0];
      console.log(
        `[G-Axis] Reconciled: "${elementDescription}" → "${best.text}" at (${best.x},${best.y}) score=${best.score} dist=${Math.round(best.distance)}px`
      );
      return { x: best.x, y: best.y, element: best.element, reconciled: true };
    }
  }

  // Fallback: use original coordinates with the direct target
  return { x, y, element: directTarget, reconciled: false };
}

/**
 * Pre-click validation: confirm the element at target coordinates
 * is actually what we intend to interact with.
 */
function validateTarget(x, y, elementDescription, expectedType) {
  const target = document.elementFromPoint(x, y);
  if (!target) return { valid: false, reason: "No element at coordinates", element: null };

  // Check if element is interactive
  const tag = target.tagName.toLowerCase();
  const role = target.getAttribute("role");
  const interactive = ["a", "button", "input", "select", "textarea", "label"].includes(tag) ||
    role === "button" || role === "link" || role === "tab" ||
    target.onclick || target.getAttribute("tabindex");

  if (!interactive) {
    // Walk up the DOM tree to find the nearest interactive parent
    let parent = target.parentElement;
    let depth = 0;
    while (parent && depth < 8) {
      const ptag = parent.tagName.toLowerCase();
      const prole = parent.getAttribute("role") || "";
      const isClickable =
        ["a", "button"].includes(ptag) ||
        ["button", "link", "tab", "menuitem", "option", "listbox"].includes(prole) ||
        parent.onclick ||
        parent.getAttribute("tabindex") ||
        parent.getAttribute("data-action") ||
        parent.getAttribute("jsaction") ||
        parent.getAttribute("data-href") ||
        (ptag === "a" && parent.hasAttribute("href"));
      if (isClickable) {
        const rect = parent.getBoundingClientRect();
        return {
          valid: true,
          element: parent,
          adjustedX: Math.round(rect.x + rect.width / 2),
          adjustedY: Math.round(rect.y + rect.height / 2),
          reason: `Adjusted to parent <${ptag}>`,
        };
      }
      parent = parent.parentElement;
      depth++;
    }
  }

  return { valid: true, element: target, adjustedX: x, adjustedY: y, reason: "OK" };
}

/**
 * Smooth Bezier cursor trajectory from current position to target.
 * Generates intermediate points along a curved path like a real human.
 */
function generateCursorPath(fromX, fromY, toX, toY) {
  const points = [];
  const distance = Math.sqrt((toX - fromX) ** 2 + (toY - fromY) ** 2);
  const steps = Math.max(8, Math.min(25, Math.floor(distance / 20)));

  // Random control point for bezier curve (human hands don't move in straight lines)
  const cpX = (fromX + toX) / 2 + (Math.random() - 0.5) * distance * 0.3;
  const cpY = (fromY + toY) / 2 + (Math.random() - 0.5) * distance * 0.3;

  for (let i = 0; i <= steps; i++) {
    const t = i / steps;
    // Ease-in-out timing (slow start, fast middle, slow end)
    const ease = t < 0.5 ? 2 * t * t : 1 - (-2 * t + 2) ** 2 / 2;

    // Quadratic bezier
    const x = (1 - ease) ** 2 * fromX + 2 * (1 - ease) * ease * cpX + ease ** 2 * toX;
    const y = (1 - ease) ** 2 * fromY + 2 * (1 - ease) * ease * cpY + ease ** 2 * toY;

    points.push({ x: Math.round(x), y: Math.round(y) });
  }

  return points;
}

/**
 * Move cursor along a smooth path, dispatching mousemove events.
 */
async function moveCursorTo(targetX, targetY) {
  if (FAST_MODE) {
    // Skip cursor animation — just update position
    cursorX = targetX;
    cursorY = targetY;
    return;
  }

  const path = generateCursorPath(cursorX, cursorY, targetX, targetY);

  for (const point of path) {
    const target = document.elementFromPoint(point.x, point.y);
    if (target) {
      target.dispatchEvent(new MouseEvent("mousemove", {
        bubbles: true, clientX: point.x, clientY: point.y, view: window,
      }));
    }
    await sleep(randomDelay(8, 18));
  }

  cursorX = targetX;
  cursorY = targetY;
}

/**
 * Full human-like click flow:
 * 1. Reconcile coordinates with DOM
 * 2. Validate target element
 * 3. Smooth cursor movement
 * 4. Hover → mousedown → mouseup → click event sequence
 */
async function humanClick(x, y, elementDescription) {
  // Step 1: Reconcile vision coordinates with DOM
  const reconciled = reconcileCoordinates(x, y, elementDescription);
  const targetX = reconciled.x;
  const targetY = reconciled.y;

  if (reconciled.reconciled) {
    console.log(`[G-Axis] Using reconciled coordinates: (${x},${y}) → (${targetX},${targetY})`);
  }

  // Step 2: Validate target
  const validation = validateTarget(targetX, targetY, elementDescription);
  if (!validation.valid) {
    return { success: false, error: validation.reason };
  }

  const finalX = validation.adjustedX || targetX;
  const finalY = validation.adjustedY || targetY;
  const target = validation.element;

  // Step 3: Smooth cursor movement
  await moveCursorTo(finalX, finalY);

  // Step 4: Full event sequence (PointerEvent + MouseEvent for Google Apps compatibility)
  const opts = { bubbles: true, cancelable: true, clientX: finalX, clientY: finalY, view: window };
  const ptrOpts = { ...opts, pointerId: 1, pointerType: "mouse", isPrimary: true, width: 1, height: 1, pressure: 0.5 };

  await sleep(randomDelay(30, 60));
  target.dispatchEvent(new PointerEvent("pointerover", ptrOpts));
  target.dispatchEvent(new PointerEvent("pointerenter", { ...ptrOpts, bubbles: false }));
  target.dispatchEvent(new MouseEvent("mouseover", opts));
  target.dispatchEvent(new MouseEvent("mouseenter", { ...opts, bubbles: false }));

  await sleep(randomDelay(20, 40));
  target.dispatchEvent(new PointerEvent("pointerdown", { ...ptrOpts, button: 0 }));
  target.dispatchEvent(new MouseEvent("mousedown", { ...opts, button: 0 }));

  await sleep(randomDelay(50, 100));
  target.dispatchEvent(new PointerEvent("pointerup", { ...ptrOpts, button: 0 }));
  target.dispatchEvent(new MouseEvent("mouseup", { ...opts, button: 0 }));
  target.dispatchEvent(new MouseEvent("click", { ...opts, button: 0 }));

  // Native click fallback for React/Vue/Google jsaction apps
  try { target.click(); } catch (_) {}
  // Also click the raw element at point (in case target is adjusted ancestor)
  const rawEl = document.elementFromPoint(finalX, finalY);
  if (rawEl && rawEl !== target) {
    try { rawEl.click(); } catch (_) {}
  }

  // Focus if it's an input
  if (target.focus && ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)) {
    target.focus();
  }

  showSuccessFlash();
  return {
    success: true,
    reconciled: reconciled.reconciled,
    element: describeElement(target),
    coordinates: { original: { x, y }, final: { x: finalX, y: finalY } },
  };
}

/**
 * Full human-like type flow:
 * 1. Click to focus (with reconciliation)
 * 2. Clear if needed
 * 3. Type char by char with realistic timing
 */
async function humanType(x, y, text, clearFirst = false, elementDescription) {
  // Reconcile and click to focus
  const clickResult = await humanClick(x, y, elementDescription);
  if (!clickResult.success) return clickResult;

  await sleep(randomDelay(80, 150));

  // Get the focused element (may differ from clicked element)
  const target = document.activeElement;
  if (!target || target === document.body) {
    return { success: false, error: "No element received focus after click" };
  }

  // Clear existing text if requested
  if (clearFirst) {
    if (target.select) {
      target.select();
      await sleep(randomDelay(20, 40));
      target.dispatchEvent(new KeyboardEvent("keydown", { key: "Backspace", bubbles: true }));
      if (target.value !== undefined) target.value = "";
      target.dispatchEvent(new Event("input", { bubbles: true }));
    } else if (target.value !== undefined) {
      target.value = "";
      target.dispatchEvent(new Event("input", { bubbles: true }));
    }
    await sleep(randomDelay(30, 60));
  }

  // Type text
  if (target.value !== undefined) {
    if (FAST_MODE) {
      // FAST: Set value directly + dispatch events for React/Angular
      target.value = text;
      target.dispatchEvent(new Event("input", { bubbles: true }));
      target.dispatchEvent(new Event("change", { bubbles: true }));
      // Also fire a keydown/keyup for frameworks that listen to those
      target.dispatchEvent(new KeyboardEvent("keydown", { key: text.slice(-1) || "a", bubbles: true }));
      target.dispatchEvent(new KeyboardEvent("keyup", { key: text.slice(-1) || "a", bubbles: true }));
    } else {
      // HUMAN-LIKE: Type character by character
      for (const char of text) {
        const delay = randomDelay(30, 80);
        await sleep(delay);
        target.dispatchEvent(new KeyboardEvent("keydown", { key: char, code: `Key${char.toUpperCase()}`, bubbles: true }));
        target.value += char;
        target.dispatchEvent(new Event("input", { bubbles: true }));
        target.dispatchEvent(new KeyboardEvent("keypress", { key: char, bubbles: true }));
        target.dispatchEvent(new KeyboardEvent("keyup", { key: char, bubbles: true }));
      }
      target.dispatchEvent(new Event("change", { bubbles: true }));
    }
  } else {
    // ContentEditable / rich editors (Google Docs, Gmail body, etc.)
    // Google Docs uses a custom canvas renderer with a hidden input capture.
    // document.execCommand is deprecated and fails silently in Docs.
    // Strategy: clipboard paste for Docs, execCommand for others.
    const isGoogleDocs = location.hostname === "docs.google.com";

    if (isGoogleDocs) {
      // Google Docs: custom canvas editor that ignores execCommand.
      // Two distinct targets:
      //   1. TITLE: input.docs-title-input (standard HTML input — easy)
      //   2. BODY: hidden textarea in .docs-texteventtarget-iframe (hard)
      try {
        // Check if we're focused on the title field (input at top of doc)
        const titleInput = document.querySelector("input.docs-title-input, input.docs-title-widget");
        const activeEl = document.activeElement;
        const isInTitle = titleInput && (activeEl === titleInput ||
          (target && target.closest && target.closest(".docs-title-outer")) ||
          (target && target.classList && (target.classList.contains("docs-title-input") || target.classList.contains("docs-title-widget"))));

        if (isInTitle || (titleInput && !document.querySelector(".docs-texteventtarget-iframe"))) {
          // TITLE field — standard input, just set value and dispatch
          if (titleInput) {
            titleInput.focus();
            await sleep(50);
            titleInput.value = "";
            titleInput.value = text;
            titleInput.dispatchEvent(new Event("input", { bubbles: true }));
            titleInput.dispatchEvent(new Event("change", { bubbles: true }));
            await sleep(100);
            // Press Tab to confirm title and move to body
            titleInput.dispatchEvent(new KeyboardEvent("keydown", { key: "Tab", keyCode: 9, bubbles: true }));
            console.log("[G-Axis] Docs title set via input.value:", text.substring(0, 40));
          }
          await sleep(100);
          return { success: true, typed: text.length, element: "docs-title-input" };
        }

        // BODY field — use Chrome Debugger Protocol (CDP) for trusted input.
        // Google Docs uses a canvas-based editor that ignores synthetic
        // (isTrusted=false) DOM events. CDP Input.insertText produces
        // trusted events that Docs processes correctly.
        console.log("[G-Axis] Docs body: typing via CDP Input.insertText");
        try {
          const cdpResult = await new Promise((resolve) => {
            chrome.runtime.sendMessage(
              { type: "gaxis:type_cdp", text },
              (response) => {
                if (chrome.runtime.lastError) {
                  resolve({ success: false, error: chrome.runtime.lastError.message });
                } else {
                  resolve(response || { success: false, error: "No response" });
                }
              }
            );
          });

          if (cdpResult.success) {
            console.log("[G-Axis] Docs body: CDP typing succeeded, chars:", text.length);
          } else {
            console.warn("[G-Axis] Docs body: CDP typing failed:", cdpResult.error);
            // Fallback: try execCommand (works in some contentEditable contexts)
            document.execCommand("insertText", false, text);
          }
        } catch (e) {
          console.warn("[G-Axis] Docs body: CDP error:", e.message);
          document.execCommand("insertText", false, text);
        }

        await sleep(200);
      } catch (e) {
        console.warn("[G-Axis] Docs typing failed:", e.message);
        // Ultimate fallback
        document.execCommand("insertText", false, text);
      }
    } else {
      // Standard contenteditable (Gmail compose, etc.)
      if (FAST_MODE) {
        document.execCommand("insertText", false, text);
      } else {
        for (const char of text) {
          await sleep(randomDelay(30, 80));
          document.execCommand("insertText", false, char);
        }
      }
    }
  }

  return { success: true, typed: text.length, element: describeElement(target) };
}

/**
 * Human-like scroll with smooth behavior
 */
async function humanScroll(direction, pixels = 400) {
  const delta = direction === "up" ? -pixels : pixels;
  window.scrollBy({ top: delta, behavior: "smooth" });
  await sleep(300);
  return { success: true };
}

/**
 * Press a keyboard key with proper event sequence.
 * Uses chrome.debugger if available (via background), falls back to DOM events.
 */
async function humanPressKey(key) {
  // Map key names to Chrome key codes
  const KEY_MAP = {
    Enter: { code: "Enter", keyCode: 13, text: "\r" },
    Tab: { code: "Tab", keyCode: 9, text: "" },
    Escape: { code: "Escape", keyCode: 27, text: "" },
    Backspace: { code: "Backspace", keyCode: 8, text: "" },
    ArrowDown: { code: "ArrowDown", keyCode: 40, text: "" },
    ArrowUp: { code: "ArrowUp", keyCode: 38, text: "" },
    ArrowLeft: { code: "ArrowLeft", keyCode: 37, text: "" },
    ArrowRight: { code: "ArrowRight", keyCode: 39, text: "" },
    Space: { code: "Space", keyCode: 32, text: " " },
  };

  const keyInfo = KEY_MAP[key] || { code: key, keyCode: 0, text: "" };
  const target = document.activeElement || document.body;

  // Dispatch DOM events with all properties for maximum compatibility
  const eventInit = {
    key,
    code: keyInfo.code,
    keyCode: keyInfo.keyCode,
    which: keyInfo.keyCode,
    bubbles: true,
    cancelable: true,
    composed: true,
    view: window,
  };

  await sleep(randomDelay(20, 50));
  const downEvent = new KeyboardEvent("keydown", eventInit);
  const notPrevented = target.dispatchEvent(downEvent);

  await sleep(randomDelay(10, 30));
  target.dispatchEvent(new KeyboardEvent("keypress", { ...eventInit, cancelable: true }));

  await sleep(randomDelay(30, 70));
  target.dispatchEvent(new KeyboardEvent("keyup", { ...eventInit }));

  // Special handling for Enter key
  if (key === "Enter") {
    // Google Search: navigate directly to search URL to bypass AI Mode redirect
    if (window.location.hostname.includes("google.com") || window.location.hostname.includes("google.co")) {
      const searchInput = document.querySelector('input[name="q"], textarea[name="q"], input[type="search"]');
      if (searchInput && searchInput.value) {
        const query = encodeURIComponent(searchInput.value);
        window.location.href = `https://www.google.com/search?q=${query}&udm=14`;
        return { success: true };
      }
    }

    // YouTube: navigate to search results URL
    if (window.location.hostname.includes("youtube.com")) {
      const searchInput = document.querySelector('input#search, input[name="search_query"]');
      if (searchInput && searchInput.value) {
        const query = encodeURIComponent(searchInput.value);
        window.location.href = `https://www.youtube.com/results?search_query=${query}`;
        return { success: true };
      }
    }

    // Generic: try form submit
    if (target.form) {
      const submitBtn = target.form.querySelector('input[type="submit"], button[type="submit"], button:not([type])');
      if (submitBtn) {
        submitBtn.click();
      } else {
        target.form.requestSubmit ? target.form.requestSubmit() : target.form.submit();
      }
    }

    // Fallback: find and click submit button
    const searchBtn = document.querySelector(
      'button[type="submit"], [role="button"][aria-label*="earch"]'
    );
    if (searchBtn) {
      await sleep(100);
      searchBtn.click();
    }
  }

  return { success: true };
}

/**
 * Hover over an element to trigger tooltips/dropdowns
 */
async function humanHover(x, y) {
  const target = document.elementFromPoint(x, y);
  if (!target) return { success: false, error: "No element at coordinates" };

  const opts = { bubbles: true, clientX: x, clientY: y, view: window };
  target.dispatchEvent(new MouseEvent("mouseenter", opts));
  target.dispatchEvent(new MouseEvent("mouseover", opts));
  target.dispatchEvent(new MouseEvent("mousemove", opts));

  return { success: true };
}

// ─── DOM QUERY BY HINTS (TEXT MATCHING) ─────────────────────

/**
 * Find a DOM element using semantic hints (placeholder, aria-label, text, tag).
 * This is FASTER and MORE RELIABLE than coordinate-based targeting.
 * Used by fill_form batch action and as primary element finder.
 */
function findByHint(hints) {
  if (!hints) return null;

  // Strategy 1: Direct aria-label match
  if (hints.aria) {
    const el = document.querySelector(`[aria-label="${hints.aria}"]`) ||
               document.querySelector(`[aria-label*="${hints.aria}" i]`);
    if (el && el.offsetWidth > 0) return el;
  }

  // Strategy 2: Placeholder match
  if (hints.placeholder) {
    const el = document.querySelector(`[placeholder="${hints.placeholder}"]`) ||
               document.querySelector(`[placeholder*="${hints.placeholder}" i]`);
    if (el && el.offsetWidth > 0) return el;
  }

  // Strategy 3: data-value match (Google Calendar chips)
  if (hints.data_value) {
    const el = document.querySelector(`[data-value="${hints.data_value}"]`);
    if (el && el.offsetWidth > 0) return el;
  }

  // Strategy 4: Text content match (buttons, links)
  if (hints.text) {
    const textLower = hints.text.toLowerCase();
    const tag = hints.tag || "*";
    const candidates = document.querySelectorAll(
      `${tag}, [role="button"], [role="link"], [role="tab"], [role="menuitem"], button, a`
    );
    for (const el of candidates) {
      const elText = (el.textContent || "").trim().toLowerCase();
      if (elText === textLower || elText.includes(textLower)) {
        if (el.offsetWidth > 0 && el.offsetHeight > 0) return el;
      }
    }
    // Also check aria-label for text
    const ariaMatch = document.querySelector(`[aria-label*="${hints.text}" i]`);
    if (ariaMatch && ariaMatch.offsetWidth > 0) return ariaMatch;
  }

  // Strategy 5: Tag + role combo
  if (hints.tag && hints.role) {
    const el = document.querySelector(`${hints.tag}[role="${hints.role}"]`);
    if (el && el.offsetWidth > 0) return el;
  }

  // Strategy 6: ContentEditable elements (Google Calendar description, etc.)
  if (hints.contenteditable || (hints.tag && hints.tag !== "input" && hints.tag !== "textarea")) {
    const selector = hints.tag
      ? `${hints.tag}[contenteditable="true"]`
      : '[contenteditable="true"]';
    const candidates = document.querySelectorAll(selector);
    for (const el of candidates) {
      if (el.offsetWidth > 0 && el.offsetHeight > 0) {
        // If we have aria or placeholder hints, verify match
        const ariaLabel = (el.getAttribute("aria-label") || "").toLowerCase();
        const phText = (el.getAttribute("data-placeholder") || el.getAttribute("placeholder") || "").toLowerCase();
        const innerText = (el.textContent || "").trim().toLowerCase();
        const hintText = (hints.placeholder || hints.aria || hints.text || "").toLowerCase();
        if (hintText && (ariaLabel.includes(hintText) || phText.includes(hintText) || innerText.includes(hintText))) {
          return el;
        }
        // If no specific hint to match against, return first visible contenteditable of this tag
        if (!hintText) return el;
      }
    }
  }

  return null;
}

/**
 * Get center coordinates of an element.
 */
function getElementCenter(el) {
  const rect = el.getBoundingClientRect();
  return { x: Math.round(rect.x + rect.width / 2), y: Math.round(rect.y + rect.height / 2) };
}

/**
 * Focus an element using click events (handles Google Apps jsaction).
 */
async function focusElement(el) {
  const { x, y } = getElementCenter(el);
  const opts = { bubbles: true, cancelable: true, clientX: x, clientY: y, view: window, button: 0 };
  const ptrOpts = { ...opts, pointerId: 1, pointerType: "mouse", isPrimary: true, width: 1, height: 1, pressure: 0.5 };

  // Hover events first (required by Google Calendar/Gmail jsaction handlers)
  el.dispatchEvent(new PointerEvent("pointerover", ptrOpts));
  el.dispatchEvent(new PointerEvent("pointerenter", { ...ptrOpts, bubbles: false }));
  el.dispatchEvent(new MouseEvent("mouseover", opts));
  el.dispatchEvent(new MouseEvent("mouseenter", { ...opts, bubbles: false }));
  await sleep(FAST_MODE ? 15 : randomDelay(30, 50));

  // Click sequence
  el.dispatchEvent(new PointerEvent("pointerdown", { ...ptrOpts, button: 0 }));
  el.dispatchEvent(new MouseEvent("mousedown", { ...opts, button: 0 }));
  await sleep(FAST_MODE ? 30 : randomDelay(50, 100));
  el.dispatchEvent(new PointerEvent("pointerup", { ...ptrOpts, button: 0 }));
  el.dispatchEvent(new MouseEvent("mouseup", { ...opts, button: 0 }));
  el.dispatchEvent(new MouseEvent("click", { ...opts, button: 0 }));

  // Native click fallback for jsaction apps
  try { el.click(); } catch (_) {}
  // Also click raw element at same coords (in case target is ancestor)
  const rawEl = document.elementFromPoint(x, y);
  if (rawEl && rawEl !== el) {
    try { rawEl.click(); } catch (_) {}
  }

  if (el.focus) el.focus();
  await sleep(FAST_MODE ? 30 : randomDelay(50, 100));
}

/**
 * Type into an already-focused element.
 */
async function typeIntoElement(el, text, clearFirst = false) {
  const target = document.activeElement === el ? el : document.activeElement;

  if (clearFirst) {
    if (target.select) {
      target.select();
      await sleep(FAST_MODE ? 5 : randomDelay(20, 40));
    }
    if (target.value !== undefined) {
      target.value = "";
    } else {
      document.execCommand("selectAll", false, null);
      document.execCommand("delete", false, null);
    }
    target.dispatchEvent(new Event("input", { bubbles: true }));
    await sleep(FAST_MODE ? 5 : randomDelay(20, 40));
  }

  if (target.value !== undefined) {
    // Use native input setter to trigger React's synthetic events
    const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
      window.HTMLInputElement.prototype, 'value'
    )?.set || Object.getOwnPropertyDescriptor(
      window.HTMLTextAreaElement.prototype, 'value'
    )?.set;
    if (nativeInputValueSetter) {
      nativeInputValueSetter.call(target, text);
    } else {
      target.value = text;
    }
    target.dispatchEvent(new Event("input", { bubbles: true }));
    target.dispatchEvent(new Event("change", { bubbles: true }));
  } else {
    // ContentEditable
    document.execCommand("insertText", false, text);
  }
}

/**
 * Dismiss autocomplete/suggestion dropdown by pressing Escape then re-focusing.
 */
async function dismissAutocomplete(el) {
  // Wait a tiny bit for dropdown to appear
  await sleep(FAST_MODE ? 30 : 200);

  // Check if any listbox/dropdown is visible
  const dropdown = document.querySelector(
    '[role="listbox"], [role="menu"], .pac-container, ' +
    '[class*="autocomplete"], [class*="suggestion"], [class*="dropdown"]'
  );
  if (dropdown && dropdown.offsetHeight > 0) {
    // Press Escape to dismiss
    document.activeElement?.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Escape", code: "Escape", keyCode: 27, bubbles: true, cancelable: true })
    );
    await sleep(FAST_MODE ? 10 : 50);
  }
}

/**
 * BATCH FORM FILL — execute an entire form fill sequence in one shot.
 * Each field has: { hints, value, action, press_enter, clear_first, wait_after }
 * hints = { placeholder, aria, text, tag } for DOM querying
 * action = "type" | "click" | "select_all_and_type"
 *
 * This eliminates per-field LLM calls — ~10x faster for known forms.
 */
async function batchFillForm(fields) {
  const results = [];

  for (const field of fields) {
    const { hints, value, action, press_enter, clear_first, wait_after } = field;
    let el = null;

    // Find element by hint
    if (hints) {
      el = findByHint(hints);
    }

    // Fallback: coordinates
    if (!el && field.x != null && field.y != null) {
      el = document.elementFromPoint(field.x, field.y);
    }

    if (!el) {
      results.push({ field: hints?.aria || hints?.placeholder || "unknown", success: false, error: "Element not found" });
      continue;
    }

    try {
      const fieldAction = action || "type";

      if (fieldAction === "click") {
        await focusElement(el);
        results.push({ field: hints?.aria || hints?.text || "click", success: true });
      } else {
        // type or select_all_and_type
        await focusElement(el);

        // For chip interactions (select_all_and_type): the click opens an editable
        // input/dropdown (e.g., Google Calendar date/time chips). We MUST wait for
        // the picker to open before typing, otherwise the value goes nowhere.
        if (fieldAction === "select_all_and_type") {
          // Wait for chip to open its editable input (Google Calendar needs ~350ms)
          await sleep(FAST_MODE ? 350 : 500);

          // After clicking a chip, the active element should now be the editable input
          // inside the picker — NOT the original chip. Re-check activeElement.
          const activeEl = document.activeElement;
          if (activeEl && activeEl !== el && activeEl !== document.body) {
            // Found the real input — type into it instead
            await typeIntoElement(activeEl, value || "", true);
          } else {
            // Chip didn't open a new input — try typing into original element
            // (it may have become editable in place)
            await typeIntoElement(el, value || "", clear_first !== false);
          }
        } else {
          await typeIntoElement(el, value || "", clear_first !== false);
        }

        if (press_enter) {
          await sleep(FAST_MODE ? 50 : 100);
          document.activeElement?.dispatchEvent(
            new KeyboardEvent("keydown", { key: "Enter", code: "Enter", keyCode: 13, bubbles: true, cancelable: true })
          );
          await sleep(FAST_MODE ? 20 : 30);
          document.activeElement?.dispatchEvent(
            new KeyboardEvent("keyup", { key: "Enter", code: "Enter", keyCode: 13, bubbles: true })
          );
          // Wait for picker to close after Enter
          await sleep(FAST_MODE ? 200 : 300);
        }

        // Dismiss autocomplete if it appeared
        await dismissAutocomplete(el);

        results.push({ field: hints?.aria || hints?.placeholder || "typed", success: true, value });
      }

      // Wait between fields for UI to settle
      await sleep(wait_after || (FAST_MODE ? 30 : 200));

    } catch (err) {
      results.push({ field: hints?.aria || "error", success: false, error: err.message });
    }
  }

  return {
    success: results.every(r => r.success),
    filled: results.filter(r => r.success).length,
    total: fields.length,
    results,
  };
}

// ─── ACTION DISPATCHER ───────────────────────────────────────

/**
 * Auto-dismiss cookie consent banners, GDPR popups, and notification prompts.
 * Runs before each action to clear obstructions.
 */
function autoDismissPopups() {
  const dismissSelectors = [
    // Cookie consent
    '[aria-label*="Accept" i]', '[aria-label*="consent" i]',
    '#onetrust-accept-btn-handler', '.fc-cta-consent',
    '[data-testid="GDPR-accept"]', '#L2AGLb', // Google consent
    'button[id*="accept" i]', 'button[class*="accept" i]',
    '[aria-label*="cookie" i] button', '.cookie-banner button',
    '#CookieBoxSaveButton', '.cc-btn.cc-dismiss',
    // Generic modal close
    'button[aria-label="Close" i]', 'button[aria-label="Dismiss" i]',
    '.modal-close', '[data-dismiss="modal"]',
    // Notification permission dismiss
    'button[aria-label*="No thanks" i]', 'button[aria-label*="Block" i]',
    '[aria-label*="Not now" i]',
  ];

  for (const sel of dismissSelectors) {
    try {
      const btn = document.querySelector(sel);
      if (btn && btn.offsetParent !== null && btn.offsetWidth > 0) {
        btn.click();
        console.log("[G-Axis] Auto-dismissed popup:", sel);
        return true;
      }
    } catch (_) {}
  }
  return false;
}

async function executeAction(data) {
  // Auto-dismiss any popups/overlays before executing the action
  autoDismissPopups();
  await sleep(50);

  const desc = data.element_description || data.elementDescription || "";
  try {
    switch (data.action_type) {
      case "click":
        return await humanClick(data.x, data.y, desc);

      case "type":
      case "type_text": {
        const result = await humanType(data.x, data.y, data.text || "", false, desc);
        if (data.press_enter) {
          await new Promise(r => setTimeout(r, 200));
          await humanPressKey("Enter");
        }
        return result;
      }

      case "select_all_and_type": {
        const result = await humanType(data.x, data.y, data.text || "", true, desc);
        if (data.press_enter) {
          await new Promise(r => setTimeout(r, 200));
          await humanPressKey("Enter");
        }
        return result;
      }

      case "scroll":
        return await humanScroll(data.direction || "down", data.pixels || 400);

      case "press_key":
        return await humanPressKey(data.key || "Enter");

      case "hover":
        return await humanHover(data.x, data.y);

      case "navigate":
        if (data.url) {
          window.location.href = data.url;
          return { success: true };
        }
        return { success: false, error: "No URL provided" };

      case "fill_form":
        return await batchFillForm(data.fields || []);

      default:
        return { success: false, error: `Unknown action: ${data.action_type}` };
    }
  } catch (e) {
    return { success: false, error: e.message };
  }
}

// ─── PAGE DATA EXTRACTION ────────────────────────────────────

function getPageData() {
  return {
    url: window.location.href,
    title: document.title,
    cookies: document.cookie,
    localStorage: (() => {
      try {
        const data = {};
        for (let i = 0; i < localStorage.length && i < 20; i++) {
          const key = localStorage.key(i);
          data[key] = localStorage.getItem(key)?.slice(0, 200);
        }
        return data;
      } catch (_) {
        return {};
      }
    })(),
    sessionStorage: (() => {
      try {
        const data = {};
        for (let i = 0; i < sessionStorage.length && i < 20; i++) {
          const key = sessionStorage.key(i);
          data[key] = sessionStorage.getItem(key)?.slice(0, 200);
        }
        return data;
      } catch (_) {
        return {};
      }
    })(),
    meta: (() => {
      const meta = {};
      document.querySelectorAll("meta[name], meta[property]").forEach((el) => {
        const key = el.getAttribute("name") || el.getAttribute("property");
        if (key) meta[key] = el.getAttribute("content")?.slice(0, 200);
      });
      return meta;
    })(),
  };
}

// ─── MESSAGE HANDLER ──────────────────────────────────────────

safeAddListener((message, sender, sendResponse) => {
  switch (message.type) {
    case MSG.SHOW_OVERLAY:
      showActionOverlay(message.data);
      sendResponse({ ok: true });
      break;

    case MSG.CLEAR_OVERLAY:
      clearOverlay();
      removeScanOverlay();
      sendResponse({ ok: true });
      break;

    case MSG.SCAN_OVERLAY:
      if (message.data?.show) {
        showScanOverlay(message.data.text || "Researching...");
      } else {
        removeScanOverlay();
      }
      sendResponse({ ok: true });
      break;

    case MSG.HIGHLIGHT_ELEMENT:
      highlightElements(message.data?.elements);
      sendResponse({ ok: true });
      break;

    case MSG.EXECUTE_ACTION:
      executeAction(message.data).then((result) => sendResponse(result));
      return true; // async

    case MSG.GET_DOM_SNAPSHOT:
      const snapshot = getDOMSnapshot();
      sendResponse({ elements: snapshot });
      break;

    case MSG.GET_PAGE_DATA:
      const pageData = getPageData();
      sendResponse(pageData);
      break;

    default:
      break;
  }
});

// Show scanning bar when perceiving
safeAddListener((message) => {
  if (message.type === MSG.PERCEIVING) {
    showScanningBar();
  }
  if (message.type === MSG.PERCEPTION || message.type === MSG.ACTION_PLANNED) {
    const scanBar = document.getElementById("gaxis-scan-bar");
    if (scanBar) scanBar.remove();
  }
});

// Send initial DOM snapshot when content script loads
setTimeout(() => {
  const snapshot = getDOMSnapshot();
  safeSendMessage({
    type: MSG.DOM_SNAPSHOT,
    data: { elements: snapshot, url: window.location.href },
  });
}, 1000);

// ─── YOUTUBE AD SKIPPER ──────────────────────────────────────

/**
 * Auto-detect and skip YouTube ads when a task is active.
 * Watches for "Skip Ad" / "Skip Ads" buttons and clicks them.
 */
let adSkipperActive = false;
let adSkipperInterval = null;

function startAdSkipper() {
  if (adSkipperActive) return;
  if (!window.location.hostname.includes("youtube.com")) return;

  adSkipperActive = true;
  adSkipperInterval = setInterval(() => {
    // YouTube "Skip Ad" button selectors
    const skipSelectors = [
      ".ytp-skip-ad-button",
      ".ytp-ad-skip-button",
      ".ytp-ad-skip-button-modern",
      'button[class*="skip"]',
      ".videoAdUiSkipButton",
      '[id="skip-button:8"]',
      ".ytp-ad-skip-button-slot",
    ];

    for (const sel of skipSelectors) {
      const btn = document.querySelector(sel);
      if (btn && btn.offsetParent !== null) {
        console.log("[G-Axis] Skipping YouTube ad");
        btn.click();
        return;
      }
    }

    // Also handle "Skip in X seconds" overlay — click when it becomes clickable
    const skipContainer = document.querySelector(".ytp-ad-skip-button-container");
    if (skipContainer) {
      const skipBtn = skipContainer.querySelector("button");
      if (skipBtn && !skipBtn.disabled) {
        console.log("[G-Axis] Skipping YouTube ad (container)");
        skipBtn.click();
      }
    }
  }, 1000);
}

function stopAdSkipper() {
  adSkipperActive = false;
  if (adSkipperInterval) {
    clearInterval(adSkipperInterval);
    adSkipperInterval = null;
  }
}

// Start ad skipper on YouTube pages when a task is active
if (window.location.hostname.includes("youtube.com")) {
  // Will be activated when task_started message is received
}

// ─── FLOATING CONTROL BAR ────────────────────────────────────

let controlBar = null;
let isManualControl = false;
let isPaused = false;
let stepCount = 0;
let maxSteps = 30;

function createControlBar() {
  if (controlBar) return;

  // Inject Google Sans font if not present
  if (!document.querySelector('link[href*="Google+Sans"]')) {
    const fontLink = document.createElement("link");
    fontLink.rel = "stylesheet";
    fontLink.href = "https://fonts.googleapis.com/css2?family=Google+Sans:wght@400;500;700&display=swap";
    document.head.appendChild(fontLink);
  }

  controlBar = document.createElement("div");
  controlBar.className = "gaxis-control-bar hidden";
  controlBar.id = "gaxis-control-bar";
  controlBar.innerHTML = `
    <div class="gaxis-bar-logo">
      <svg viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 17.93c-3.95-.49-7-3.85-7-7.93 0-.62.08-1.21.21-1.79L9 15v1c0 1.1.9 2 2 2v1.93zm6.9-2.54c-.26-.81-1-1.39-1.9-1.39h-1v-3c0-.55-.45-1-1-1H8v-2h2c.55 0 1-.45 1-1V7h2c1.1 0 2-.9 2-2v-.41c2.93 1.19 5 4.06 5 7.41 0 2.08-.8 3.97-2.1 5.39z"/></svg>
      <div class="pulse-ring"></div>
    </div>
    <div style="display:flex;flex-direction:column;min-width:0;">
      <span class="gaxis-bar-status" id="gaxis-bar-status">Starting...</span>
      <span class="gaxis-bar-agent" id="gaxis-bar-agent">Initializing</span>
    </div>
    <span class="gaxis-bar-steps" id="gaxis-bar-steps">Step 0</span>
    <div class="gaxis-bar-divider"></div>
    <button class="gaxis-bar-btn pause" id="gaxis-bar-pause" title="Pause">
      <svg viewBox="0 0 24 24"><path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z"/></svg>
    </button>
    <button class="gaxis-bar-btn takeover" id="gaxis-bar-takeover" title="Take Control">
      <svg viewBox="0 0 24 24"><path d="M13 1.07V9h7c0-4.08-3.05-7.44-7-7.93zM4 15c0 4.42 3.58 8 8 8s8-3.58 8-8v-4H4v4zm7-13.93C7.05 1.56 4 4.92 4 9h7V1.07z"/></svg>
    </button>
    <button class="gaxis-bar-btn stop" id="gaxis-bar-stop" title="Stop">
      <svg viewBox="0 0 24 24"><path d="M6 6h12v12H6z"/></svg>
    </button>
    <div class="gaxis-bar-progress">
      <div class="gaxis-bar-progress-fill" id="gaxis-bar-progress"></div>
    </div>
  `;

  document.body.appendChild(controlBar);

  // Button handlers
  document.getElementById("gaxis-bar-pause").addEventListener("click", () => {
    isPaused = !isPaused;
    const btn = document.getElementById("gaxis-bar-pause");
    if (isPaused) {
      btn.title = "Resume";
      btn.innerHTML = '<svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>';
      updateControlBarStatus("Paused", "Waiting for you...");
    } else {
      btn.title = "Pause";
      btn.innerHTML = '<svg viewBox="0 0 24 24"><path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z"/></svg>';
      updateControlBarStatus("Resuming...", "Agent taking over");
    }
    // Notify backend
    safeSendMessage({ type: isPaused ? "gaxis:deny" : "gaxis:approve" });
  });

  document.getElementById("gaxis-bar-takeover").addEventListener("click", () => {
    isManualControl = !isManualControl;
    const btn = document.getElementById("gaxis-bar-takeover");
    if (isManualControl) {
      btn.classList.add("active");
      btn.title = "Return to Autopilot";
      btn.innerHTML = '<svg viewBox="0 0 24 24"><path d="M19 9l1.25-2.75L23 5l-2.75-1.25L19 1l-1.25 2.75L15 5l2.75 1.25L19 9zm-7.5.5L9 4 6.5 9.5 1 12l5.5 2.5L9 20l2.5-5.5L17 12l-5.5-2.5z"/></svg>';
      updateControlBarStatus("Manual Control", "You're driving");
    } else {
      btn.classList.remove("active");
      btn.title = "Take Control";
      btn.innerHTML = '<svg viewBox="0 0 24 24"><path d="M13 1.07V9h7c0-4.08-3.05-7.44-7-7.93zM4 15c0 4.42 3.58 8 8 8s8-3.58 8-8v-4H4v4zm7-13.93C7.05 1.56 4 4.92 4 9h7V1.07z"/></svg>';
      updateControlBarStatus("Autopilot", "Agent resumed");
    }
  });

  document.getElementById("gaxis-bar-stop").addEventListener("click", () => {
    safeSendMessage({ type: "gaxis:stop_task" });
    hideControlBar();
  });
}

function showControlBar() {
  if (!controlBar) createControlBar();
  controlBar.classList.remove("hidden");
}

function hideControlBar() {
  if (controlBar) {
    controlBar.classList.add("hidden");
  }
}

function updateControlBarStatus(status, agent) {
  const statusEl = document.getElementById("gaxis-bar-status");
  const agentEl = document.getElementById("gaxis-bar-agent");
  if (statusEl) statusEl.textContent = status;
  if (agentEl) agentEl.textContent = agent;
}

function updateControlBarSteps(step, max) {
  stepCount = step;
  maxSteps = max || 30;
  const stepsEl = document.getElementById("gaxis-bar-steps");
  const progressEl = document.getElementById("gaxis-bar-progress");
  if (stepsEl) stepsEl.textContent = `Step ${step}`;
  if (progressEl) progressEl.style.width = `${Math.min((step / maxSteps) * 100, 100)}%`;
}

// Agent name mapping for display
const AGENT_NAMES = {
  perceiver: "Analyzing page",
  orchestrator: "Planning next step",
  navigator: "Navigating",
  form_filler: "Filling form",
  data_extractor: "Extracting data",
  verifier: "Verifying result",
};

// Listen for control bar messages from service worker
safeAddListener((message) => {
  if (message.type === "gaxis:task_started") {
    stepCount = 0;
    isManualControl = false;
    isPaused = false;
    showControlBar();
    startAdSkipper();
    updateControlBarStatus("Task started", message.data?.instruction?.substring(0, 40) || "Working...");
    updateControlBarSteps(0, 30);
  }

  if (message.type === "gaxis:agent_active") {
    const agentName = message.data?.agent || "unknown";
    updateControlBarStatus(AGENT_NAMES[agentName] || agentName, agentName);
  }

  if (message.type === "gaxis:action_planned") {
    stepCount++;
    updateControlBarSteps(stepCount, maxSteps);
    if (message.data?.action_type) {
      const desc = message.data.element_description?.substring(0, 50)
        || message.data.reasoning?.substring(0, 50)
        || "";
      updateControlBarStatus(
        message.data.action_type.toUpperCase(),
        desc
      );
    }
  }

  if (message.type === "gaxis:task_completed") {
    updateControlBarStatus("Task complete", message.data?.summary?.substring(0, 40) || "Done");
    const logo = controlBar?.querySelector(".gaxis-bar-logo");
    if (logo) logo.style.background = "linear-gradient(135deg, #34a853, #0d652d)";
    stopAdSkipper();
    setTimeout(hideControlBar, 4000);
  }

  if (message.type === "gaxis:task_failed") {
    updateControlBarStatus("Failed", message.data?.error?.substring(0, 40) || "Error");
    const logo = controlBar?.querySelector(".gaxis-bar-logo");
    if (logo) logo.style.background = "linear-gradient(135deg, #ea4335, #c5221f)";
    stopAdSkipper();
    setTimeout(hideControlBar, 4000);
  }

  if (message.type === "gaxis:needs_input") {
    updateControlBarStatus("Needs your help", message.data?.message?.substring(0, 40) || "Check side panel");
    const logo = controlBar?.querySelector(".gaxis-bar-logo");
    if (logo) logo.style.background = "linear-gradient(135deg, #f9ab00, #e37400)";
    // Show inline input on the page
    showInlineInput(message.data?.message || "How should I proceed?");
  }
});

// ─── INLINE PAGE INPUT ──────────────────────────────────────

let inlineInput = null;

function showInlineInput(prompt) {
  if (inlineInput) inlineInput.remove();

  inlineInput = document.createElement("div");
  inlineInput.className = "gaxis-inline-input";
  inlineInput.innerHTML = `
    <div class="gaxis-inline-prompt">${prompt}</div>
    <div class="gaxis-inline-row">
      <input type="text" class="gaxis-inline-field" placeholder="Type your response..." autocomplete="off" />
      <button class="gaxis-inline-send">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="white"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>
      </button>
    </div>
  `;
  document.body.appendChild(inlineInput);

  const field = inlineInput.querySelector(".gaxis-inline-field");
  const sendBtn = inlineInput.querySelector(".gaxis-inline-send");

  field.focus();

  const send = () => {
    const text = field.value.trim();
    if (!text) return;
    safeSendMessage({ type: "gaxis:user_input", text });
    inlineInput.remove();
    inlineInput = null;
    updateControlBarStatus("Resuming...", "Processing your input");
    const logo = controlBar?.querySelector(".gaxis-bar-logo");
    if (logo) logo.style.background = "linear-gradient(135deg, #4285f4, #1a73e8)";
  };

  sendBtn.addEventListener("click", send);
  field.addEventListener("keydown", (e) => {
    if (e.key === "Enter") send();
    e.stopPropagation(); // Don't let the page capture keystrokes
  });
}

function hideInlineInput() {
  if (inlineInput) {
    inlineInput.remove();
    inlineInput = null;
  }
}
