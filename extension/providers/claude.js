/**
 * Claude Provider Adapter
 *
 * Detects Claude at claude.ai.
 */
registerProvider({
  id: "claude",
  name: "Anthropic Claude",
  urlPattern: "claude.ai",

  matches(url) {
    return url.hostname === "claude.ai";
  },

  _inputCandidates: [
    'div[contenteditable="true"][aria-label*="message" i]',
    'div[contenteditable="true"][aria-label*="Write" i]',
    'div[contenteditable="true"][aria-label*="prompt" i]',
    'div[contenteditable="true"]',
    'textarea[aria-label*="message" i]',
    'textarea[placeholder*="Message" i]',
    'textarea[placeholder*="Reply" i]',
    'textarea',
  ],

  _submitCandidates: [
    'button[aria-label="Send Message"]',
    'button[aria-label="Send"]',
    'button[aria-label="Submit"]',
    'button[type="submit"]',
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

  diagnose() {
    const inputResults = this._inputCandidates.map(sel => ({
      selector: sel, found: !!document.querySelector(sel),
    }));
    const submitResults = this._submitCandidates.map(sel => ({
      selector: sel, found: !!document.querySelector(sel),
    }));
    const inputMatch = inputResults.find(r => r.found);
    const submitMatch = submitResults.find(r => r.found);

    console.group("%c[RAG] Claude DOM Diagnostics", "color: #60a5fa; font-weight: bold");
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
      let ctx = "Here is the catalog of folders/projects in the document repository:\n\n";
      folders.forEach((f, i) => {
        ctx += `${i + 1}. ${f.folder} — ${f.document_count} document(s)`;
        if (f.sources && f.sources.length) ctx += ` (source: ${f.sources.join(", ")})`;
        ctx += "\n";
      });
      ctx += "\nAnswer the question by listing these folders from the evidence. Do not invent folders or files.\n\n";
      return ctx + originalQuestion;
    }

    if (!results || results.length === 0) return null;

    let context = "You are a project knowledge assistant. Answer using ONLY the evidence below.\n\n";
    results.forEach((r, i) => {
      context += `<document name="${r.document_name}" relevance="${Math.round(r.relevance_score * 100)}%">\n`;
      context += `${r.chunk_content.substring(0, 500)}\n`;

      const meta = [];
      if (r.project_names?.length) meta.push(`Projects: ${r.project_names.join(", ")}`);
      if (r.requirement_ids?.length) meta.push(`Requirements: ${r.requirement_ids.map(id => "REQ-" + id).join(", ")}`);
      if (r.cr_numbers?.length) meta.push(`Change Requests: ${r.cr_numbers.map(c => "CR-" + c).join(", ")}`);
      if (meta.length) context += `Metadata: ${meta.join(" | ")}`;
      context += `\n</document>\n\n`;
    });

    context += `Searched ${total_chunks_searched} document chunks.\n\n`;
    context += "Important: Only use the evidence above. Cite documents. If insufficient, say so.\n\n";
    context += `Question: ${originalQuestion}`;
    return context;
  },
});
