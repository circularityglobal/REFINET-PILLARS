REFInet Browser Extension
==========================

Browse Gopherspace from any web browser.

The REFInet browser extension connects to your local Pillar via
WebSocket (ws://localhost:7075) and provides a graphical interface
for navigating Gopher menus, authenticating with your EVM wallet,
and browsing the REFInet mesh.


FEATURES
--------

  - Gopher-to-HTML bridge: renders Gopher menus as clickable HTML
  - SIWE authentication: link your wallet to your Pillar's PID
  - Ed25519 signature verification on all responses
  - Session persistence across browser restarts
  - EIP-6963 multi-wallet discovery (MetaMask, Rabby, etc.)
  - REFInet Network tab for browsing remote Pillars
  - window.refinet API for web page integration


HOW IT WORKS
------------

The extension runs a background service worker that maintains a
persistent WebSocket connection to your local Pillar. When you
navigate to a Gopher address, the extension:

  1. Sends the selector to your Pillar via WebSocket
  2. The Pillar fetches the content (local or remote)
  3. The response is signed with the Pillar's Ed25519 key
  4. The extension verifies the signature
  5. Gopher menu items are rendered as HTML links

No HTTP server is added to the Pillar. The browser extension IS the
HTTP bridge — it translates between Gopher protocol and the browser.


REQUIREMENTS
------------

  - A running REFInet Pillar on localhost (port 7075 for WebSocket)
  - Chrome/Chromium or Firefox
  - An EVM wallet (optional, for authentication)


INSTALL
-------

  Chrome: Chrome Web Store (search "REFInet")
  Firefox: Firefox Add-ons (search "REFInet")
  Source: browser-extension/ directory in the repository


VERSION
-------

Current: v0.4.0 (Manifest V3)

Source: https://github.com/circularityglobal/REFINET-PILLARS/tree/main/browser-extension
