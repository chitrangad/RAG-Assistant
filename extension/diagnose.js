/**
 * Diagnose Script — AI Chat Selector Finder
 *
 * Paste this into the DevTools Console on any AI chat page to discover
 * the correct DOM selectors for the chat input and submit button.
 *
 * Usage:
 *   1. Open your AI chat (ChatGPT, Gemini, Claude, Copilot)
 *   2. Press F12 to open DevTools
 *   3. Go to the Console tab
 *   4. Paste this entire script and press Enter
 *   5. Copy the suggested selectors into the provider file
 *
 * Or use as a bookmarklet (minified version below).
 */

(function findAIChatSelectors() {
  "use strict";

  const results = {
    url: window.location.href,
    hostname: window.location.hostname,
    inputs: [],
    buttons: [],
    recommendation: null,
  };

  // ── Find all likely chat input elements ──────────────────────────────────

  // Textareas
  document.querySelectorAll("textarea").forEach((el) => {
    results.inputs.push({
      tag: "textarea",
      id: el.id || null,
      className: el.className || null,
      placeholder: el.getAttribute("placeholder") || null,
      ariaLabel: el.getAttribute("aria-label") || null,
      dataTestId: el.getAttribute("data-testid") || null,
      suggestedSelector: el.id
        ? `#${el.id}`
        : el.getAttribute("data-testid")
          ? `textarea[data-testid="${el.getAttribute("data-testid")}"]`
          : el.getAttribute("aria-label")
            ? `textarea[aria-label="${el.getAttribute("aria-label")}"]`
            : el.getAttribute("placeholder")
              ? `textarea[placeholder="${el.getAttribute("placeholder")}"]`
              : "textarea",
      visible: el.offsetParent !== null,
      isContentEditable: false,
    });
  });

  // Contenteditable divs
  document.querySelectorAll('div[contenteditable="true"]').forEach((el) => {
    results.inputs.push({
      tag: "div",
      id: el.id || null,
      className: el.className || null,
      placeholder: el.getAttribute("placeholder") || null,
      ariaLabel: el.getAttribute("aria-label") || null,
      dataTestId: el.getAttribute("data-testid") || null,
      suggestedSelector: el.id
        ? `#${el.id}`
        : el.getAttribute("data-testid")
          ? `div[data-testid="${el.getAttribute("data-testid")}"]`
          : el.getAttribute("aria-label")
            ? `div[contenteditable="true"][aria-label="${el.getAttribute("aria-label")}"]`
            : el.className
              ? `div.${el.className.split(" ")[0]}[contenteditable="true"]`
              : 'div[contenteditable="true"]',
      visible: el.offsetParent !== null,
      isContentEditable: true,
    });
  });

  // ── Find all likely submit/send buttons ──────────────────────────────────

  // Look for buttons near input areas
  const buttonSelectors = [
    'button[aria-label*="Send" i]',
    'button[aria-label*="Submit" i]',
    'button[data-testid*="send" i]',
    'button[type="submit"]',
  ];

  const foundButtons = new Set();
  buttonSelectors.forEach((sel) => {
    document.querySelectorAll(sel).forEach((btn) => {
      const key = btn.ariaLabel + btn.className;
      if (!foundButtons.has(key)) {
        foundButtons.add(key);
        results.buttons.push({
          tag: btn.tagName.toLowerCase(),
          ariaLabel: btn.getAttribute("aria-label") || null,
          dataTestId: btn.getAttribute("data-testid") || null,
          className: btn.className || null,
          title: btn.getAttribute("title") || null,
          type: btn.getAttribute("type") || null,
          suggestedSelector: btn.getAttribute("data-testid")
            ? `button[data-testid="${btn.getAttribute("data-testid")}"]`
            : btn.getAttribute("aria-label")
              ? `button[aria-label="${btn.getAttribute("aria-label")}"]`
              : "button[type=\"submit\"]",
        });
      }
    });
  });

  // ── Make a recommendation ────────────────────────────────────────────────

  const visibleInputs = results.inputs.filter((i) => i.visible);
  if (visibleInputs.length > 0) {
    const bestInput = visibleInputs[0];
    const bestButton = results.buttons[0];
    results.recommendation = {
      inputSelector: bestInput.suggestedSelector,
      submitSelector: bestButton?.suggestedSelector || null,
      inputTag: bestInput.tag,
      inputIsContentEditable: bestInput.isContentEditable,
    };
  }

  // ── Output ───────────────────────────────────────────────────────────────

  console.group(
    "%c🔍 RAG Selector Finder Results",
    "color: #22c55e; font-size: 14px; font-weight: bold"
  );
  console.log("URL:", results.url);

  if (results.inputs.length === 0) {
    console.warn(
      "%c⚠️ No input elements found. Is the chat page loaded?",
      "color: #f59e0b"
    );
  } else {
    console.log(
      `%c📝 Found ${results.inputs.length} input(s):`,
      "font-weight: bold"
    );
    console.table(
      results.inputs.map((i) => ({
        tag: i.tag,
        visible: i.visible ? "✅" : "❌",
        id: i.id || "-",
        placeholder: (i.placeholder || "").substring(0, 40),
        suggestedSelector: i.suggestedSelector,
      }))
    );
  }

  if (results.buttons.length === 0) {
    console.warn(
      "%c⚠️ No submit buttons found.",
      "color: #f59e0b"
    );
  } else {
    console.log(
      `%c🔘 Found ${results.buttons.length} button(s):`,
      "font-weight: bold"
    );
    console.table(
      results.buttons.map((b) => ({
        ariaLabel: b.ariaLabel || "-",
        dataTestId: b.dataTestId || "-",
        suggestedSelector: b.suggestedSelector,
      }))
    );
  }

  if (results.recommendation) {
    console.log(
      "%c✅ RECOMMENDED SELECTORS:",
      "color: #22c55e; font-weight: bold"
    );
    console.log(
      `  Input:  %c"${results.recommendation.inputSelector}"`,
      "color: #60a5fa; font-family: monospace"
    );
    console.log(
      `  Submit: %c"${results.recommendation.submitSelector || "N/A — no button found"}"`,
      "color: #60a5fa; font-family: monospace"
    );
    console.log(
      `  Input is contenteditable: ${results.recommendation.inputIsContentEditable ? "Yes (use innerText)" : "No (use value)"}`
    );
    console.log(
      "\n%c📋 Copy the selectors above into the provider adapter file in extension/providers/",
      "color: #a78bfa"
    );
  }

  console.groupEnd();

  // Also return for programmatic use
  return results;
})();
