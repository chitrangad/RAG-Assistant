/**
 * Popup script — manages per-provider settings, backend health, and quick-open links.
 */

const PROVIDERS = [
  { id: "gemini",   name: "Google Gemini",      icon: "🟦", url: "https://gemini.google.com" },
  { id: "chatgpt",  name: "ChatGPT",             icon: "🟩", url: "https://chatgpt.com" },
  { id: "copilot",  name: "Microsoft Copilot",   icon: "🟪", url: "https://copilot.microsoft.com" },
  { id: "claude",   name: "Anthropic Claude",    icon: "🟧", url: "https://claude.ai" },
];

document.addEventListener("DOMContentLoaded", () => {
  const backendUrlInput = document.getElementById("backend-url");
  const saveBtn = document.getElementById("save-btn");
  const testBtn = document.getElementById("test-btn");
  const statusDot = document.getElementById("status-dot");
  const statusText = document.getElementById("status-text");
  const providerList = document.getElementById("provider-list");

  // ─── Build provider rows with toggles ────────────────────────────────────

  function buildProviderRows(enabledProviders) {
    providerList.innerHTML = "";
    const ep = enabledProviders || {};
    PROVIDERS.forEach((p) => {
      const checked = ep[p.id] !== false ? "checked" : ""; // default: enabled
      const row = document.createElement("div");
      row.className = "provider-row";
      row.innerHTML = `
        <div class="provider-info">
          <span class="provider-icon">${p.icon}</span>
          <div>
            <div class="provider-name">${p.name}</div>
            <div class="provider-url">${p.url.replace("https://", "")}</div>
          </div>
        </div>
        <div class="provider-actions">
          <a class="open-link" href="${p.url}" target="_blank" title="Open ${p.name}">↗</a>
          <label class="toggle">
            <input type="checkbox" data-provider="${p.id}" ${checked}>
            <span class="toggle-slider"></span>
          </label>
        </div>`;
      providerList.appendChild(row);
    });
  }

  // ─── Load saved settings ──────────────────────────────────────────────────

  chrome.storage.sync.get(["backendUrl", "enabled", "enabledProviders"], (settings) => {
    if (settings.backendUrl) backendUrlInput.value = settings.backendUrl;
    buildProviderRows(settings.enabledProviders);
    checkBackendHealth();
  });

  // ─── Save settings ────────────────────────────────────────────────────────

  saveBtn.addEventListener("click", () => {
    const enabledProviders = {};
    document.querySelectorAll('[data-provider]').forEach((cb) => {
      enabledProviders[cb.dataset.provider] = cb.checked;
    });

    const settings = {
      backendUrl: backendUrlInput.value.trim() || "http://localhost:8000",
      enabledProviders: enabledProviders,
    };

    chrome.storage.sync.set(settings, () => {
      showToast("Settings saved");
      checkBackendHealth();
    });
  });

  // ─── Test Connection ──────────────────────────────────────────────────────

  testBtn.addEventListener("click", () => {
    setStatus("chk", "Checking...");
    checkBackendHealth();
  });

  // ─── Health Check ─────────────────────────────────────────────────────────

  async function checkBackendHealth() {
    setStatus("chk", "Checking backend...");
    const baseUrl = backendUrlInput.value.trim() || "http://localhost:8000";

    try {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 3000);

      const response = await fetch(`${baseUrl}/api/health`, {
        signal: controller.signal,
      });
      clearTimeout(timeout);

      if (response.ok) {
        const data = await response.json();
        setStatus("ok", `Connected — ${data.status || "healthy"}`);
      } else {
        setStatus("err", `Backend returned ${response.status}`);
      }
    } catch (err) {
      if (err.name === "AbortError") {
        setStatus("err", "Backend unreachable (timeout)");
      } else {
        setStatus("err", "Backend unreachable");
      }
    }
  }

  function setStatus(state, message) {
    statusDot.className = "status-dot " + state;
    statusText.textContent = message;
  }

  // ─── Toast Notification ───────────────────────────────────────────────────

  function showToast(message) {
    const existing = document.querySelector(".toast");
    if (existing) existing.remove();

    const toast = document.createElement("div");
    toast.className = "toast";
    toast.textContent = message;
    document.body.appendChild(toast);

    setTimeout(() => toast.remove(), 2200);
  }
});
