#!/usr/bin/env node
// refinet-pillar — add a REFInet Pillar to your app before you go live.
//
//   npx @refinet/pillar init --pillar-domain pillar.example.com --app-domain example.com
//   npx @refinet/pillar deploy --ssh root@203.0.113.7
//   npx @refinet/pillar bind --ssh root@203.0.113.7 --address 0xYourWallet
//   npx @refinet/pillar stake
//   npx @refinet/pillar doctor

import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { spawnSync } from "node:child_process";
import { createInterface } from "node:readline/promises";
import { promises as dns } from "node:dns";

import {
  APOTHEM_RPC, REFI_TOKEN, THRESHOLD_UNITS, WELL_KNOWN_PATH, XDC_CHAIN_ID, XDC_RPC,
  createPillarClient, fetchWellKnown, formatRefi, normalizeDomain, stakeStatus, verifyWellKnown,
} from "../src/index.js";

const CONFIG_FILE = "refinet.config.json";
const REPO_RAW = "https://raw.githubusercontent.com/circularityglobal/REFINET-PILLARS";
const REMOTE_DIR = "/opt/refinet-pillar/deploy/vps";

// ---------------------------------------------------------------------------
// Small helpers
// ---------------------------------------------------------------------------
function parseArgs(argv) {
  const out = { _: [] };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a.startsWith("--")) {
      const key = a.slice(2).replace(/-([a-z])/g, (_, c) => c.toUpperCase());
      const next = argv[i + 1];
      out[key] = next === undefined || next.startsWith("--") ? true : (i++, next);
    } else out._.push(a);
  }
  return out;
}

const ok = (msg) => console.log(`  ✓ ${msg}`);
const bad = (msg) => console.log(`  ✗ ${msg}`);
const note = (msg) => console.log(`    ${msg}`);

function loadConfig() {
  if (!existsSync(CONFIG_FILE)) {
    console.error(`No ${CONFIG_FILE} here. Run: npx @refinet/pillar init`);
    process.exit(1);
  }
  return JSON.parse(readFileSync(CONFIG_FILE, "utf8"));
}

async function ask(question, fallback = "") {
  if (!process.stdin.isTTY) return fallback;
  const rl = createInterface({ input: process.stdin, output: process.stdout });
  const answer = (await rl.question(`${question}${fallback ? ` [${fallback}]` : ""}: `)).trim();
  rl.close();
  return answer || fallback;
}

function shQuote(s) {
  return `'${String(s).replace(/'/g, `'\\''`)}'`;
}

const SSH_DEST = /^(?:[A-Za-z0-9._-]+@)?[A-Za-z0-9._-]+$/;

function ssh(host, command, { capture = false } = {}) {
  // refinet.config.json travels in the repo, so its "ssh" value is not
  // trusted to be a destination: "-oProxyCommand=…" would run locally.
  if (!SSH_DEST.test(String(host))) {
    throw new Error(`Not an ssh destination: ${host} (expected user@host)`);
  }
  const r = spawnSync("ssh", ["--", host, command], { stdio: capture ? ["inherit", "pipe", "inherit"] : "inherit", encoding: "utf8" });
  if (r.status !== 0) throw new Error(`ssh ${host} exited ${r.status}`);
  return r.stdout;
}

function stakingRpc(cfg) {
  return cfg.staking?.rpc || (Number(cfg.staking?.chainId) === 51 ? APOTHEM_RPC : XDC_RPC);
}

// ---------------------------------------------------------------------------
// init — record the pairing and make the app serve the Pillar's domain proof
// ---------------------------------------------------------------------------
function wireVercel(pillarDomain) {
  const path = "vercel.json";
  const cfg = existsSync(path) ? JSON.parse(readFileSync(path, "utf8")) : {};
  cfg.rewrites = cfg.rewrites || [];
  if (cfg.rewrites.some((r) => r.source === WELL_KNOWN_PATH)) return `${path} already serves ${WELL_KNOWN_PATH}`;
  // First, so no catch-all rewrite shadows it
  cfg.rewrites.unshift({ source: WELL_KNOWN_PATH, destination: `https://${pillarDomain}${WELL_KNOWN_PATH}` });
  writeFileSync(path, JSON.stringify(cfg, null, 2) + "\n");
  return `${path}: ${WELL_KNOWN_PATH} proxied to the Pillar`;
}

function wireNetlify(pillarDomain) {
  const line = `${WELL_KNOWN_PATH}  https://${pillarDomain}${WELL_KNOWN_PATH}  200!`;
  // Netlify applies _redirects before netlify.toml, so an SPA catch-all in
  // _redirects would shadow a rule added to netlify.toml.
  for (const dir of [".", "public", "static", "website"]) {
    const path = resolve(dir, "_redirects");
    if (existsSync(path)) {
      const text = readFileSync(path, "utf8");
      if (text.includes(WELL_KNOWN_PATH)) return `${dir}/_redirects already serves ${WELL_KNOWN_PATH}`;
      writeFileSync(path, line + "\n" + text);
      return `${dir}/_redirects: ${WELL_KNOWN_PATH} proxied to the Pillar`;
    }
  }
  const path = "netlify.toml";
  const text = existsSync(path) ? readFileSync(path, "utf8") : "";
  if (text.includes(WELL_KNOWN_PATH)) return `${path} already serves ${WELL_KNOWN_PATH}`;
  const block = `[[redirects]]\n  from = "${WELL_KNOWN_PATH}"\n  to = "https://${pillarDomain}${WELL_KNOWN_PATH}"\n  status = 200\n  force = true\n\n`;
  const at = text.indexOf("[[redirects]]");
  writeFileSync(path, at >= 0 ? text.slice(0, at) + block + text.slice(at) : text + (text && !text.endsWith("\n") ? "\n\n" : "") + block);
  return `${path}: ${WELL_KNOWN_PATH} proxied to the Pillar`;
}

function detectHost() {
  if (existsSync("vercel.json") || existsSync(".vercel")) return "vercel";
  if (existsSync("netlify.toml") || existsSync(".netlify")) return "netlify";
  if (existsSync("package.json")) {
    const pkg = JSON.parse(readFileSync("package.json", "utf8"));
    const deps = { ...pkg.dependencies, ...pkg.devDependencies };
    if (deps.next) return "vercel";
  }
  return null;
}

async function cmdInit(args) {
  const appDomain = normalizeDomain(args.appDomain || (await ask("Your app's domain", "example.com")));
  const pillarDomain = normalizeDomain(args.pillarDomain || (await ask("Domain for the Pillar", `pillar.${appDomain}`)));
  const cfg = {
    appDomain,
    appOrigin: args.appOrigin || `https://${appDomain}`,
    pillarDomain,
    ssh: args.ssh || "",
    staking: {
      chainId: Number(args.chainId || XDC_CHAIN_ID),
      contract: args.stakingContract || "",
      token: REFI_TOKEN,
    },
  };
  writeFileSync(CONFIG_FILE, JSON.stringify(cfg, null, 2) + "\n");
  console.log(`\n  Wrote ${CONFIG_FILE}`);

  const host = args.host || detectHost();
  if (host === "vercel") console.log("  " + wireVercel(pillarDomain));
  else if (host === "netlify") console.log("  " + wireNetlify(pillarDomain));
  else {
    console.log(`  Could not tell where the app is hosted. Serve this from your app so it claims the Pillar:`);
    note(`${WELL_KNOWN_PATH}  ->  proxy to https://${pillarDomain}${WELL_KNOWN_PATH}`);
    note(`(or rerun with --host vercel | --host netlify)`);
  }

  if (existsSync("package.json")) {
    const pkg = JSON.parse(readFileSync("package.json", "utf8"));
    pkg.scripts = pkg.scripts || {};
    if (!pkg.scripts["pillar:doctor"]) {
      pkg.scripts["pillar:doctor"] = "refinet-pillar doctor";
      writeFileSync("package.json", JSON.stringify(pkg, null, 2) + "\n");
      console.log(`  package.json: added "pillar:doctor"`);
    }
  }

  console.log(`
  Next:
    1. Point an A record for ${pillarDomain} at a VPS, then deploy the Pillar:
         npx @refinet/pillar deploy --ssh root@<vps-ip>
    2. Bind the wallet you will stake from:
         npx @refinet/pillar bind --ssh root@<vps-ip> --address 0xYourWallet
    3. Stake 100,000 REFI for the Pillar:   npx @refinet/pillar stake
    4. Before you go live:                   npx @refinet/pillar doctor
`);
}

// ---------------------------------------------------------------------------
// deploy / bind — run the VPS installer and the binding over SSH
// ---------------------------------------------------------------------------
async function cmdDeploy(args) {
  const cfg = loadConfig();
  const host = args.ssh || cfg.ssh;
  if (!host) throw new Error("Pass --ssh root@<vps-ip> (or set \"ssh\" in refinet.config.json)");
  const ref = args.ref || "main";
  const env = [
    `REFINET_REF=${shQuote(ref)}`,
    `APP_ORIGIN=${shQuote(cfg.appOrigin || "")}`,
    `APP_DOMAIN=${shQuote(cfg.appDomain || "")}`,
    `STAKING_CONTRACT=${shQuote(cfg.staking?.contract || "")}`,
  ].join(" ");
  const url = `${REPO_RAW}/${ref}/deploy/vps/install.sh`;
  console.log(`\n  Installing the Pillar on ${host} for ${cfg.pillarDomain}\n`);
  ssh(host, `curl -fsSL ${shQuote(url)} | sudo ${env} bash -s -- ${shQuote(cfg.pillarDomain)}`);
  if (!cfg.ssh) {
    cfg.ssh = host;
    writeFileSync(CONFIG_FILE, JSON.stringify(cfg, null, 2) + "\n");
  }
}

async function cmdBind(args) {
  const cfg = loadConfig();
  const host = args.ssh || cfg.ssh;
  const address = args.address;
  const chain = Number(args.chain || cfg.staking?.chainId || XDC_CHAIN_ID);
  if (!host || !/^0x[0-9a-fA-F]{40}$/.test(address || "")) {
    throw new Error("usage: bind --ssh root@<vps-ip> --address 0xYourWallet [--chain 50]");
  }
  const exec = `cd ${REMOTE_DIR} && sudo docker compose exec -T -u refinet pillar python3 pillar.py identity`;
  const message = ssh(host, `${exec} challenge --address ${address} --chain ${chain} --quiet`, { capture: true });
  console.log(`\n  Sign this message with ${address} (personal_sign), exactly as shown:\n`);
  console.log("  " + "-".repeat(62));
  for (const line of message.replace(/\n$/, "").split("\n")) console.log("  " + line);
  console.log("  " + "-".repeat(62));
  const signature = args.signature || (await ask("\n  Paste the signature (0x...)"));
  if (!/^0x[0-9a-fA-F]{130}$/.test(signature)) throw new Error("That is not a 65-byte signature");
  ssh(host, `${exec} rebind --address ${address} --chain ${chain} --signature ${signature}`);
}

// ---------------------------------------------------------------------------
// stake — what to send, for this Pillar
// ---------------------------------------------------------------------------
async function cmdStake() {
  const cfg = loadConfig();
  const doc = await fetchWellKnown(cfg.pillarDomain);
  const check = await verifyWellKnown(doc, { domain: cfg.pillarDomain });
  if (!check.valid) throw new Error(`https://${cfg.pillarDomain}${WELL_KNOWN_PATH}: ${check.reason}`);
  const contract = cfg.staking?.contract || "<PillarStaking address>";
  const rpc = stakingRpc(cfg);
  console.log(`
  Pillar ID:  ${doc.pid}
  Endpoint:   ${cfg.pillarDomain}
  Stake:      100,000 REFI (more is a buffer: 1 REFI per offline day)

  From the wallet you bound, on XDC (chain ${cfg.staking?.chainId || XDC_CHAIN_ID}):

    cast send ${REFI_TOKEN} "approve(address,uint256)" ${contract} 100000ether --rpc-url ${rpc}
    cast send ${contract} "register(bytes32,uint256,string)" 0x${doc.pid} 100000ether "${cfg.pillarDomain}" --rpc-url ${rpc}

  Then: npx @refinet/pillar doctor
`);
}

// ---------------------------------------------------------------------------
// doctor — everything that must be true before going live
// ---------------------------------------------------------------------------
async function cmdDoctor(args) {
  const cfg = loadConfig();
  let failures = 0;
  const fail = (m, hint) => { failures++; bad(m); if (hint) note(hint); };
  console.log(`\n  REFInet Pillar check — ${cfg.pillarDomain}${cfg.appDomain ? ` for ${cfg.appDomain}` : ""}\n`);

  try {
    const addrs = await dns.resolve4(cfg.pillarDomain);
    ok(`${cfg.pillarDomain} resolves to ${addrs.join(", ")}`);
  } catch {
    fail(`${cfg.pillarDomain} does not resolve`, `Add an A record for ${cfg.pillarDomain} pointing at your VPS.`);
  }

  let pid = null;
  try {
    const doc = await fetchWellKnown(cfg.pillarDomain);
    const r = await verifyWellKnown(doc, { domain: cfg.pillarDomain });
    if (r.valid) { pid = doc.pid; ok(`Domain proof verifies (Pillar ${pid.slice(0, 16)}...)`); }
    else fail(`Domain proof: ${r.reason}`);
  } catch (e) {
    fail(`https://${cfg.pillarDomain}${WELL_KNOWN_PATH} unreachable (${e.message})`, "Is the Pillar deployed and Caddy's certificate issued?");
  }

  if (pid) {
    try {
      const status = await createPillarClient(`https://${cfg.pillarDomain}`, { pid }).json("/status.json");
      ok(`Gateway answers are signed by the Pillar (${status.pillar_name || "status ok"})`);
    } catch (e) {
      fail(`Gateway: ${e.message}`);
    }
  }

  if (cfg.appDomain && pid) {
    try {
      const doc = await fetchWellKnown(cfg.appDomain);
      const r = await verifyWellKnown(doc, { pid, domain: cfg.appDomain });
      if (r.valid) ok(`${cfg.appDomain} claims this Pillar`);
      else fail(`${cfg.appDomain} domain proof: ${r.reason}`, `Deploy the app with the ${WELL_KNOWN_PATH} rewrite (npx @refinet/pillar init).`);
    } catch (e) {
      fail(`${cfg.appDomain}${WELL_KNOWN_PATH} unreachable (${e.message})`, "Deploy the app with the rewrite that init added.");
    }
  }

  const contract = cfg.staking?.contract;
  if (!contract) {
    note("Staking contract not set in refinet.config.json — skipping the stake check.");
  } else if (pid) {
    try {
      const s = await stakeStatus(contract, pid, { rpc: stakingRpc(cfg) });
      if (!s.registered) fail("Not staked", "Run: npx @refinet/pillar stake");
      else {
        if (s.active) ok(`Staked ${formatRefi(s.stakeUnits)} REFI — active (reward distribution is not live yet)`);
        else fail(`Staked ${formatRefi(s.stakeUnits)} REFI — not active`,
          s.stakeUnits < THRESHOLD_UNITS
            ? `Top up ${formatRefi(THRESHOLD_UNITS - s.stakeUnits)} REFI, then stay up: readmission also needs 2 days with no inactive day recorded.`
            : "Either an unstake is pending, or an inactive day was recorded in the last 2 days — bring the Pillar up and it readmits itself.");
        if (normalizeDomain(s.endpoint) === cfg.pillarDomain) ok(`On-chain endpoint is ${s.endpoint}`);
        else fail(`On-chain endpoint is "${s.endpoint}", not ${cfg.pillarDomain}`, "Call setEndpoint from the staking wallet.");
        const identity = await createPillarClient(`https://${cfg.pillarDomain}`, { pid }).json("/identity/v3.json");
        // The wallet signature itself is verified by every Pillar; what is
        // checked here is that a binding exists for the staking wallet and
        // that its statement names THIS Pillar — the part a stale or
        // wrong-Pillar binding gets wrong, and the part that is cheap here.
        const statement = `I bind this wallet to REFINET Pillar ${pid}`;
        const binding = (identity.bindings || []).find(
          (b) => (b.evm_address || "").toLowerCase() === s.operator);
        if (!binding) {
          fail(`Staking wallet ${s.operator} has no binding on the Pillar`,
            `Run: npx @refinet/pillar bind --address ${s.operator}`);
        } else if (!(binding.siwe_message || "").includes(statement)) {
          fail(`The binding for ${s.operator} does not name this Pillar`,
            `Re-sign it: npx @refinet/pillar bind --address ${s.operator}`);
        } else {
          ok(`Staking wallet ${s.operator} is bound to the Pillar`);
        }
      }
    } catch (e) {
      fail(`Stake check failed (${e.message})`);
    }
  }

  console.log(failures ? `\n  ${failures} problem(s) to fix before going live.\n` : "\n  Ready to go live.\n");
  if (failures && !args.warnOnly) process.exit(1);
}

// ---------------------------------------------------------------------------
const HELP = `
  refinet-pillar — add a REFInet Pillar to your app before you go live

  init    --pillar-domain <d> --app-domain <d> [--staking-contract 0x..] [--host vercel|netlify]
  deploy  --ssh root@<vps-ip> [--ref main]        install the Pillar on a VPS
  bind    --ssh root@<vps-ip> --address 0x..      bind your staking wallet to the Pillar
  stake                                          print the approve + register transactions
  doctor  [--warn-only]                          check everything before going live
`;

const commands = { init: cmdInit, deploy: cmdDeploy, bind: cmdBind, stake: cmdStake, doctor: cmdDoctor };
const args = parseArgs(process.argv.slice(2));
const cmd = commands[args._[0]];
if (!cmd) {
  console.log(HELP);
  process.exit(args._[0] ? 1 : 0);
}
cmd(args).catch((e) => {
  console.error(`\n  ${e.message}\n`);
  process.exit(1);
});
