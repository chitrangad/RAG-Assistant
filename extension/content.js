/**
 * Content script — injected into supported AI chat pages.
 * Detects the provider, intercepts queries, and injects RAG evidence.
 */

(function () {
  "use strict";

  // ─── Configuration ────────────────────────────────────────────────────────

  let BACKEND_URL = "http://localhost:8000";
  let MIN_RELEVANCE_THRESHOLD = 0.3; // only inject if at least one result >= this

  // ─── State ────────────────────────────────────────────────────────────────

  let provider = null;
  let processingQuery = false;
  let injectingPrompt = false; // true when bypassing interceptor to let augmented prompt through

  // ─── Load settings from extension storage ─────────────────────────────────

  let enabledProviders = {}; // per-provider toggles from popup

  chrome.storage.sync.get(["backendUrl", "enabledProviders"], (settings) => {
    if (settings.backendUrl) BACKEND_URL = settings.backendUrl;
    if (settings.enabledProviders) enabledProviders = settings.enabledProviders;

    init();
  });

  async function init() {
    // Detect the provider based on URL
    provider = detectProvider(window.location);
    if (!provider) return;

    // Check if this provider is disabled in settings (default: enabled)
    if (enabledProviders[provider.id] === false) {
      console.log(`%c[RAG] ⏸️ Provider ${provider.name} is disabled in settings`, "color: #64748b");
      return;
    }

    // Run diagnostics: find both input and submit selectors
    const diag = provider.diagnose ? provider.diagnose() : diagnoseSelectors();

    if (!diag.inputSelector) {
      console.warn(
        `%c[RAG] ⚠️ No input element found for ${provider.name}`,
        "color: #f59e0b; font-weight: bold"
      );
      console.log("%c[RAG] Selectors tried:", "color: #94a3b8", diag.inputCandidates);
      console.log(
        "%c[RAG] 💡 To calibrate: paste the diagnose script into DevTools Console. See extension/README.md",
        "color: #60a5fa"
      );
      return;
    }

    console.log(
      `%c[RAG] ✅ Provider: ${provider.name} | Input: \`${diag.inputSelector}\` | Submit: \`${diag.submitSelector || "N/A"}\``,
      "color: #22c55e"
    );

    // Create the floating badge
    createBadge();

    // Wait for input to be available, then attach interceptors
    waitForElement(diag.inputSelector, 10000, (inputEl) => {
      attachInterceptor(inputEl);
      observeInputChanges(diag.inputSelector);
    });
  }

  // ─── Diagnose selectors (used when provider lacks diagnose()) ────────────

  function diagnoseSelectors() {
    const inputSelector = provider.getInputSelector();
    const inputCandidates = provider._inputCandidates || [];
    const submitSelector = provider.getSubmitSelector();
    const submitCandidates = provider._submitCandidates || [];
    return { inputSelector, inputCandidates, submitSelector, submitCandidates };
  }

  // ─── Badge ────────────────────────────────────────────────────────────────

  function createBadge() {
    const badge = document.createElement("div");
    badge.id = "rag-extension-badge";
    badge.innerHTML = `
      <span class="rag-badge-dot"></span>
      <span class="rag-badge-text">RAG Ready</span>
    `;
    badge.title = `Project Knowledge Assistant — ${provider.name}`;
    document.body.appendChild(badge);
  }

  function updateBadge(status, text) {
    const badge = document.getElementById("rag-extension-badge");
    if (!badge) return;
    const dot = badge.querySelector(".rag-badge-dot");
    const label = badge.querySelector(".rag-badge-text");
    if (dot) dot.className = "rag-badge-dot rag-badge-" + status;
    if (label && text) label.textContent = text;
  }

  // ─── Input Interception ───────────────────────────────────────────────────

  let lastProcessedQuery = "";
  let lastProcessedTime = 0;

  function attachInterceptor(inputEl) {
    if (!inputEl || inputEl.dataset.ragIntercepted) return;
    inputEl.dataset.ragIntercepted = "true";

    // Intercept Enter key
    inputEl.addEventListener("keydown", async (e) => {
      // Bypass: let the augmented prompt go through to the AI provider
      if (injectingPrompt) return;

      if (e.key !== "Enter" || e.shiftKey) return;

      if (processingQuery) {
        e.preventDefault();
        e.stopImmediatePropagation();
        return;
      }

      const query = getInputText(inputEl);
      if (!query || query.trim().length === 0) return;

      // Debounce: don't reprocess the same query within 3 seconds
      const now = Date.now();
      if (query === lastProcessedQuery && now - lastProcessedTime < 3000) return;

      lastProcessedQuery = query;
      lastProcessedTime = now;

      e.preventDefault();
      e.stopImmediatePropagation();
      await handleQuery(query, inputEl);
    }, true);

    // Intercept submit button clicks
    const submitSelector = provider.getSubmitSelector();
    if (submitSelector) {
      const submitBtn = document.querySelector(submitSelector);
      if (submitBtn && !submitBtn.dataset.ragIntercepted) {
        submitBtn.dataset.ragIntercepted = "true";
        submitBtn.addEventListener("click", async (e) => {
          // Bypass: let the augmented prompt go through to the AI provider
          if (injectingPrompt) return;

          const query = getInputText(inputEl);
          if (!query || query.trim().length === 0) return;

          if (processingQuery) {
            e.preventDefault();
            e.stopImmediatePropagation();
            return;
          }

          const now = Date.now();
          if (query === lastProcessedQuery && now - lastProcessedTime < 3000) return;

          lastProcessedQuery = query;
          lastProcessedTime = now;

          e.preventDefault();
          e.stopImmediatePropagation();
          await handleQuery(query, inputEl);
        }, true);
      }
    }
  }

  function observeInputChanges(inputSelector) {
    const observer = new MutationObserver(() => {
      const el = document.querySelector(inputSelector);
      if (el && !el.dataset.ragIntercepted) {
        attachInterceptor(el);
      }
    });
    observer.observe(document.body, { childList: true, subtree: true });
  }

  // ─── Get input text ──────────────────────────────────────────────────────

  function getInputText(inputEl) {
    if (inputEl.isContentEditable) {
      return inputEl.innerText || inputEl.textContent || "";
    }
    return inputEl.value || "";
  }

  function setInputText(inputEl, text) {
    if (inputEl.isContentEditable) {
      inputEl.innerText = text;
      inputEl.dispatchEvent(new Event("input", { bubbles: true }));
    } else {
      inputEl.value = text;
      inputEl.dispatchEvent(new Event("input", { bubbles: true }));
    }
  }

  // ─── Intent Detection ────────────────────────────────────────────────────

  /**
   * Lightweight intent classifier — runs BEFORE the backend call.
   * Returns "project" if the query likely relates to indexed documents,
   * "generic" if clearly unrelated (skip backend), or "search" for default.
   */
  function classifyIntent(query) {
    const q = query.toLowerCase().trim();

    // ── Clearly generic: skip backend ──────────────────────────────────
    const skipPatterns = [
      /^(hi|hey|hello|yo|sup|greetings)[\s!.,]*$/,
      /^who are you[?]?$/,
      /^what (can|do) you (do|offer|help)/,
      /write (me )?a (poem|haiku|song|rap|limerick|story|joke)/,
      /(tell|say) (me )?a (joke|riddle|funny)/,
      /what('s| is) the weather/,
      /(recipe|how to cook|how to bake)/,
      /(movie|film|tv show|netflix) (recommend|suggest)/,
      /who (won|will win) the (election|world cup|super bowl|oscar)/,
      /(bitcoin|crypto|stock) price/,
      /translate .+ (to|into) (english|spanish|french|german)/,
      /^(yes|no|ok|okay|thanks|thank you|bye|goodbye)[\s!.,]*$/,
      /^what time is it/,
      /^(how are you|what's up|whats up|howdy)/,
    ];

    for (const pattern of skipPatterns) {
      if (pattern.test(q)) {
        console.log("%c[RAG] 🏷️ Intent: generic — skipping backend", "color: #94a3b8");
        return "generic";
      }
    }

    // ── Clearly project-related: always search (must check BEFORE short-length) ─
    const projectPatterns = [
      /\b(REQ|CR)-\d+/i,                          // REQ-101, CR-1234
      /\b(project|migration|architecture|security|audit|implementation|deployment|release)/i,
      /\b(requirement|change request|artifact|deliverable|milestone|roadmap|sprint)/i,
      /\b(document|spec|specification|design doc|runbook|playbook)/i,
      /\b(payment|gateway|auth|authentication|authorization|api|endpoint|service|microservice)/i,
      /\b(stripe|adyen|braintree|rabbitmq|kubernetes|docker|terraform)/i,
      /\b(compliance|regulatory|GDPR|HIPAA|PCI|SOC2|ISO)/i,
    ];

    for (const pattern of projectPatterns) {
      if (pattern.test(q)) {
        console.log("%c[RAG] 🏷️ Intent: project — searching documents", "color: #22c55e");
        return "project";
      }
    }

    // ── Very short queries: unlikely to match documents ────────────────
    if (q.replace(/\s/g, "").length < 10) {
      console.log("%c[RAG] 🏷️ Intent: generic (too short) — skipping backend", "color: #94a3b8");
      return "generic";
    }

    // ── Default: search (when in doubt, check the documents) ───────────
    console.log("%c[RAG] 🏷️ Intent: default — searching documents", "color: #60a5fa");
    return "search";
  }

  // ─── Query Handling ──────────────────────────────────────────────────────

  async function handleQuery(originalQuery, inputEl) {
    // ── Step 1: Intent detection (skip backend for generic queries) ────
    const intent = classifyIntent(originalQuery);
    if (intent === "generic") {
      updateBadge("skipped", "Skipped · generic");
      console.log("%c[RAG] ⏭️ Skipping — query classified as generic", "color: #64748b");
      simulateSubmit(inputEl);
      // Return to green after 15s (non-critical — just skipped)
      setTimeout(() => updateBadge("ready", "RAG Ready"), 15000);
      return;
    }

    processingQuery = true;
    updateBadge("querying", "Searching...");

    try {
      const evidence = await fetchEvidence(originalQuery);

      // Catalog listing response (folders/projects) — no relevance scoring
      if (evidence && evidence.intent === 'listing' && evidence.folders && evidence.folders.length) {
        const augmentedPrompt = provider.formatPrompt(originalQuery, evidence);
        if (!augmentedPrompt) {
          updateBadge("none", "No evidence");
          simulateSubmit(inputEl);
          setTimeout(() => updateBadge("ready", "RAG Ready"), 15000);
          return;
        }
        setInputText(inputEl, augmentedPrompt);
        updateBadge("injected", evidence.folders.length + " folder(s) injected");
        injectingPrompt = true;
        setTimeout(() => {
          simulateSubmit(inputEl);
          setTimeout(() => { injectingPrompt = false; }, 500);
        }, 200);
        return;
      }

      if (!evidence || !evidence.results || evidence.results.length === 0) {
        updateBadge("none", "No evidence");
        simulateSubmit(inputEl);
        setTimeout(() => updateBadge("ready", "RAG Ready"), 15000);
        return;
      }

      // Check if any result meets the threshold
      const maxScore = Math.max(...evidence.results.map(r => r.relevance_score));
      if (maxScore < MIN_RELEVANCE_THRESHOLD) {
        updateBadge("weak", "Weak match");
        simulateSubmit(inputEl);
        setTimeout(() => updateBadge("ready", "RAG Ready"), 15000);
        return;
      }

      // Format the grounding prompt
      const augmentedPrompt = provider.formatPrompt(originalQuery, evidence);
      if (!augmentedPrompt) {
        updateBadge("none", "No evidence");
        simulateSubmit(inputEl);
        setTimeout(() => updateBadge("ready", "RAG Ready"), 15000);
        return;
      }

      // Inject the augmented prompt
      setInputText(inputEl, augmentedPrompt);

      const n = evidence.results.length;
      updateBadge("injected", `${n} source${n > 1 ? "s" : ""} injected`);

      // Set bypass flag so the subsequent submit goes straight to the AI provider
      injectingPrompt = true;

      // Small delay to let the UI update, then submit
      setTimeout(() => {
        simulateSubmit(inputEl);
        setTimeout(() => { injectingPrompt = false; }, 500);
      }, 200);
    } catch (err) {
      console.error("[RAG] Query failed:", err);
      updateBadge("error", "Backend error");
      simulateSubmit(inputEl);
    } finally {
      processingQuery = false;
    }
  }

  // ─── API Call (via background worker to avoid mixed-content blocking) ────

  async function fetchEvidence(question) {
    // Route through background service worker to avoid mixed-content blocking
    // (HTTPS pages cannot fetch HTTP localhost directly)
    return new Promise((resolve, reject) => {
      chrome.runtime.sendMessage(
        {
          type: "QUERY",
          backendUrl: BACKEND_URL,
          question: question,
          topK: 5,
        },
        (response) => {
          if (chrome.runtime.lastError) {
            reject(new Error(chrome.runtime.lastError.message));
            return;
          }
          if (!response || !response.success) {
            reject(new Error(response?.error || "Backend query failed"));
            return;
          }
          resolve(response.data);
        }
      );
    });
  }

  // ─── Submit Simulation ───────────────────────────────────────────────────

  function simulateSubmit(inputEl) {
    // Try clicking the submit button first
    const submitSelector = provider.getSubmitSelector();
    if (submitSelector) {
      const btn = document.querySelector(submitSelector);
      if (btn) {
        btn.click();
        return;
      }
    }

    // Fallback: dispatch an Enter key event on the input
    inputEl.dispatchEvent(
      new KeyboardEvent("keydown", {
        key: "Enter",
        code: "Enter",
        keyCode: 13,
        which: 13,
        bubbles: true,
        cancelable: true,
      })
    );
  }

  // ─── Utility: wait for element to exist in DOM ───────────────────────────

  function waitForElement(selector, timeoutMs, callback) {
    const el = document.querySelector(selector);
    if (el) {
      callback(el);
      return;
    }

    const observer = new MutationObserver(() => {
      const el = document.querySelector(selector);
      if (el) {
        observer.disconnect();
        callback(el);
      }
    });

    observer.observe(document.body, { childList: true, subtree: true });

    if (timeoutMs) {
      setTimeout(() => {
        observer.disconnect();
      }, timeoutMs);
    }
  }
})();
