/**
 * REFInet Pillar Bridge — Background Service Worker
 *
 * Maintains a WebSocket connection to the local Pillar node
 * at ws://localhost:7075. Handles identity retrieval, SIWE
 * authentication, session management, and Ed25519 signature
 * verification for PID-SIWE correlation.
 */

const DEFAULT_WS_URL = "ws://localhost:7075";

let ws = null;
let pendingRequests = new Map();
let requestId = 0;
let reconnectDelay = 1000;
const MAX_RECONNECT_DELAY = 30000;

// --- Identity & Session State ---

let pillarIdentity = null; // {pid, public_key, key_store, protocol}
let sessionData = null; // {session_id, expires_at, pid, address}
let knownPids = {}; // {pid: {public_key, first_seen, last_seen, verified}}

// --- WebSocket Connection ---

function connect(url) {
  if (ws && ws.readyState === WebSocket.OPEN) return;

  ws = new WebSocket(url || DEFAULT_WS_URL);

  ws.onopen = async () => {
    console.log("[REFInet] Connected to Pillar");
    reconnectDelay = 1000; // Reset backoff on success
    broadcastStatus(true);

    // Fetch Pillar identity immediately on connect
    await fetchIdentity();

    // Restore session from storage if valid
    await restoreSession();
  };

  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);

      // Check for typed responses (identity, auth) — resolve by type
      if (data.type && pendingRequests.size > 0) {
        for (const [id, pending] of pendingRequests) {
          if (pending.expectedType === data.type || !pending.expectedType) {
            pending.resolve(data);
            pendingRequests.delete(id);
            return;
          }
        }
      }

      // Fall back to FIFO resolution for selector-based requests
      const pending = pendingRequests.values().next().value;
      if (pending) {
        // Verify Ed25519 signature if present
        if (data.signature) {
          verifyAndTrackSignature(data);
        }
        pending.resolve(data);
        pendingRequests.delete(pending.id);
      }
    } catch (e) {
      console.error("[REFInet] Parse error:", e);
    }
  };

  ws.onerror = (error) => {
    console.warn("[REFInet] WebSocket error:", error);
  };

  ws.onclose = () => {
    console.log("[REFInet] Disconnected from Pillar");
    ws = null;
    broadcastStatus(false);

    // Reject all pending requests
    for (const [id, pending] of pendingRequests) {
      pending.reject(new Error("Connection lost"));
    }
    pendingRequests.clear();

    // Exponential backoff reconnect
    setTimeout(() => {
      connect();
      reconnectDelay = Math.min(reconnectDelay * 2, MAX_RECONNECT_DELAY);
    }, reconnectDelay);
  };
}

function broadcastStatus(connected) {
  chrome.runtime.sendMessage({
    type: "ws-status",
    connected,
    identity: pillarIdentity,
    session: sessionData ? { address: sessionData.address, pid: sessionData.pid } : null,
  }).catch(() => {}); // Popup may not be open
}

function sendTypedMessage(message, expectedType) {
  return new Promise((resolve, reject) => {
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      reject(new Error("Not connected to Pillar"));
      return;
    }

    const id = ++requestId;
    pendingRequests.set(id, { id, resolve, reject, expectedType });
    ws.send(JSON.stringify(message));

    setTimeout(() => {
      if (pendingRequests.has(id)) {
        pendingRequests.get(id).reject(new Error("Request timeout"));
        pendingRequests.delete(id);
      }
    }, 30000);
  });
}

function sendRequest(selector, sessionId) {
  const msg = { selector: selector || "" };
  // Auto-attach session_id if authenticated
  const sid = sessionId || (sessionData ? sessionData.session_id : null);
  if (sid) msg.session_id = sid;

  return sendTypedMessage(msg, null);
}

// --- Identity ---

async function fetchIdentity() {
  try {
    const resp = await sendTypedMessage({ type: "identity" }, "identity");
    if (resp.status === "ok") {
      pillarIdentity = {
        pid: resp.pid,
        public_key: resp.public_key,
        key_store: resp.key_store,
        protocol: resp.protocol,
      };
      // Cache in storage for quick access
      await chrome.storage.local.set({ refinet_identity: pillarIdentity });
      console.log("[REFInet] Identity loaded — PID:", pillarIdentity.pid.substring(0, 16) + "...");
    }
  } catch (e) {
    console.warn("[REFInet] Failed to fetch identity:", e.message);
    // Try to load cached identity
    const stored = await chrome.storage.local.get("refinet_identity");
    if (stored.refinet_identity) {
      pillarIdentity = stored.refinet_identity;
    }
  }
}

// --- Session Management ---

async function restoreSession() {
  try {
    const stored = await chrome.storage.local.get("refinet_session");
    if (stored.refinet_session) {
      const session = stored.refinet_session;
      // Check if session is still valid (not expired)
      if (new Date(session.expires_at) > new Date()) {
        sessionData = session;
        console.log("[REFInet] Session restored for", session.address);
        broadcastStatus(true);
      } else {
        // Expired session — clear it
        await chrome.storage.local.remove("refinet_session");
        console.log("[REFInet] Expired session cleared");
      }
    }
  } catch (e) {
    console.warn("[REFInet] Failed to restore session:", e.message);
  }
}

async function requestChallenge(address, chainId) {
  const resp = await sendTypedMessage(
    { type: "auth_challenge", address, chain_id: chainId || 1 },
    "auth_challenge"
  );
  if (resp.status !== "ok") {
    throw new Error(resp.error || "Challenge request failed");
  }
  return { message: resp.message, nonce: resp.nonce, pid: resp.pid };
}

async function verifySignature_auth(address, signature, message) {
  const resp = await sendTypedMessage(
    { type: "auth_verify", address, signature, message },
    "auth_verify"
  );
  if (resp.status !== "ok") {
    throw new Error(resp.error || "Verification failed");
  }
  // Store session
  sessionData = {
    session_id: resp.session_id,
    expires_at: resp.expires_at,
    pid: resp.pid,
    address: resp.address,
  };
  await chrome.storage.local.set({ refinet_session: sessionData });
  console.log("[REFInet] Authenticated as", resp.address, "— PID:", resp.pid.substring(0, 16) + "...");
  broadcastStatus(true);
  return sessionData;
}

async function logout() {
  sessionData = null;
  await chrome.storage.local.remove("refinet_session");
  console.log("[REFInet] Logged out");
  broadcastStatus(ws && ws.readyState === WebSocket.OPEN);
}

// --- Ed25519 Signature Verification ---

function hexToBytes(hex) {
  const bytes = new Uint8Array(hex.length / 2);
  for (let i = 0; i < hex.length; i += 2) {
    bytes[i / 2] = parseInt(hex.substring(i, i + 2), 16);
  }
  return bytes;
}

async function verifyEd25519(data, signatureHex, publicKeyHex) {
  try {
    const pubKeyBytes = hexToBytes(publicKeyHex);
    const sigBytes = hexToBytes(signatureHex);
    const dataBytes = new TextEncoder().encode(data);

    const key = await crypto.subtle.importKey(
      "raw",
      pubKeyBytes,
      { name: "Ed25519" },
      false,
      ["verify"]
    );

    return await crypto.subtle.verify("Ed25519", key, sigBytes, dataBytes);
  } catch (e) {
    console.warn("[REFInet] Ed25519 verification error:", e.message);
    return false;
  }
}

async function verifyAndTrackSignature(response) {
  if (!response.signature) return;

  const { pid, pubkey, sig, hash } = response.signature;
  const verified = await verifyEd25519(response.data, sig, pubkey);
  const now = new Date().toISOString();

  if (!knownPids[pid]) {
    knownPids[pid] = { public_key: pubkey, first_seen: now, last_seen: now, verified };
  } else {
    knownPids[pid].last_seen = now;
    knownPids[pid].verified = verified;
  }

  // Persist known PIDs
  await chrome.storage.local.set({ refinet_known_pids: knownPids });

  if (!verified) {
    console.warn("[REFInet] Signature verification FAILED for PID:", pid.substring(0, 16));
  }
}

// --- Native Wallet Integration (EIP-6963 + EIP-1193) ---

async function getActiveTabId() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab || !tab.id) throw new Error("No active tab available");
  // Cannot inject into chrome://, edge://, about:, or extension pages
  if (!tab.url || !/^https?:\/\//.test(tab.url)) {
    throw new Error("WALLET_TAB_INVALID");
  }
  return tab.id;
}

async function discoverWallets() {
  const tabId = await getActiveTabId();
  const [result] = await chrome.scripting.executeScript({
    target: { tabId },
    world: "MAIN",
    func: () => {
      return new Promise((resolve) => {
        const wallets = [];
        const seen = new Set();

        // EIP-6963: Modern multi-wallet discovery
        const handler = (event) => {
          const { info } = event.detail;
          if (info && info.uuid && !seen.has(info.uuid)) {
            seen.add(info.uuid);
            wallets.push({
              uuid: info.uuid,
              name: info.name || "Unknown Wallet",
              icon: info.icon || null,
              rdns: info.rdns || null,
              isLegacy: false,
            });
          }
        };
        window.addEventListener("eip6963:announceProvider", handler);
        window.dispatchEvent(new Event("eip6963:requestProvider"));

        // Collect announcements for 600ms, then fall back to legacy
        setTimeout(() => {
          window.removeEventListener("eip6963:announceProvider", handler);

          if (wallets.length === 0 && window.ethereum) {
            // Legacy fallback: detect from window.ethereum flags
            const providers = window.ethereum.providers || [window.ethereum];
            for (const p of providers) {
              const name = p.isRabby ? "Rabby Wallet"
                : p.isMetaMask ? "MetaMask"
                : p.isCoinbaseWallet ? "Coinbase Wallet"
                : p.isDcentWallet ? "D'Cent Wallet"
                : p.isBraveWallet ? "Brave Wallet"
                : p.isTrust ? "Trust Wallet"
                : p.isTokenPocket ? "TokenPocket"
                : p.isOkxWallet ? "OKX Wallet"
                : "EVM Wallet";
              const id = "legacy-" + wallets.length;
              if (!seen.has(name)) {
                seen.add(name);
                wallets.push({
                  uuid: id,
                  name,
                  icon: null,
                  rdns: null,
                  isLegacy: true,
                });
              }
            }
          }

          resolve(wallets);
        }, 600);
      });
    },
  });
  return result.result || [];
}

async function walletRequestAccounts(tabId, walletUuid) {
  const [result] = await chrome.scripting.executeScript({
    target: { tabId },
    world: "MAIN",
    args: [walletUuid],
    func: (uuid) => {
      return new Promise(async (resolve, reject) => {
        let provider = null;

        // Try EIP-6963 first
        if (!uuid.startsWith("legacy-")) {
          const found = new Promise((res) => {
            const handler = (event) => {
              if (event.detail.info.uuid === uuid) {
                window.removeEventListener("eip6963:announceProvider", handler);
                res(event.detail.provider);
              }
            };
            window.addEventListener("eip6963:announceProvider", handler);
            window.dispatchEvent(new Event("eip6963:requestProvider"));
            setTimeout(() => res(null), 600);
          });
          provider = await found;
        }

        // Legacy fallback
        if (!provider) {
          if (window.ethereum && window.ethereum.providers) {
            const idx = parseInt(uuid.replace("legacy-", ""), 10);
            provider = window.ethereum.providers[idx] || window.ethereum;
          } else if (window.ethereum) {
            provider = window.ethereum;
          }
        }

        if (!provider) {
          reject(new Error("Wallet provider not found"));
          return;
        }

        try {
          const accounts = await provider.request({ method: "eth_requestAccounts" });
          resolve(accounts);
        } catch (e) {
          reject(new Error(e.message || "User rejected connection"));
        }
      });
    },
  });
  if (result.result) return result.result;
  throw new Error(result.error || "Failed to get accounts");
}

async function walletPersonalSign(tabId, walletUuid, message, address) {
  // Convert message to hex (personal_sign expects hex-encoded UTF-8)
  const msgBytes = new TextEncoder().encode(message);
  let hexMsg = "0x";
  for (const b of msgBytes) {
    hexMsg += b.toString(16).padStart(2, "0");
  }

  const [result] = await chrome.scripting.executeScript({
    target: { tabId },
    world: "MAIN",
    args: [walletUuid, hexMsg, address],
    func: (uuid, hexMessage, addr) => {
      return new Promise(async (resolve, reject) => {
        let provider = null;

        // Try EIP-6963 first
        if (!uuid.startsWith("legacy-")) {
          const found = new Promise((res) => {
            const handler = (event) => {
              if (event.detail.info.uuid === uuid) {
                window.removeEventListener("eip6963:announceProvider", handler);
                res(event.detail.provider);
              }
            };
            window.addEventListener("eip6963:announceProvider", handler);
            window.dispatchEvent(new Event("eip6963:requestProvider"));
            setTimeout(() => res(null), 600);
          });
          provider = await found;
        }

        // Legacy fallback
        if (!provider) {
          if (window.ethereum && window.ethereum.providers) {
            const idx = parseInt(uuid.replace("legacy-", ""), 10);
            provider = window.ethereum.providers[idx] || window.ethereum;
          } else if (window.ethereum) {
            provider = window.ethereum;
          }
        }

        if (!provider) {
          reject(new Error("Wallet provider not found"));
          return;
        }

        try {
          const signature = await provider.request({
            method: "personal_sign",
            params: [hexMessage, addr],
          });
          resolve(signature);
        } catch (e) {
          reject(new Error(e.message || "User rejected signing"));
        }
      });
    },
  });
  if (result.result) return result.result;
  throw new Error(result.error || "Failed to sign message");
}

// --- Message Handler ---

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === "connect") {
    connect(message.url);
    sendResponse({ ok: true });
    return false;
  }

  if (message.type === "disconnect") {
    if (ws) ws.close();
    sendResponse({ ok: true });
    return false;
  }

  if (message.type === "status") {
    sendResponse({
      connected: ws && ws.readyState === WebSocket.OPEN,
      identity: pillarIdentity,
      session: sessionData
        ? { address: sessionData.address, pid: sessionData.pid, expires_at: sessionData.expires_at }
        : null,
    });
    return false;
  }

  if (message.type === "get-identity") {
    sendResponse({ ok: true, identity: pillarIdentity });
    return false;
  }

  if (message.type === "get-session") {
    sendResponse({ ok: true, session: sessionData });
    return false;
  }

  if (message.type === "request") {
    sendRequest(message.selector, message.sessionId)
      .then((data) => sendResponse({ ok: true, data }))
      .catch((err) => sendResponse({ ok: false, error: err.message }));
    return true; // async response
  }

  if (message.type === "auth-challenge") {
    requestChallenge(message.address, message.chainId)
      .then((challenge) => sendResponse({ ok: true, challenge }))
      .catch((err) => sendResponse({ ok: false, error: err.message }));
    return true;
  }

  if (message.type === "auth-verify") {
    verifySignature_auth(message.address, message.signature, message.message)
      .then((session) => sendResponse({ ok: true, session }))
      .catch((err) => sendResponse({ ok: false, error: err.message }));
    return true;
  }

  if (message.type === "auth-logout") {
    logout()
      .then(() => sendResponse({ ok: true }))
      .catch((err) => sendResponse({ ok: false, error: err.message }));
    return true;
  }

  if (message.type === "get-known-pids") {
    sendResponse({ ok: true, pids: knownPids });
    return false;
  }

  // --- Native Wallet Handlers ---

  if (message.type === "wallet-discover") {
    discoverWallets()
      .then((wallets) => sendResponse({ ok: true, wallets }))
      .catch((err) => sendResponse({ ok: false, error: err.message, wallets: [] }));
    return true;
  }

  if (message.type === "wallet-sign") {
    // One-click orchestrated flow: connect → challenge → sign → verify
    (async () => {
      const tabId = await getActiveTabId();
      const uuid = message.walletUuid;
      const chainId = message.chainId || 1;

      // Step 1: Get accounts from wallet
      const accounts = await walletRequestAccounts(tabId, uuid);
      if (!accounts || accounts.length === 0) {
        throw new Error("No accounts returned from wallet");
      }
      const address = accounts[0];

      // Step 2: Get SIWE challenge from Pillar
      const challenge = await requestChallenge(address, chainId);

      // Step 3: Sign with wallet
      const signature = await walletPersonalSign(tabId, uuid, challenge.message, address);

      // Step 4: Verify with Pillar
      const session = await verifySignature_auth(address, signature, challenge.message);

      return session;
    })()
      .then((session) => sendResponse({ ok: true, session }))
      .catch((err) => sendResponse({ ok: false, error: err.message }));
    return true;
  }

  return false;
});

// Load known PIDs from storage on startup
chrome.storage.local.get("refinet_known_pids").then((stored) => {
  if (stored.refinet_known_pids) {
    knownPids = stored.refinet_known_pids;
  }
});

// Auto-connect on install/startup
connect();
