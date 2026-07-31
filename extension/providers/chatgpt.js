/**
 * ChatGPT Provider Adapter
 *
 * Detects ChatGPT at chat.openai.com or chatgpt.com.
 */
registerProvider({
  id: "chatgpt",
  name: "ChatGPT",
  urlPattern: "chat.openai.com, chatgpt.com",

  matches(url) {
    return url.hostname === "chat.openai.com" || url.hostname === "chatgpt.com";
  },

  _inputCandidates: [
    '#prompt-textarea',
    'textarea[placeholder*="Message" i]',
    'textarea[placeholder*="Ask" i]',
    'textarea[data-id]',
    'div[contenteditable="true"][aria-label*="message" i]',
    'div[contenteditable="true"]',
    'textarea',
  ],

  _submitCandidates: [
    'button[data-testid="send-button"]',
    'button[aria-label="Send prompt"]',
    'button[aria-label="Send"]',
    'button.absolute.bottom-3',
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

    console.group("%c[RAG] ChatGPT DOM Diagnostics", "color: #60a5fa; font-weight: bold");
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
      ctx += "\nAnswer the question by listing these folders from the evidence. Do not invent folders or files.";
      ctx += `\n\nQuestion: ${originalQuestion}`;
      return ctx;
    }

    if (!results || results.length === 0) return null;

    let context = "You are a project knowledge assistant. Use ONLY the evidence below to answer.\n\n";
    context += "=== EVIDENCE ===\n";
    results.forEach((r, i) => {
      context += `\n[${i + 1}] ${r.document_name} (${Math.round(r.relevance_score * 100)}% match)\n`;
      context += `${r.chunk_content.substring(0, 500)}\n`;

      const meta = [];
      if (r.project_names?.length) meta.push(`Projects: ${r.project_names.join(", ")}`);
      if (r.requirement_ids?.length) meta.push(`Requirements: ${r.requirement_ids.map(id => "REQ-" + id).join(", ")}`);
      if (r.cr_numbers?.length) meta.push(`Change Requests: ${r.cr_numbers.map(c => "CR-" + c).join(", ")}`);
      if (meta.length) context += `[${meta.join(" | ")}]\n`;
    });

    context += `\n=== END EVIDENCE (${total_chunks_searched} chunks searched) ===\n\n`;
    context += "Rules:\n";
    context += "- Answer ONLY from the evidence above. Do not fabricate.\n";
    context += "- Cite document names for each claim.\n";
    context += '- If evidence is insufficient, say "I do not have enough evidence to answer this question."\n';
    context += `\nQuestion: ${originalQuestion}`;
    return context;
  },
});
