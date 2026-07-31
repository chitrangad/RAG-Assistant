/**
 * Background service worker — lightweight, handles installation and messaging.
 */

// ─── Installation ───────────────────────────────────────────────────────────

chrome.runtime.onInstalled.addListener((details) => {
  if (details.reason === "install") {
    // Set default settings
    chrome.storage.sync.set({
      backendUrl: "http://localhost:8000",
      enabled: true,
      preferredProvider: "auto",
    });

    console.log("[RAG] Extension installed. Default settings applied.");
  } else if (details.reason === "update") {
    console.log(`[RAG] Extension updated from ${details.previousVersion} to ${chrome.runtime.getManifest().version}`);
  }
});

// ─── Message Handling ───────────────────────────────────────────────────────

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  // Health check ping from popup
  if (message.type === "PING") {
    sendResponse({ status: "ok", version: chrome.runtime.getManifest().version });
    return true;
  }

  // Query evidence from RAG backend (proxied to avoid mixed-content blocking)
  if (message.type === "QUERY") {
    const { backendUrl, question, topK } = message;
    console.log("[RAG] Background query:", question.substring(0, 60));
    fetch(`${backendUrl}/api/chat/query`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, top_k: topK || 5 }),
    })
      .then((r) => {
        if (!r.ok) throw new Error(`Backend returned ${r.status}: ${r.statusText}`);
        return r.json();
      })
      .then((data) => sendResponse({ success: true, data }))
      .catch((err) => sendResponse({ success: false, error: err.message }));

    return true; // keep the message channel open for async response
  }
});
