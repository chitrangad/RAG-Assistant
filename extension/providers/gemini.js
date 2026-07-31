/**
 * Google Gemini Provider Adapter
 *
 * Detects Gemini chat at gemini.google.com.
 */
registerProvider({
  id: "gemini",
  name: "Google Gemini",
  urlPattern: "gemini.google.com",

  matches(url) {
    return url.hostname === "gemini.google.com";
  },

  _inputCandidates: [
    // Gemini-specific: rich-textarea > div[contenteditable] with aria-label
    'div[contenteditable="true"][aria-label="Enter a prompt for Gemini"]',
    'rich-textarea div[contenteditable="true"]',
    'div[contenteditable="true"][aria-label*="prompt" i]',
    'div[contenteditable="true"][aria-label*="message" i]',
    'div[contenteditable="true"]',
    // Fallback: textarea (older versions)
    'textarea[aria-label*="message" i]',
    'textarea[placeholder*="Enter" i]',
    'textarea',
  ],

  _submitCandidates: [
    // Gemini-specific submit button
    'button[aria-label="Send message"]',
    'button[aria-label="Send"]',
    'button[aria-label="Submit"]',
    'button[type="submit"]',
    'button.send-button',
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

    console.group("%c[RAG] Gemini DOM Diagnostics", "color: #60a5fa; font-weight: bold");
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

    let context = "Here is relevant evidence from your project documents:\n\n";
    results.forEach((r, i) => {
      context += `[Document: ${r.document_name} | Relevance: ${Math.round(r.relevance_score * 100)}%]\n`;
      context += `${r.chunk_content.substring(0, 500)}\n`;

      const meta = [];
      if (r.project_names?.length) meta.push(`Projects: ${r.project_names.join(", ")}`);
      if (r.requirement_ids?.length) meta.push(`REQs: ${r.requirement_ids.map(id => "REQ-" + id).join(", ")}`);
      if (r.cr_numbers?.length) meta.push(`CRs: ${r.cr_numbers.map(c => "CR-" + c).join(", ")}`);
      if (meta.length) context += `[${meta.join(" | ")}]\n`;
      context += "\n";
    });

    context += `\n(Searched ${total_chunks_searched} chunks.)\n\n`;
    context += "Using ONLY the evidence above, answer this question. Cite sources. If the evidence is insufficient, state that clearly.\n\n";
    context += originalQuestion;
    return context;
  },
});
