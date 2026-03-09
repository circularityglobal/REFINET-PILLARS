/**
 * REFInet Pillar Bridge — Popup Logic
 *
 * Renders Gopher menus from the Pillar WebSocket bridge.
 * Handles SIWE authentication flow for PID-SIWE correlation.
 */

const contentEl = document.getElementById("content");
const statusDot = document.getElementById("status-dot");
const btnBack = document.getElementById("btn-back");
const btnRefresh = document.getElementById("btn-refresh");
const btnConnect = document.getElementById("btn-connect");
const breadcrumb = document.getElementById("breadcrumb");

// Auth elements
const authLabel = document.getElementById("auth-label");
const btnAuth = document.getElementById("btn-auth");
const pidBadge = document.getElementById("pid-badge");
const authModal = document.getElementById("auth-modal");
const authChain = document.getElementById("auth-chain");
const authError = document.getElementById("auth-error");
const btnAuthClose = document.getElementById("btn-auth-close");
const authStepResult = document.getElementById("auth-step-result");
const authResultMsg = document.getElementById("auth-result-msg");

// Wallet discovery elements
const authStepWallets = document.getElementById("auth-step-wallets");
const walletList = document.getElementById("wallet-list");
const btnDetectWallets = document.getElementById("btn-detect-wallets");
const btnManualEntry = document.getElementById("btn-manual-entry");

// Wallet signing elements
const authStepSigning = document.getElementById("auth-step-signing");
const signingStatusText = document.getElementById("signing-status-text");
const btnCancelSigning = document.getElementById("btn-cancel-signing");

// Manual entry elements (fallback)
const authStepAddress = document.getElementById("auth-step-address");
const authAddress = document.getElementById("auth-address");
const btnGetChallenge = document.getElementById("btn-get-challenge");
const btnBackToWallets = document.getElementById("btn-back-to-wallets");
const authStepSign = document.getElementById("auth-step-sign");
const authChallengeMsg = document.getElementById("auth-challenge-msg");
const authSignature = document.getElementById("auth-signature");
const btnVerifySig = document.getElementById("btn-verify-sig");

let history = [];
let currentSelector = "";
let currentChallenge = null; // {message, nonce, pid}

// --- Communication with background ---

function sendMessage(msg) {
  return new Promise((resolve) => {
    chrome.runtime.sendMessage(msg, resolve);
  });
}

async function checkStatus() {
  const resp = await sendMessage({ type: "status" });
  const connected = resp && resp.connected;
  updateStatusDot(connected);
  updateAuthDisplay(connected, resp ? resp.identity : null, resp ? resp.session : null);
  return connected;
}

function updateStatusDot(connected) {
  statusDot.className = connected ? "dot online" : "dot offline";
  statusDot.title = connected ? "Connected" : "Disconnected";
}

function updateAuthDisplay(connected, identity, session) {
  if (!connected) {
    authLabel.textContent = "Offline";
    authLabel.className = "auth-label anonymous";
    btnAuth.textContent = "Sign In";
    btnAuth.disabled = true;
    pidBadge.classList.add("hidden");
    return;
  }

  btnAuth.disabled = false;

  if (session && session.address) {
    // Authenticated
    const shortAddr = session.address.substring(0, 6) + "..." + session.address.slice(-4);
    authLabel.textContent = "Authenticated: " + shortAddr;
    authLabel.className = "auth-label authenticated";
    btnAuth.textContent = "Sign Out";
  } else if (identity && identity.pid) {
    // Connected but not authenticated
    authLabel.textContent = "Connected";
    authLabel.className = "auth-label connected";
    btnAuth.textContent = "Sign In";
  } else {
    authLabel.textContent = "Anonymous";
    authLabel.className = "auth-label anonymous";
    btnAuth.textContent = "Sign In";
  }

  // PID badge
  if (identity && identity.pid) {
    pidBadge.textContent = "PID: " + identity.pid.substring(0, 16) + "...";
    pidBadge.classList.remove("hidden");
  } else {
    pidBadge.classList.add("hidden");
  }
}

// --- Auth Flow ---

btnAuth.addEventListener("click", async () => {
  const resp = await sendMessage({ type: "status" });
  if (resp && resp.session && resp.session.address) {
    // Already authenticated — sign out
    await sendMessage({ type: "auth-logout" });
    await checkStatus();
  } else {
    // Open auth modal
    showAuthModal();
  }
});

function hideAllAuthSteps() {
  authStepWallets.classList.add("hidden");
  authStepSigning.classList.add("hidden");
  authStepAddress.classList.add("hidden");
  authStepSign.classList.add("hidden");
  authStepResult.classList.add("hidden");
  authError.classList.add("hidden");
}

function showAuthModal() {
  authModal.classList.remove("hidden");
  hideAllAuthSteps();
  authStepWallets.classList.remove("hidden");
  authAddress.value = "";
  authSignature.value = "";
  authChallengeMsg.value = "";
  currentChallenge = null;
  detectWallets();
}

function hideAuthModal() {
  authModal.classList.add("hidden");
}

btnAuthClose.addEventListener("click", hideAuthModal);

// --- Wallet Discovery ---

async function detectWallets() {
  walletList.innerHTML = '<p class="muted" id="wallet-detecting">Detecting wallets...</p>';

  const resp = await sendMessage({ type: "wallet-discover" });

  if (!resp || !resp.ok || !resp.wallets || resp.wallets.length === 0) {
    const errorMsg = resp && resp.error === "WALLET_TAB_INVALID"
      ? "Open any web page first, then try again."
      : "No EVM wallets detected.";
    walletList.innerHTML =
      '<p class="no-wallets">' + escapeHtml(errorMsg) + "</p>";
    return;
  }

  walletList.innerHTML = "";
  for (const wallet of resp.wallets) {
    const card = document.createElement("div");
    card.className = "wallet-card";
    card.dataset.uuid = wallet.uuid;

    const icon = document.createElement("div");
    icon.className = "wallet-icon";
    if (wallet.icon) {
      const img = document.createElement("img");
      img.src = wallet.icon;
      img.alt = wallet.name;
      img.width = 32;
      img.height = 32;
      icon.appendChild(img);
    } else {
      icon.textContent = wallet.name.charAt(0).toUpperCase();
    }

    const info = document.createElement("div");
    info.className = "wallet-info";
    const name = document.createElement("span");
    name.className = "wallet-name";
    name.textContent = wallet.name;
    info.appendChild(name);
    if (wallet.rdns) {
      const rdns = document.createElement("span");
      rdns.className = "wallet-rdns";
      rdns.textContent = wallet.rdns;
      info.appendChild(rdns);
    }

    card.appendChild(icon);
    card.appendChild(info);

    card.addEventListener("click", () => onWalletSelected(wallet));
    walletList.appendChild(card);
  }
}

btnDetectWallets.addEventListener("click", detectWallets);

// --- One-Click Wallet Signing ---

async function onWalletSelected(wallet) {
  hideAllAuthSteps();
  authStepSigning.classList.remove("hidden");
  signingStatusText.textContent = "Connecting to " + wallet.name + "...";

  const chainId = parseInt(authChain.value, 10);

  const resp = await sendMessage({
    type: "wallet-sign",
    walletUuid: wallet.uuid,
    chainId,
  });

  if (!resp || !resp.ok) {
    hideAllAuthSteps();
    authStepWallets.classList.remove("hidden");
    showAuthError((resp && resp.error) || "Wallet signing failed");
    return;
  }

  // Success
  hideAllAuthSteps();
  authStepResult.classList.remove("hidden");
  authResultMsg.textContent =
    "Authenticated! PID-SIWE correlation established. " +
    "Your browser identity is now cryptographically linked to your Pillar.";

  await checkStatus();
  setTimeout(hideAuthModal, 3000);
}

btnCancelSigning.addEventListener("click", () => {
  hideAllAuthSteps();
  authStepWallets.classList.remove("hidden");
});

// --- Manual Entry Fallback ---

btnManualEntry.addEventListener("click", () => {
  hideAllAuthSteps();
  authStepAddress.classList.remove("hidden");
});

btnBackToWallets.addEventListener("click", () => {
  hideAllAuthSteps();
  authStepWallets.classList.remove("hidden");
});

btnGetChallenge.addEventListener("click", async () => {
  const address = authAddress.value.trim();
  const chainId = parseInt(authChain.value, 10);

  if (!address.startsWith("0x") || address.length !== 42) {
    showAuthError("Invalid address. Must be 0x followed by 40 hex characters.");
    return;
  }

  authError.classList.add("hidden");
  btnGetChallenge.disabled = true;
  btnGetChallenge.textContent = "Requesting...";

  try {
    const resp = await sendMessage({ type: "auth-challenge", address, chainId });
    if (!resp || !resp.ok) {
      showAuthError((resp && resp.error) || "Challenge request failed");
      return;
    }

    currentChallenge = resp.challenge;
    authChallengeMsg.value = resp.challenge.message;

    hideAllAuthSteps();
    authStepSign.classList.remove("hidden");
  } catch (e) {
    showAuthError(e.message);
  } finally {
    btnGetChallenge.disabled = false;
    btnGetChallenge.textContent = "Get Challenge";
  }
});

btnVerifySig.addEventListener("click", async () => {
  const signature = authSignature.value.trim();
  const address = authAddress.value.trim();

  if (!signature.startsWith("0x") || signature.length < 130) {
    showAuthError("Invalid signature. Must be a 0x-prefixed hex string.");
    return;
  }

  authError.classList.add("hidden");
  btnVerifySig.disabled = true;
  btnVerifySig.textContent = "Verifying...";

  try {
    const resp = await sendMessage({
      type: "auth-verify",
      address,
      signature,
      message: currentChallenge.message,
    });

    if (!resp || !resp.ok) {
      showAuthError((resp && resp.error) || "Verification failed");
      return;
    }

    hideAllAuthSteps();
    authStepResult.classList.remove("hidden");
    authResultMsg.textContent =
      "Authenticated! PID-SIWE correlation established. " +
      "Your browser identity is now cryptographically linked to your Pillar.";

    await checkStatus();
    setTimeout(hideAuthModal, 3000);
  } catch (e) {
    showAuthError(e.message);
  } finally {
    btnVerifySig.disabled = false;
    btnVerifySig.textContent = "Verify & Connect";
  }
});

function showAuthError(msg) {
  authError.textContent = msg;
  authError.classList.remove("hidden");
}

// --- Navigation ---

async function navigate(selector) {
  contentEl.innerHTML = '<p class="muted">Loading...</p>';

  const resp = await sendMessage({ type: "request", selector });

  if (!resp || !resp.ok) {
    const err = (resp && resp.error) || "Connection failed";
    contentEl.innerHTML = `<p class="error">${escapeHtml(err)}</p>`;
    return;
  }

  if (currentSelector !== selector) {
    history.push(currentSelector);
  }
  currentSelector = selector;
  btnBack.disabled = history.length === 0;

  updateBreadcrumb(selector);
  renderGopherMenu(resp.data);
}

function updateBreadcrumb(selector) {
  const parts = (selector || "/").split("/").filter(Boolean);
  let html = '<a href="#" data-selector="/">root</a>';
  let path = "";
  for (const part of parts) {
    path += "/" + part;
    html += ` / <a href="#" data-selector="${escapeHtml(path)}">${escapeHtml(part)}</a>`;
  }
  breadcrumb.innerHTML = html;

  breadcrumb.querySelectorAll("a").forEach((a) => {
    a.addEventListener("click", (e) => {
      e.preventDefault();
      navigate(a.dataset.selector);
    });
  });
}

// --- Gopher Menu Rendering ---

function renderGopherMenu(response) {
  if (!response || !response.data) {
    contentEl.innerHTML = '<p class="muted">Empty response</p>';
    return;
  }

  const raw = response.data;
  const lines = raw.split("\r\n");
  let html = "";

  for (const line of lines) {
    if (line === "." || line === "") continue;

    const type = line[0];
    const rest = line.substring(1);
    const fields = rest.split("\t");
    const display = fields[0] || "";
    const selector = fields[1] || "";
    const host = fields[2] || "";
    const port = fields[3] || "";

    switch (type) {
      case "i": // Info line
        html += `<div class="info">${escapeHtml(display)}</div>`;
        break;
      case "1": // Directory link
        html += `<div class="link"><a href="#" data-selector="${escapeHtml(selector)}" class="menu-link">${escapeHtml(display)}</a></div>`;
        break;
      case "0": // Text file
        html += `<div class="link"><a href="#" data-selector="${escapeHtml(selector)}" class="text-link">${escapeHtml(display)}</a></div>`;
        break;
      case "7": // Search
        html += `<div class="search"><span class="search-icon">&#128269;</span> ${escapeHtml(display)}</div>`;
        break;
      case "h": // HTML link
        if (selector.startsWith("URL:")) {
          const url = selector.substring(4);
          html += `<div class="link"><a href="${escapeHtml(url)}" target="_blank" rel="noopener" class="ext-link">${escapeHtml(display)} &#8599;</a></div>`;
        }
        break;
      default:
        html += `<div class="info">${escapeHtml(display)}</div>`;
    }
  }

  contentEl.innerHTML = html || '<p class="muted">No content</p>';

  // Attach navigation handlers to Gopher links
  contentEl.querySelectorAll("[data-selector]").forEach((a) => {
    a.addEventListener("click", (e) => {
      e.preventDefault();
      navigate(a.dataset.selector);
    });
  });
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

// --- Event Handlers ---

btnBack.addEventListener("click", () => {
  if (history.length > 0) {
    const prev = history.pop();
    currentSelector = prev;
    navigate(prev);
  }
});

btnRefresh.addEventListener("click", () => {
  navigate(currentSelector);
});

btnConnect.addEventListener("click", async () => {
  await sendMessage({ type: "connect" });
  setTimeout(async () => {
    const connected = await checkStatus();
    if (connected) navigate(currentSelector || "");
  }, 500);
});

// --- Tab Switching ---

document.querySelectorAll(".tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    // Deactivate all tabs and panels
    document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach((p) => p.classList.add("hidden"));

    // Activate clicked tab
    btn.classList.add("active");
    const panel = document.getElementById("tab-" + btn.dataset.tab);
    if (panel) panel.classList.remove("hidden");

    // Load services data when switching to Services tab
    if (btn.dataset.tab === "services") {
      loadServices();
    }
  });
});

// --- Services Tab ---

async function loadServices() {
  const list = document.getElementById("services-list");
  const installDiv = document.getElementById("services-install");
  const installCmd = document.getElementById("install-cmd");

  try {
    // Fetch /health/services via background sendRequest
    const resp = await sendMessage({ type: "request", selector: "/health/services" });
    if (!resp || !resp.ok || !resp.data) {
      list.innerHTML = '<p class="muted">Could not load service status.</p>';
      return;
    }

    // The response data contains the JSON inside a Gopher response wrapper
    const rawData = typeof resp.data === "string" ? resp.data : (resp.data.data || resp.data);
    // Strip Gopher terminator
    const jsonStr = (typeof rawData === "string" ? rawData : JSON.stringify(rawData))
      .replace(/\r?\n\.\s*$/, "");
    const statuses = JSON.parse(jsonStr);

    list.innerHTML = "";
    const missingCmds = [];

    for (const s of statuses) {
      const row = document.createElement("div");
      row.className = "service-row";
      const icon = s.available ? "\u2713" : (s.install_cmd ? "\u25CB" : "\u2717");
      const iconClass = s.available ? "ok" : "missing";
      row.innerHTML =
        '<span class="service-icon ' + iconClass + '">' + escapeHtml(icon) + "</span>" +
        '<span class="service-name">' + escapeHtml(s.name) + "</span>" +
        (s.version ? '<span class="service-version">v' + escapeHtml(s.version) + "</span>" : "") +
        (!s.available && s.install_cmd ? '<span class="service-cmd">' + escapeHtml(s.install_cmd) + "</span>" : "");
      list.appendChild(row);
      if (!s.available && s.install_cmd && s.install_cmd.startsWith("pip")) {
        missingCmds.push(s.install_cmd);
      }
    }

    if (missingCmds.length > 0) {
      // Combine pip installs
      const packages = missingCmds
        .map((c) => c.replace("pip install ", ""))
        .join(" ");
      installCmd.textContent = "pip install " + packages;
      installDiv.classList.remove("hidden");

      document.getElementById("btn-copy-install").onclick = () => {
        navigator.clipboard.writeText(installCmd.textContent);
      };
    } else {
      installDiv.classList.add("hidden");
    }
  } catch (e) {
    list.innerHTML = '<p class="muted">Could not load service status.</p>';
  }
}

// --- Init ---

(async function init() {
  const connected = await checkStatus();
  if (connected) {
    navigate("");
  } else {
    contentEl.innerHTML =
      '<p class="muted">Not connected. Click Connect or start your Pillar node.</p>';
  }
})();

// Listen for status updates from background
chrome.runtime.onMessage.addListener((msg) => {
  if (msg.type === "ws-status") {
    updateStatusDot(msg.connected);
    updateAuthDisplay(msg.connected, msg.identity, msg.session);
  }
});
