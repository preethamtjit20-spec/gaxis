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
  GET_PAGE_DATA: "gaxis:get_page_data",
};

let overlayContainer = null;
let mutationBuffer = [];
let mutationFlushTimer = null;

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
    "[onclick]", "[tabindex]",
    'label[for]', '[contenteditable="true"]',
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

// ─── MUTATION OBSERVER ────────────────────────────────────────

/**
 * Watch for DOM changes — detects dynamic content loading,
 * popup appearances, form validation errors, etc.
 */
const observer = new MutationObserver((mutations) => {
  const significant = mutations.filter((m) => {
    // Ignore our own overlay changes
    if (m.target.id && m.target.id.startsWith("gaxis-")) return false;
    if (m.target.closest && m.target.closest("#gaxis-overlay-root")) return false;
    return true;
  });

  if (significant.length === 0) return;

  const changes = significant.slice(0, 10).map((m) => ({
    type: m.type,
    target: describeElement(m.target),
    addedNodes: m.addedNodes.length,
    removedNodes: m.removedNodes.length,
    attributeName: m.attributeName || null,
  }));

  mutationBuffer.push(...changes);

  // Flush buffered mutations every 500ms to avoid flooding
  if (!mutationFlushTimer) {
    mutationFlushTimer = setTimeout(() => {
      if (mutationBuffer.length > 0) {
        chrome.runtime.sendMessage({
          type: MSG.DOM_CHANGED,
          data: {
            changes: mutationBuffer.slice(0, 20),
            timestamp: Date.now(),
            url: window.location.href,
          },
        }).catch(() => {});
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

// ─── HUMAN-LIKE ACTION EXECUTION ─────────────────────────────

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function randomDelay(min = 30, max = 100) {
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
    while (parent && depth < 5) {
      const ptag = parent.tagName.toLowerCase();
      if (["a", "button"].includes(ptag) || parent.getAttribute("role") === "button") {
        // Found interactive parent — use its center instead
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
  const path = generateCursorPath(cursorX, cursorY, targetX, targetY);

  for (const point of path) {
    const target = document.elementFromPoint(point.x, point.y);
    if (target) {
      target.dispatchEvent(new MouseEvent("mousemove", {
        bubbles: true, clientX: point.x, clientY: point.y, view: window,
      }));
    }
    await sleep(randomDelay(8, 18)); // ~60-120fps movement
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

  // Step 4: Full event sequence
  const opts = { bubbles: true, cancelable: true, clientX: finalX, clientY: finalY, view: window };

  await sleep(randomDelay(30, 60));
  target.dispatchEvent(new MouseEvent("mouseover", opts));
  target.dispatchEvent(new MouseEvent("mouseenter", { ...opts, bubbles: false }));

  await sleep(randomDelay(20, 40));
  target.dispatchEvent(new MouseEvent("mousedown", { ...opts, button: 0 }));

  await sleep(randomDelay(50, 100));
  target.dispatchEvent(new MouseEvent("mouseup", { ...opts, button: 0 }));
  target.dispatchEvent(new MouseEvent("click", { ...opts, button: 0 }));

  // Native click fallback for React/Vue apps
  try { target.click(); } catch (_) {}

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

  // Type character by character
  if (target.value !== undefined) {
    for (const char of text) {
      const delay = randomDelay(30, 80); // Human typing: 30-80ms per char
      await sleep(delay);

      target.dispatchEvent(new KeyboardEvent("keydown", { key: char, code: `Key${char.toUpperCase()}`, bubbles: true }));
      target.value += char;
      target.dispatchEvent(new Event("input", { bubbles: true }));
      target.dispatchEvent(new KeyboardEvent("keypress", { key: char, bubbles: true }));
      target.dispatchEvent(new KeyboardEvent("keyup", { key: char, bubbles: true }));
    }
    target.dispatchEvent(new Event("change", { bubbles: true }));
  } else {
    // ContentEditable
    for (const char of text) {
      await sleep(randomDelay(30, 80));
      document.execCommand("insertText", false, char);
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
 * Press a keyboard key with proper event sequence
 */
async function humanPressKey(key) {
  const target = document.activeElement || document.body;

  await sleep(randomDelay(20, 50));
  target.dispatchEvent(new KeyboardEvent("keydown", { key, code: key, bubbles: true, cancelable: true }));

  await sleep(randomDelay(30, 70));
  target.dispatchEvent(new KeyboardEvent("keyup", { key, code: key, bubbles: true }));

  // Special handling for Enter in forms
  if (key === "Enter" && target.form) {
    target.form.dispatchEvent(new Event("submit", { bubbles: true }));
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

// ─── ACTION DISPATCHER ───────────────────────────────────────

async function executeAction(data) {
  const desc = data.element_description || data.elementDescription || "";
  try {
    switch (data.action_type) {
      case "click":
        return await humanClick(data.x, data.y, desc);

      case "type":
      case "type_text":
        return await humanType(data.x, data.y, data.text || "", false, desc);

      case "select_all_and_type":
        return await humanType(data.x, data.y, data.text || "", true, desc);

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
chrome.runtime.onMessage.addListener((message) => {
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
  chrome.runtime.sendMessage({
    type: MSG.DOM_SNAPSHOT,
    data: { elements: snapshot, url: window.location.href },
  }).catch(() => {});
}, 1000);
