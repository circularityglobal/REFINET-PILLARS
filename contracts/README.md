# PillarStaking

The on-chain half of REFInet Pillar admission, deployed on XDC.

| | |
|---|---|
| Token | REFI `0x2D010d707da973E194e41D7eA52617f8F969BD23` (XDC mainnet, chain 50; 18 decimals; LayerZero OFT, no transfer fee) |
| Threshold | 100,000 REFI staked per Pillar ID; more is allowed |
| Inactivity fee | 1 REFI per inactive UTC day, never below 99,999 REFI |
| Cooldown | 14 days from `requestUnstake` to `withdraw` |

## The rules

- `isActive(pid)` is `stake >= 100,000 REFI && no unstake pending`. Pillars read
  it to admit peers; reward accounting reads it to decide who earns.
- The oracle (`ORACLE_ROLE`, the liveness monitor) calls
  `recordInactive(pids, day)` once per completed day. Each record costs
  `min(1 REFI, stake - 99,999 REFI)`. A Pillar at exactly 100,000 loses 1 REFI,
  drops to 99,999 and pauses; further inactive days cost nothing. A 1 REFI
  top-up resumes it. Stake above 100,000 is a buffer of one day per REFI.
- Every recorded day emits `InactiveDay(pid, day, fee, staked)`, fee or not.
  Rewards are never paid for a day that has one.
- Records are idempotent per (pid, day), limited to the last 7 completed days,
  and never for the registration day. A day is **always** recorded, whatever
  the Pillar's state when the oracle runs: an operator who could suppress the
  record — by sitting in the unstaking state, or sandwiching the oracle's call
  with `requestUnstake`/`cancelUnstake` — would erase the very evidence that
  rewards are withheld on.
- The **fee** is judged for the day itself: a day inside the Pillar's latest
  unstaking stretch (from `requestUnstake` until `cancelUnstake`, or open while
  the request stands) is recorded and not charged, because the Pillar was
  deactivated and earning nothing. Cancelling does not make those days
  chargeable. Only the latest stretch is kept, so an operator who toggles twice
  within the 7-day backfill window keeps only the newer one.
- `requestUnstake` deactivates at once; `withdraw` returns the whole stake
  after 14 days and frees the PID. No role can block it.
- The contract is the mesh directory: `pidsPage`, `endpointOf`, `operatorOf`.
  An endpoint is the domain where the Pillar serves `/.well-known/refinet.json`.
  A withdrawal empties its slot (reads as zero) and never moves another PID
  into it, so a node paging the directory across several calls cannot miss a
  Pillar that stayed. `pillarCount()` is the paging bound, not a population.
- **A registration authenticates nothing.** A PID is SHA-256 of an Ed25519
  public key, which this chain cannot verify, so anyone may register any PID
  and the first caller wins. That buys an impostor only denial: every Pillar
  checks a peer's own signed identity document against `operatorOf(pid)` before
  trusting it, so a registration whose key the registrant does not hold is
  never admitted to the mesh. The stake prices the nuisance; it does not prove
  ownership. A squatted PID is answered by generating a new key.
- Not upgradeable. A successor would be deployed beside it; Pillars accept
  stake in any contract listed in their config.

## Build and test

```bash
forge install OpenZeppelin/openzeppelin-contracts@v5.0.2 foundry-rs/forge-std@v1.16.2 --no-git
forge test
```

`evm_version = "paris"` keeps the bytecode free of PUSH0/MCOPY for XDC.

## Deploy

```bash
# Apothem first. REFI is not on Apothem: deploy a test token there.
REFI_TOKEN=0x... STAKING_ADMIN=0x<multisig> FEE_RECIPIENT=0x<rewards pool> \
  forge script script/DeployPillarStaking.s.sol --rpc-url apothem --broadcast --private-key $KEY
```

## Known limits (v1)

- `recordInactive` costs ~27k gas per chargeable Pillar, so the oracle shards
  large meshes across transactions and retries a failed shard inside the
  7-day window.
- Stake above the threshold can only be reduced by unstaking in full and
  re-registering after the cooldown; there is no partial withdrawal. An oracle
  that recorded every single day would erode a buffer at 365 REFI a year.
- `inactiveRecorded` is not cleared when a PID is withdrawn. It cannot affect a
  later registration (the registration-day guard shadows any stale day), but it
  should not be read off-chain as "this Pillar was down on day D" without
  checking `registeredAt`.

The contract holds operator funds. Have it audited before a mainnet deploy.
