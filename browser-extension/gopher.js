/**
 * REFInet Gopher Protocol — Shared Parser & Utilities
 *
 * Parses RFC 1436 Gopher menu format and provides URL utilities
 * for routing gopher:// addresses through the WebSocket bridge.
 */

/**
 * Parse raw Gopher menu text into structured entries.
 * @param {string} rawText - Raw Gopher menu response (CRLF-delimited)
 * @returns {Array<{type: string, display: string, selector: string, host: string, port: string}>}
 */
function parseGopherMenu(rawText) {
  if (!rawText) return [];

  const lines = rawText.split("\r\n");
  const entries = [];

  for (const line of lines) {
    if (line === "." || line === "") continue;
    // Skip signature block
    if (line.startsWith("---BEGIN REFINET SIGNATURE---")) break;

    const type = line[0];
    const rest = line.substring(1);
    const fields = rest.split("\t");

    entries.push({
      type,
      display: fields[0] || "",
      selector: fields[1] || "",
      host: fields[2] || "",
      port: fields[3] || "",
    });
  }

  return entries;
}

/**
 * Parse a gopher:// URL into its components.
 * Format: gopher://host[:port][/type[/selector]]
 * @param {string} url - A gopher:// URL
 * @returns {{host: string, port: number, type: string, selector: string} | null}
 */
function gopherUrlToSelector(url) {
  try {
    const match = url.match(/^gopher:\/\/([^/:]+)(?::(\d+))?(\/.*)?$/);
    if (!match) return null;

    const host = match[1];
    const port = match[2] ? parseInt(match[2], 10) : 70;
    const path = match[3] || "/";

    // First char after leading "/" is the item type
    let type = "1"; // default to directory
    let selector = "/";

    if (path.length > 1) {
      type = path[1];
      selector = path.substring(2) || "/";
      if (!selector.startsWith("/")) selector = "/" + selector;
    }

    return { host, port, type, selector };
  } catch (e) {
    return null;
  }
}

/**
 * Convert a selector + host + port back to a gopher:// URL.
 * @param {string} selector
 * @param {string} host
 * @param {number} port
 * @param {string} [type="1"]
 * @returns {string}
 */
function selectorToGopherUrl(selector, host, port, type) {
  type = type || "1";
  port = port || 70;
  const portStr = port === 70 ? "" : ":" + port;
  const sel = selector.startsWith("/") ? selector.substring(1) : selector;
  return `gopher://${host}${portStr}/${type}${sel}`;
}

/**
 * Check if a host:port refers to the local Pillar.
 * @param {string} host
 * @param {number} port
 * @returns {boolean}
 */
function isLocalPillar(host, port) {
  const localHosts = ["localhost", "127.0.0.1", "::1"];
  const pillarPorts = [70, 7070];
  return localHosts.includes(host) && pillarPorts.includes(port);
}
