# Project Knowledge Assistant — Browser Extension

Manifest V3 browser extension for Chrome/Edge that intercepts queries in AI chat interfaces and injects grounded evidence from your local RAG backend.

## Supported Providers

| Provider | URL | Status |
|----------|-----|--------|
| Microsoft Copilot | `*.cloud.microsoft`, `copilot.microsoft.com`, `bing.com/chat` | Best-effort selectors |
| Google Gemini | `gemini.google.com` | Tested |
| ChatGPT | `chat.openai.com`, `chatgpt.com` | Tested |
| Anthropic Claude | `claude.ai` | Best-effort selectors |

> **Note:** Provider DOM selectors may need recalibration if the AI service updates its UI.

## Loading the Extension

### Chrome / Edge

1. Open `chrome://extensions` (or `edge://extensions` in Edge)
2. Enable **Developer mode** (toggle in top right)
3. Click **Load unpacked**
4. Select the `extension/` directory from this project
5. The extension icon appears in your toolbar

### Development

Generated icons:
```bash
cd extension && python3 generate_icons.py
```

## How It Works

1. Visit any supported AI chat (e.g., `https://chatgpt.com`)
2. A small "RAG Ready" badge appears in the bottom-right corner
3. Type your question normally
4. The extension intercepts your query, calls `http://localhost:8000/api/chat/query`
5. If relevant evidence is found (≥30% match), your prompt is augmented with document evidence
6. The AI answers using the grounded evidence, with citations

### Badge States

| Dot Color | Meaning |
|-----------|---------|
| 🟢 Green | Ready — provider detected, backend healthy |
| 🟡 Yellow | Querying — fetching evidence from backend |
| 🔵 Blue | Injected — evidence added to prompt, submitting |
| ⚪ Gray | No results — query goes through unchanged |
| 🟤 Brown | Weak evidence — below threshold, query unchanged |
| 🔴 Red | Error — backend unreachable, query unchanged |

## Settings (Popup)

Click the extension icon to configure:
- **AI Provider**: Auto-detect or force a specific provider
- **Backend URL**: Default `http://localhost:8000`
- **Enable/Disable**: Toggle grounding on/off

## Architecture

```
popup.html + popup.js     → Settings UI (provider, backend URL, toggle)
background.js             → Service worker (install defaults, message relay)
content.js                → Content script (main logic: detect, intercept, inject)
content.css               → Badge styling (injected into AI chat pages)
providers/
  registry.js             → Provider registry (registerProvider, detectProvider)
  copilot.js              → Copilot adapter (selectors, prompt formatting)
  gemini.js               → Gemini adapter
  chatgpt.js              → ChatGPT adapter
  claude.js               → Claude adapter
```
