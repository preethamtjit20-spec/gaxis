/**
 * Google Docs API Helper — creates well-formatted documents.
 *
 * Strategy: Two-phase approach to avoid index calculation errors.
 *   Phase 1: Insert all text content at once (headings, paragraphs, bullets)
 *   Phase 2: Apply formatting (heading styles, bold, colors, bullets)
 *   Phase 3: Insert tables separately (requires fresh index reads)
 */

const DOCS_API = "https://docs.googleapis.com/v1/documents";

async function getAuthToken() {
  return new Promise((resolve, reject) => {
    chrome.identity.getAuthToken({ interactive: true }, (token) => {
      if (chrome.runtime.lastError) {
        reject(new Error(chrome.runtime.lastError.message));
      } else {
        resolve(token);
      }
    });
  });
}

async function apiCall(method, url, body) {
  const token = await getAuthToken();
  const opts = {
    method,
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
  };
  if (body) opts.body = JSON.stringify(body);
  const res = await fetch(url, opts);
  if (!res.ok) {
    const err = await res.text();
    throw new Error(`Docs API ${method} ${res.status}: ${err}`);
  }
  return res.json();
}

async function createEmptyDoc(title) {
  const doc = await apiCall("POST", DOCS_API, { title });
  return {
    documentId: doc.documentId,
    url: `https://docs.google.com/document/d/${doc.documentId}/edit`,
  };
}

async function getDoc(documentId) {
  return apiCall("GET", `${DOCS_API}/${documentId}`, null);
}

async function batchUpdate(documentId, requests) {
  if (!requests.length) return;
  return apiCall("POST", `${DOCS_API}/${documentId}:batchUpdate`, { requests });
}

/**
 * Build a flat text string and a formatting map from blocks.
 * This avoids complex index math — we insert all text first,
 * then apply formatting based on known offsets.
 */
function buildTextAndFormatting(blocks) {
  let text = "";
  const formats = []; // { start, end, style }
  const tablePositions = []; // { insertAfterText: "...", headers, rows }

  for (const block of blocks) {
    const start = text.length;

    switch (block.type) {
      case "heading1":
      case "heading2":
      case "heading3": {
        const line = block.text + "\n";
        text += line;
        const style = block.type === "heading1" ? "HEADING_1"
          : block.type === "heading2" ? "HEADING_2" : "HEADING_3";
        formats.push({ start, end: start + line.length, type: "heading", style });
        break;
      }

      case "paragraph": {
        text += block.text + "\n\n";
        break;
      }

      case "bullet": {
        const items = block.items || [];
        for (const item of items) {
          const itemStart = text.length;
          const line = item + "\n";
          text += line;
          formats.push({ start: itemStart, end: itemStart + line.length, type: "bullet" });
        }
        text += "\n";
        break;
      }

      case "checklist": {
        const items = block.items || [];
        for (const item of items) {
          text += "☐ " + item + "\n";
        }
        text += "\n";
        break;
      }

      case "table": {
        // Insert a placeholder marker, we'll replace with actual table later
        const marker = `[TABLE_${tablePositions.length}]\n\n`;
        text += marker;
        tablePositions.push({
          marker,
          markerStart: start,
          headers: block.headers || [],
          rows: block.rows || [],
        });
        break;
      }

      case "callout": {
        const prefix = (block.prefix || "TIP") + ": ";
        const body = block.text + "\n\n";
        text += prefix + body;
        formats.push({ start, end: start + prefix.length, type: "bold" });
        const color = block.prefix === "WARNING"
          ? { red: 0.9, green: 0.2, blue: 0.2 }
          : block.prefix === "NOTE"
          ? { red: 0.2, green: 0.4, blue: 0.9 }
          : { red: 0.1, green: 0.6, blue: 0.3 };
        formats.push({ start, end: start + prefix.length, type: "color", color });
        break;
      }

      case "toc": {
        const line = "Table of Contents\n\n";
        text += line;
        formats.push({ start, end: start + "Table of Contents\n".length, type: "heading", style: "HEADING_1" });
        break;
      }

      case "divider": {
        const line = "─".repeat(50) + "\n\n";
        text += line;
        formats.push({
          start, end: start + 50, type: "color",
          color: { red: 0.7, green: 0.7, blue: 0.7 },
        });
        break;
      }

      default: {
        text += (block.text || "") + "\n\n";
      }
    }
  }

  return { text, formats, tablePositions };
}

/**
 * Create a fully formatted Google Doc from structured content blocks.
 */
async function createFormattedDoc(title, blocks) {
  // Step 1: Create empty doc
  const { documentId, url } = await createEmptyDoc(title);
  console.log("[G-Axis Docs] Created doc:", documentId);

  // Step 2: Build text and formatting info
  const { text, formats, tablePositions } = buildTextAndFormatting(blocks);

  if (!text.trim()) {
    console.log("[G-Axis Docs] No content to insert");
    return { url, documentId };
  }

  // Step 3: Insert all text at once (index 1, after the implicit empty paragraph)
  const baseIndex = 1;
  await batchUpdate(documentId, [
    { insertText: { location: { index: baseIndex }, text } },
  ]);
  console.log(`[G-Axis Docs] Inserted ${text.length} chars`);

  // Step 4: Apply formatting (headings, bold, colors, bullets)
  const formatRequests = [];
  for (const fmt of formats) {
    const start = baseIndex + fmt.start;
    const end = baseIndex + fmt.end;

    switch (fmt.type) {
      case "heading":
        formatRequests.push({
          updateParagraphStyle: {
            range: { startIndex: start, endIndex: end },
            paragraphStyle: { namedStyleType: fmt.style },
            fields: "namedStyleType",
          },
        });
        break;

      case "bullet":
        formatRequests.push({
          createParagraphBullets: {
            range: { startIndex: start, endIndex: end },
            bulletPreset: "BULLET_DISC_CIRCLE_SQUARE",
          },
        });
        break;

      case "bold":
        formatRequests.push({
          updateTextStyle: {
            range: { startIndex: start, endIndex: end },
            textStyle: { bold: true },
            fields: "bold",
          },
        });
        break;

      case "color":
        formatRequests.push({
          updateTextStyle: {
            range: { startIndex: start, endIndex: end },
            textStyle: {
              foregroundColor: { color: { rgbColor: fmt.color } },
            },
            fields: "foregroundColor",
          },
        });
        break;
    }
  }

  if (formatRequests.length > 0) {
    try {
      await batchUpdate(documentId, formatRequests);
      console.log(`[G-Axis Docs] Applied ${formatRequests.length} format ops`);
    } catch (err) {
      console.error("[G-Axis Docs] Format error (non-fatal):", err.message);
    }
  }

  // Step 5: Replace table placeholders with actual tables
  // Tables need special handling — we read the doc to find marker positions,
  // delete the marker text, and insert a table at that position
  if (tablePositions.length > 0) {
    try {
      // Process tables in REVERSE order so indices don't shift
      for (let t = tablePositions.length - 1; t >= 0; t--) {
        const tbl = tablePositions[t];
        const allRows = tbl.headers.length ? [tbl.headers, ...tbl.rows] : tbl.rows;
        const numRows = allRows.length;
        const numCols = allRows[0]?.length || 2;

        if (numRows === 0) continue;

        // Read fresh doc to find marker position
        const freshDoc = await getDoc(documentId);
        const body = freshDoc.body?.content || [];
        let markerIndex = -1;
        let markerEndIndex = -1;

        for (const el of body) {
          if (el.paragraph) {
            const paraText = (el.paragraph.elements || [])
              .map((e) => e.textRun?.content || "")
              .join("");
            if (paraText.includes(`[TABLE_${t}]`)) {
              markerIndex = el.startIndex;
              markerEndIndex = el.endIndex;
              break;
            }
          }
        }

        if (markerIndex < 0) continue;

        // Delete marker text and insert table
        const tableRequests = [
          {
            deleteContentRange: {
              range: { startIndex: markerIndex, endIndex: markerEndIndex },
            },
          },
          {
            insertTable: {
              rows: numRows,
              columns: numCols,
              location: { index: markerIndex },
            },
          },
        ];

        await batchUpdate(documentId, tableRequests);

        // Now read doc again to find table cell positions and fill content
        const docWithTable = await getDoc(documentId);
        const tableEl = (docWithTable.body?.content || []).find(
          (el) => el.table && el.startIndex >= markerIndex
        );

        if (tableEl && tableEl.table) {
          const cellRequests = [];
          const tableRows = tableEl.table.tableRows || [];

          for (let r = 0; r < Math.min(tableRows.length, allRows.length); r++) {
            const cells = tableRows[r].tableCells || [];
            for (let c = 0; c < Math.min(cells.length, numCols); c++) {
              const cellContent = cells[c].content || [];
              if (cellContent.length > 0) {
                const cellIndex = cellContent[0].startIndex;
                const cellText = allRows[r][c] || "";
                if (cellText) {
                  cellRequests.push({
                    insertText: {
                      location: { index: cellIndex },
                      text: cellText,
                    },
                  });
                  // Bold header row
                  if (r === 0 && tbl.headers.length) {
                    cellRequests.push({
                      updateTextStyle: {
                        range: {
                          startIndex: cellIndex,
                          endIndex: cellIndex + cellText.length,
                        },
                        textStyle: { bold: true },
                        fields: "bold",
                      },
                    });
                  }
                }
              }
            }
          }

          if (cellRequests.length > 0) {
            // Must process cells in REVERSE order (highest index first)
            cellRequests.sort((a, b) => {
              const idxA = a.insertText?.location?.index || a.updateTextStyle?.range?.startIndex || 0;
              const idxB = b.insertText?.location?.index || b.updateTextStyle?.range?.startIndex || 0;
              return idxB - idxA;
            });
            await batchUpdate(documentId, cellRequests);
          }
        }

        console.log(`[G-Axis Docs] Table ${t + 1} inserted with ${numRows}x${numCols} cells`);
      }
    } catch (err) {
      console.error("[G-Axis Docs] Table insertion error (non-fatal):", err.message);
    }
  }

  console.log("[G-Axis Docs] Document complete:", url);
  return { url, documentId };
}

export { createFormattedDoc, getAuthToken };
