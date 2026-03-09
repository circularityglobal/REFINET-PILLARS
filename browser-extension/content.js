/**
 * REFInet Pillar Bridge — Content Script (Isolated World)
 *
 * Runs in Chrome's isolated world where chrome.runtime is available.
 * Injects page-api.js into the MAIN world so web pages can access
 * window.refinet. Acts as a message relay between the page and the
 * background service worker.
 *
 * Architecture:
 *   Page JS (MAIN world)  <--postMessage-->  Content Script (ISOLATED)  <--sendMessage-->  Background SW
 *   window.refinet.getPID()    -->    relay    -->    chrome.runtime.sendMessage({type: "get-identity"})
 */

(function () {
  "use strict";

  // Inject the page-level API script into the MAIN world
  const script = document.createElement("script");
  script.src = chrome.runtime.getURL("page-api.js");
  script.onload = () => script.remove();
  (document.head || document.documentElement).appendChild(script);

  // Listen for auth status broadcasts from background
  chrome.runtime.onMessage.addListener((msg) => {
    if (msg.type === "ws-status" && msg.session) {
      window.postMessage(
        {
          direction: "refinet-from-background",
          broadcast: true,
          type: "auth-status",
          session: { address: msg.session.address, pid: msg.session.pid },
        },
        "*"
      );
    }
  });

  // Relay messages from page (MAIN world) to background service worker
  window.addEventListener("message", (event) => {
    // Only accept messages from our own page
    if (event.source !== window) return;
    if (!event.data || event.data.direction !== "refinet-to-background") return;

    const { id, payload } = event.data;

    chrome.runtime.sendMessage(payload, (response) => {
      // Relay the response back to the page
      window.postMessage(
        {
          direction: "refinet-from-background",
          id,
          response: response || null,
          error: chrome.runtime.lastError
            ? chrome.runtime.lastError.message
            : null,
        },
        "*"
      );
    });
  });
})();
