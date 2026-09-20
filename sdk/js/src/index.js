// @refinet/pillar — verify a REFInet Pillar from Node (>= 20) or a browser.
//
// Everything a Pillar says is signed with its Ed25519 key, and its Pillar ID
// (PID) is SHA-256 of that key. Nothing here trusts the network, a proxy or
// a CDN in between: an answer that does not verify is reported as such.

const te = new TextEncoder();

const DOMAIN_RESPONSE = "REFINET-RESPONSE-v1";
const DOMAIN_WELL_KNOWN = "REFINET-WELL-KNOWN-v1";
export const WELL_KNOWN_PATH = "/.well-known/refinet.json";
export const SCHEMA = "refinet-pillar/1";

// PillarStaking on XDC
export const XDC_CHAIN_ID = 50;
export const XDC_RPC = "https://rpc.xinfin.network";
export const APOTHEM_RPC = "https://rpc.apothem.network";
export const REFI_TOKEN = "0x2D010d707da973E194e41D7eA52617f8F969BD23";
export const THRESHOLD_UNITS = 100_000n * 10n ** 18n;

const subtle = () => {
  const s = globalThis.crypto?.subtle;
  if (!s) throw new Error("WebCrypto is not available (Node >= 20 or a modern browser is required)");
  return s;
};

export function hexToBytes(hex) {
  const clean = String(hex).replace(/^0x/, "");
  if (clean.length % 2 || /[^0-9a-fA-F]/.test(clean)) throw new Error("not hex");
  const out = new Uint8Array(clean.length / 2);
  for (let i = 0; i < out.length; i++) out[i] = parseInt(clean.slice(2 * i, 2 * i + 2), 16);
  return out;
}

export function bytesToHex(bytes) {
  return Array.from(new Uint8Array(bytes), (b) => b.toString(16).padStart(2, "0")).join("");
}

export async function sha256Hex(data) {
  const bytes = typeof data === "string" ? te.encode(data) : data;
  return bytesToHex(await subtle().digest("SHA-256", bytes));
}

export async function verifyEd25519(signatureHex, messageBytes, publicKeyHex) {
  try {
    const key = await subtle().importKey("raw", hexToBytes(publicKeyHex), { name: "Ed25519" }, false, ["verify"]);
    return await subtle().verify({ name: "Ed25519" }, key, hexToBytes(signatureHex), messageBytes);
  } catch {
    return false;
  }
}

export async function pidMatchesKey(pid, publicKeyHex) {
  try {
    return (await sha256Hex(hexToBytes(publicKeyHex))) === String(pid).toLowerCase();
  } catch {
    return false;
  }
}

/** Bytes a domain-separated signature covers: domain || fields joined by "\n". */
export function domainPreimage(domain, ...fields) {
  return te.encode(domain + fields.map(String).join("\n"));
}

/** Deterministic JSON matching the Pillar's canonical_json (sorted keys, no spaces). */
export function canonicalJson(value) {
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) return "[" + value.map(canonicalJson).join(",") + "]";
  return "{" + Object.keys(value).sort(compareCodePoints).map((k) => JSON.stringify(k) + ":" + canonicalJson(value[k])).join(",") + "}";
}

/** Order strings by Unicode code point, matching Python's sort_keys.
 *  JavaScript's default sort compares UTF-16 code units, which puts a
 *  surrogate pair after U+FFFF — the opposite order — so a document with
 *  astral-plane keys would hash differently on each side. */
export function compareCodePoints(a, b) {
  const x = Array.from(a), y = Array.from(b);
  for (let i = 0; i < Math.min(x.length, y.length); i++) {
    const d = x[i].codePointAt(0) - y[i].codePointAt(0);
    if (d !== 0) return d;
  }
  return x.length - y.length;
}

export function normalizeDomain(value) {
  return String(value || "").trim().toLowerCase().replace(/^[a-z]+:\/\//, "").split("/")[0].replace(/\.$/, "");
}

// ---------------------------------------------------------------------------
// Signed answers from the HTTP gateway (GET https://<pillar>/g/<selector>)
// ---------------------------------------------------------------------------

/**
 * Verify one gateway answer. `body` is the exact response text; `headers` a
 * Headers object or a plain object of the X-Refinet-* headers.
 */
export async function verifyAnswer(body, headers) {
  const get = (name) => (typeof headers.get === "function" ? headers.get(name) : headers[name] ?? headers[name.toLowerCase()]);
  const pid = get("X-Refinet-Pid") || "";
  const pubkey = get("X-Refinet-Pubkey") || "";
  const bodyBytes = typeof body === "string" ? te.encode(body) : body;
  const hash = await sha256Hex(bodyBytes);
  const result = {
    pid,
    selector: get("X-Refinet-Selector"),
    time: get("X-Refinet-Time") ? Number(get("X-Refinet-Time")) : null,
    pidValid: await pidMatchesKey(pid, pubkey),
    hashValid: get("X-Refinet-Hash") === hash,
    bodySignatureValid: await verifyEd25519(get("X-Refinet-Sig") || "", bodyBytes, pubkey),
    envelopeValid: null,
  };
  if (get("X-Refinet-V") === "1") {
    result.envelopeValid = await verifyEd25519(
      get("X-Refinet-Sig1") || "",
      domainPreimage(DOMAIN_RESPONSE, pid, result.selector ?? "", result.time, hash),
      pubkey,
    );
  }
  // The envelope is required. Its fields travel as detached headers, so an
  // intermediary could otherwise strip X-Refinet-V and X-Refinet-Sig1 and
  // leave the body-only signature, which says nothing about WHICH selector
  // was answered or when. Every Pillar serving this gateway signs one.
  result.valid = result.pidValid && result.hashValid && result.bodySignatureValid && result.envelopeValid === true;
  return result;
}

/** Strip the Gopher terminator ("\r\n.\r\n") from a verified body. */
export function gopherText(body) {
  return body.replace(/\r?\n\.\r?\n?$/, "").replace(/\.$/, "").trimEnd();
}

/**
 * A client for one Pillar's HTTP gateway.
 *
 *   const pillar = createPillarClient("https://pillar.example.com", { pid });
 *   const status = await pillar.json("/status.json");
 *
 * Pass `pid` to also require that every answer comes from that Pillar.
 */
export function createPillarClient(baseUrl, { pid = null, fetch: f = globalThis.fetch } = {}) {
  const base = String(baseUrl).replace(/\/+$/, "");
  async function get(selector = "/") {
    const path = selector.startsWith("/") ? selector : "/" + selector;
    const res = await f(`${base}/g${path}`);
    const body = await res.text();
    if (!res.ok) throw new Error(`Pillar answered HTTP ${res.status}: ${body.slice(0, 200)}`);
    const check = await verifyAnswer(body, res.headers);
    if (!check.valid) throw new Error(`Pillar answer for ${path} does not verify`);
    if (check.selector !== path) throw new Error(`Asked for ${path}, got an answer signed for ${check.selector}`);
    if (pid && check.pid !== pid.toLowerCase()) throw new Error(`Answer came from ${check.pid}, not ${pid}`);
    return { body, text: gopherText(body), ...check };
  }
  return {
    get,
    async json(selector) {
      return JSON.parse((await get(selector)).text);
    },
    async wellKnown() {
      const res = await f(`${base}${WELL_KNOWN_PATH}`);
      return res.json();
    },
  };
}

// ---------------------------------------------------------------------------
// Domain proof: https://<domain>/.well-known/refinet.json
// ---------------------------------------------------------------------------

export async function verifyWellKnown(doc, { pid = null, domain = null, maxAgeSec = null } = {}) {
  try {
    if (!doc || typeof doc !== "object" || doc.schema !== SCHEMA) return { valid: false, reason: "not a refinet-pillar/1 document" };
    if (!(await pidMatchesKey(doc.pid, doc.public_key))) return { valid: false, reason: "public key does not hash to pid" };
    const { signature, ...body } = doc;
    const digest = await sha256Hex(canonicalJson(body));
    if (!(await verifyEd25519(signature, domainPreimage(DOMAIN_WELL_KNOWN, digest), doc.public_key))) {
      return { valid: false, reason: "signature does not verify" };
    }
    if (pid && doc.pid !== pid.toLowerCase()) return { valid: false, reason: "document names a different PID" };
    if (maxAgeSec !== null) {
      const age = Date.now() / 1000 - Number(doc.issued_at || 0);
      if (!(age <= maxAgeSec)) return { valid: false, reason: `document is ${Math.round(age / 86400)} days old` };
    }
    if (domain) {
      const want = normalizeDomain(domain);
      const claimed = new Set([doc.domain, ...(doc.linked_domains || [])]);
      if (!claimed.has(want)) return { valid: false, reason: `document does not claim ${want}` };
    }
    return { valid: true, reason: "valid", pid: doc.pid };
  } catch (e) {
    return { valid: false, reason: `malformed document: ${e.message}` };
  }
}

export async function fetchWellKnown(domain, { fetch: f = globalThis.fetch } = {}) {
  const url = `https://${normalizeDomain(domain)}${WELL_KNOWN_PATH}`;
  let res;
  try {
    res = await f(url, { redirect: "error" });
  } catch (e) {
    throw new Error(`${url} unreachable: ${e.cause?.code || e.cause?.message || e.message}`);
  }
  if (!res.ok) throw new Error(`${url} answered HTTP ${res.status}`);
  return res.json();
}

// ---------------------------------------------------------------------------
// PillarStaking reads (plain JSON-RPC eth_call)
// ---------------------------------------------------------------------------

const SEL = {
  isActive: "5c36901c",
  operatorOf: "63ea4ab2",
  endpointOf: "ab091871",
  stakeOf: "07177c9c",
};

async function ethCall(rpc, to, data, f) {
  const res = await f(rpc, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "eth_call", params: [{ to, data }, "latest"] }),
  });
  const reply = await res.json();
  if (reply.error) throw new Error(`RPC error: ${reply.error.message || JSON.stringify(reply.error)}`);
  return reply.result.replace(/^0x/, "");
}

function decodeString(hex) {
  const offset = parseInt(hex.slice(0, 64), 16) * 2;
  const len = parseInt(hex.slice(offset, offset + 64), 16);
  return new TextDecoder().decode(hexToBytes(hex.slice(offset + 64, offset + 64 + len * 2)));
}

/** A Pillar's standing in one PillarStaking contract. */
export async function stakeStatus(contract, pid, { rpc = XDC_RPC, fetch: f = globalThis.fetch } = {}) {
  const arg = String(pid).toLowerCase().replace(/^0x/, "");
  if (!/^[0-9a-f]{64}$/.test(arg)) throw new Error("not a PID");
  const call = (sel) => ethCall(rpc, contract, "0x" + sel + arg, f);
  const [active, operator, endpoint, stake] = await Promise.all([
    call(SEL.isActive), call(SEL.operatorOf), call(SEL.endpointOf), call(SEL.stakeOf),
  ]);
  const op = "0x" + operator.slice(24, 64);
  return {
    active: BigInt("0x" + active) !== 0n,
    registered: BigInt(op) !== 0n,
    operator: op,
    endpoint: decodeString(endpoint),
    stakeUnits: BigInt("0x" + stake),
  };
}

export function formatRefi(units) {
  const whole = units / 10n ** 18n;
  const frac = units % 10n ** 18n;
  return frac === 0n ? whole.toLocaleString("en-US") : `${whole.toLocaleString("en-US")}.${frac.toString().padStart(18, "0").replace(/0+$/, "")}`;
}
