/**
 * REFInet Pillar Bridge — Page API (MAIN World)
 *
 * Injected into the page's MAIN world by content.js.
 * Exposes window.refinet to web page JavaScript.
 * Communicates with the content script (isolated world)
 * via window.postMessage for relay to the background SW.
 */

(function () {
  "use strict";

  // Avoid double-injection
  if (window.refinet) return;

  let msgId = 0;
  const pendingMessages = new Map();

  // Listen for responses relayed back from the content script
  window.addEventListener("message", (event) => {
    if (event.source !== window) return;
    if (!event.data || event.data.direction !== "refinet-from-background") return;

    const { id, response, error } = event.data;
    const pending = pendingMessages.get(id);
    if (!pending) return;

    pendingMessages.delete(id);
    if (error) {
      pending.reject(new Error(error));
    } else {
      pending.resolve(response);
    }
  });

  function sendToBackground(payload) {
    return new Promise((resolve, reject) => {
      const id = ++msgId;
      pendingMessages.set(id, { resolve, reject });

      window.postMessage(
        { direction: "refinet-to-background", id, payload },
        "*"
      );

      // Timeout after 15 seconds
      setTimeout(() => {
        if (pendingMessages.has(id)) {
          pendingMessages.delete(id);
          reject(new Error("REFInet request timeout"));
        }
      }, 15000);
    });
  }

  /**
   * Public API exposed to web pages via window.refinet
   *
   * All methods return Promises. Identity and session data
   * are read-only; authentication requires user confirmation
   * via the extension popup.
   */
  const refinet = Object.freeze({
    /**
     * Check if the extension is connected to a local Pillar.
     * @returns {Promise<boolean>}
     */
    isConnected: async () => {
      try {
        const resp = await sendToBackground({ type: "status" });
        return !!(resp && resp.connected);
      } catch {
        return false;
      }
    },

    /**
     * Get the local Pillar's PID (public identity).
     * @returns {Promise<{pid: string, public_key: string} | null>}
     */
    getPID: async () => {
      try {
        const resp = await sendToBackground({ type: "get-identity" });
        if (resp && resp.ok && resp.identity) {
          return { pid: resp.identity.pid, public_key: resp.identity.public_key };
        }
        return null;
      } catch {
        return null;
      }
    },

    /**
     * Get the current authenticated session info.
     * Does not expose session_id (security).
     * @returns {Promise<{address: string, pid: string, expires_at: string} | null>}
     */
    getSession: async () => {
      try {
        const resp = await sendToBackground({ type: "get-session" });
        if (resp && resp.ok && resp.session) {
          return {
            address: resp.session.address,
            pid: resp.session.pid,
            expires_at: resp.session.expires_at,
          };
        }
        return null;
      } catch {
        return null;
      }
    },

    /**
     * Browse a Gopher selector through the local Pillar.
     * @param {string} selector - Gopher selector (e.g., "/", "/about")
     * @returns {Promise<{data: string, signature: object} | null>}
     */
    browseGopher: async (selector) => {
      try {
        const resp = await sendToBackground({ type: "request", selector });
        if (resp && resp.ok && resp.data) {
          return { data: resp.data.data, signature: resp.data.signature };
        }
        return null;
      } catch {
        return null;
      }
    },

    /**
     * Get verified PIDs that this extension has encountered.
     * @returns {Promise<object>} Map of PID -> {public_key, first_seen, last_seen, verified}
     */
    getKnownPIDs: async () => {
      try {
        const resp = await sendToBackground({ type: "get-known-pids" });
        if (resp && resp.ok) {
          return resp.pids || {};
        }
        return {};
      } catch {
        return {};
      }
    },

    /**
     * Request wallet connection and SIWE authentication.
     * Opens the extension popup for user approval. The page
     * receives the result via the returned promise or a
     * "refinet-authenticated" CustomEvent on window.
     * @param {object} [options] - { chainId: number }
     * @returns {Promise<{address: string, pid: string} | null>}
     */
    connectWallet: async (options) => {
      try {
        const resp = await sendToBackground({
          type: "wallet-sign",
          walletUuid: (options && options.walletUuid) || null,
          chainId: (options && options.chainId) || 1,
        });
        if (resp && resp.ok && resp.session) {
          return { address: resp.session.address, pid: resp.session.pid };
        }
        return null;
      } catch {
        return null;
      }
    },

    /** Protocol version */
    version: "0.4.0",
  });

  // Expose to page context (immutable)
  Object.defineProperty(window, "refinet", {
    value: refinet,
    writable: false,
    configurable: false,
    enumerable: true,
  });

  // Dispatch event so pages can detect the extension
  window.dispatchEvent(
    new CustomEvent("refinet-ready", { detail: { version: "0.4.0" } })
  );
})();
