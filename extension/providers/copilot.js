/**
 * Microsoft 365 Copilot Provider Adapter
 *
 * Detects Copilot chat in Microsoft 365 (work/school) and Bing Chat Enterprise.
 * URL patterns: *.cloud.microsoft, copilot.microsoft.com, bing.com/chat
 *
 * NOTE: Copilot's DOM is complex and frequently updated. The selectors below
 * are best-effort and may need recalibration if Microsoft changes their UI.
 */
registerProvider({
  id: "copilot",
  name: "Microsoft Copilot",
  urlPattern: "*.cloud.microsoft, copilot.microsoft.com, bing.com/chat",

  matches(url) {
    return (
      url.hostname.endsWith(".cloud.microsoft") ||
      url.hostname === "copilot.microsoft.com" ||
      (url.hostname === "www.bing.com" && url.pathname.startsWith("/chat"))
    );
  },

  /** Candidate selectors for the chat input — exposed for diagnostics. */
  _inputCandidates: [
    'div[contenteditable="true"][aria-label*="message" i]',
    'div[contenteditable="true"][aria-label*="Ask" i]',
    'div[contenteditable="true"][aria-label*="Type" i]',
    'textarea[aria-label*="message" i]',
    'textarea[aria-label*="Ask" i]',
    'textarea[placeholder*="Ask" i]',
    'textarea[placeholder*="Message" i]',
    'textarea[placeholder*="Type" i]',
    '#userInput',
    '[data-id="chat-input"]',
    'div[contenteditable="true"]', // fallback
  ],

  /** Candidate selectors for the submit button — exposed for diagnostics. */
  _submitCandidates: [
    'button[aria-label="Submit"]',
    'button[aria-label="Send"]',
    'button[title="Submit"]',
    'button[title="Send"]',
    'button.send-button',
    'button[data-testid="send-button"]',
  ],

  getInputSelector() {
    for (const sel of this._inputCandidates) {
      const el = document.querySelector(sel);
      if (el) return sel;
    }
    return null;
  },

  getSubmitSelector() {
    for (const sel of this._submitCandidates) {
      const el = document.querySelector(sel);
      if (el) return sel;
    }
    return null;
  },

  /**
   * Run diagnostics and log which selectors matched.
   */
  diagnose() {
    const inputResults = this._inputCandidates.map(sel => ({
      selector: sel,
      found: !!document.querySelector(sel),
    }));
    const submitResults = this._submitCandidates.map(sel => ({
      selector: sel,
      found: !!document.querySelector(sel),
    }));
    const inputMatch = inputResults.find(r => r.found);
    const submitMatch = submitResults.find(r => r.found);

    console.group("%c[RAG] Copilot DOM Diagnostics", "color: #60a5fa; font-weight: bold");
    console.log("Input candidates:", inputResults);
    console.log("Submit candidates:", submitResults);
    console.log("Matched input:", inputMatch?.selector || "NONE ❌");
    console.log("Matched submit:", submitMatch?.selector || "NONE ❌");
    console.groupEnd();

    return {
      inputSelector: inputMatch?.selector || null,
      inputCandidates: inputResults,
      submitSelector: submitMatch?.selector || null,
      submitCandidates: submitResults,
    };
  },

  formatPrompt(originalQuestion, evidence) {
    const { results, total_chunks_searched, folders } = evidence;

    // Catalog listing — enumerate folders/projects
    if (folders && folders.length) {
      let ctx = "## PROJECT FOLDER CATALOG (use only this for factual claims)\n\n";
      folders.forEach((f, i) => {
        ctx += `${i + 1}. ${f.folder} — ${f.document_count} document(s)`;
        if (f.sources && f.sources.length) ctx += ` (source: ${f.sources.join(", ")})`;
        ctx += "\n";
      });
      ctx += "\nAnswer the question by listing these folders from the evidence. Do not invent folders or files.";
      return `${ctx}\n\n---\n\nUser question: ${originalQuestion}`;
    }

    if (!results || results.length === 0) {
      return null;
    }

    let context = "## PROJECT EVIDENCE (use only this for factual claims)\n\n";
    results.forEach((r, i) => {
      context += `### Source ${i + 1}: ${r.document_name} (${Math.round(r.relevance_score * 100)}% relevance)\n`;
      context += `${r.chunk_content.substring(0, 500)}\n`;

      const meta = [];
      if (r.project_names?.length) meta.push(`Projects: ${r.project_names.join(", ")}`);
      if (r.requirement_ids?.length) meta.push(`Requirements: ${r.requirement_ids.map(id => "REQ-" + id).join(", ")}`);
      if (r.cr_numbers?.length) meta.push(`Change Requests: ${r.cr_numbers.map(c => "CR-" + c).join(", ")}`);
      if (meta.length) context += `Metadata: ${meta.join(" | ")}\n`;
      context += "\n";
    });

    context += `\n---\nSearched ${total_chunks_searched} document chunks.\n`;
    context +=
      "Answer the question using ONLY the evidence above. Cite source documents. If evidence is insufficient, say so.";

    return `${context}\n\n---\n\nUser question: ${originalQuestion}`;
  },
});
