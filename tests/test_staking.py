"""PillarStaking reader: ABI encoding, standing, caching, directory."""

import pytest

from mesh import staking as st
from mesh.staking import StakingReader

CONTRACT = "0x" + "11" * 20
CONTRACT_2 = "0x" + "22" * 20
PID_A = "a" * 64
PID_B = "b" * 64
OPERATOR = "0x" + "ab" * 20


# ---------------------------------------------------------------------------
# ABI helpers for a fake contract
# ---------------------------------------------------------------------------
def _w(n: int) -> str:
    return format(n, "064x")


def abi_uint(n: int) -> str:
    return "0x" + _w(n)


def abi_address(a: str) -> str:
    return "0x" + a.lower().removeprefix("0x").rjust(64, "0")


def abi_string(s: str) -> str:
    raw = s.encode()
    padded = raw.hex().ljust(((len(raw) + 31) // 32) * 64, "0")
    return "0x" + _w(32) + _w(len(raw)) + padded


def abi_bytes32_array(items: list[str]) -> str:
    return "0x" + _w(32) + _w(len(items)) + "".join(items)


class FakeChain:
    """A JSON-RPC transport backed by in-memory PillarStaking state."""

    def __init__(self):
        # contract -> pid -> dict(active, operator, endpoint, stake)
        self.state: dict[str, dict[str, dict]] = {CONTRACT: {}, CONTRACT_2: {}}
        # Directory slots, including the zeros a withdrawal leaves behind
        self.slots: dict[str, list[str]] = {CONTRACT: [], CONTRACT_2: []}
        self.calls = 0
        self.fail = False

    def add(self, pid, contract=CONTRACT, active=True, operator=OPERATOR,
            endpoint="pillar.example.com", stake=100_000 * 10**18):
        self.state[contract][pid] = dict(active=active, operator=operator,
                                         endpoint=endpoint, stake=stake)
        self.slots[contract].append(pid)

    def withdraw(self, pid, contract=CONTRACT):
        """Free the PID and empty its slot, as the contract does."""
        del self.state[contract][pid]
        self.slots[contract][self.slots[contract].index(pid)] = "0" * 64

    def __call__(self, url, payload):
        self.calls += 1
        if self.fail:
            raise OSError("rpc down")
        call = payload["params"][0]
        contract, data = call["to"], call["data"].removeprefix("0x")
        sel, args = data[:8], data[8:]
        pillars = self.state[contract]
        if sel == st.SEL_PILLAR_COUNT:
            return {"result": abi_uint(len(self.slots[contract]))}
        if sel == st.SEL_PIDS_PAGE:
            offset, limit = int(args[:64], 16), int(args[64:128], 16)
            return {"result": abi_bytes32_array(self.slots[contract][offset:offset + limit])}
        p = pillars.get(args[:64])
        if sel == st.SEL_IS_ACTIVE:
            return {"result": abi_uint(1 if p and p["active"] else 0)}
        if sel == st.SEL_OPERATOR_OF:
            return {"result": abi_address(p["operator"] if p else "0x" + "00" * 20)}
        if sel == st.SEL_ENDPOINT_OF:
            return {"result": abi_string(p["endpoint"] if p else "")}
        if sel == st.SEL_STAKE_OF:
            return {"result": abi_uint(p["stake"] if p else 0)}
        return {"error": {"code": -32000, "message": "execution reverted"}}


class Clock:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


def _reader(chain, contracts=(CONTRACT,), clock=None):
    return StakingReader(list(contracts), "https://rpc.test", transport=chain,
                         clock=clock or Clock())


# ---------------------------------------------------------------------------
# Selectors and ABI
# ---------------------------------------------------------------------------
def test_selectors_match_the_contract_signatures():
    eth_utils = pytest.importorskip("eth_utils")
    for name, sel in [
        ("isActive(bytes32)", st.SEL_IS_ACTIVE),
        ("operatorOf(bytes32)", st.SEL_OPERATOR_OF),
        ("endpointOf(bytes32)", st.SEL_ENDPOINT_OF),
        ("stakeOf(bytes32)", st.SEL_STAKE_OF),
        ("pillarCount()", st.SEL_PILLAR_COUNT),
        ("pidsPage(uint256,uint256)", st.SEL_PIDS_PAGE),
    ]:
        assert eth_utils.keccak(text=name)[:4].hex() == sel, name


def test_encode_call():
    assert st.encode_call(st.SEL_IS_ACTIVE, PID_A) == "0x" + st.SEL_IS_ACTIVE + PID_A
    assert st.encode_call(st.SEL_PIDS_PAGE, 5, 200) == "0x" + st.SEL_PIDS_PAGE + _w(5) + _w(200)
    with pytest.raises(ValueError):
        st.encode_call(st.SEL_IS_ACTIVE, "not-a-pid")


def test_decoders():
    assert st.decode_bool(abi_uint(1)) is True
    assert st.decode_bool(abi_uint(0)) is False
    assert st.decode_address(abi_address(OPERATOR)) == OPERATOR
    assert st.decode_string(abi_string("pillars.google.com")) == "pillars.google.com"
    assert st.decode_string(abi_string("")) == ""
    assert st.decode_bytes32_array(abi_bytes32_array([PID_A, PID_B])) == [PID_A, PID_B]


def test_decoders_refuse_truncated_results():
    with pytest.raises(ValueError):
        st.decode_string("0x" + _w(32) + _w(100))
    with pytest.raises(ValueError):
        st.decode_bytes32_array("0x" + _w(32) + _w(3) + PID_A)


# ---------------------------------------------------------------------------
# Standing
# ---------------------------------------------------------------------------
async def test_active_pillar():
    chain = FakeChain()
    chain.add(PID_A)
    s = await _reader(chain).status(PID_A)
    assert s.active and s.operator == OPERATOR
    assert s.endpoint == "pillar.example.com"
    assert s.stake_units == 100_000 * 10**18
    assert s.contract == CONTRACT


async def test_unregistered_pillar():
    s = await _reader(FakeChain()).status(PID_A)
    assert not s.active and s.operator is None and s.error is None


async def test_below_threshold_reports_operator():
    chain = FakeChain()
    chain.add(PID_A, active=False, stake=99_999 * 10**18)
    s = await _reader(chain).status(PID_A)
    assert not s.active
    assert s.operator == OPERATOR
    assert s.stake_units == 99_999 * 10**18


async def test_active_in_any_listed_contract():
    chain = FakeChain()
    chain.add(PID_A, contract=CONTRACT, active=False)
    chain.add(PID_A, contract=CONTRACT_2, active=True)
    s = await _reader(chain, contracts=(CONTRACT, CONTRACT_2)).status(PID_A)
    assert s.active and s.contract == CONTRACT_2


async def test_non_pid_is_refused_without_rpc():
    chain = FakeChain()
    s = await _reader(chain).status("xyz")
    assert not s.active and s.error == "not a PID"
    assert chain.calls == 0


async def test_answers_are_cached():
    chain = FakeChain()
    chain.add(PID_A)
    clock = Clock()
    reader = _reader(chain, clock=clock)
    await reader.status(PID_A)
    calls = chain.calls
    await reader.status(PID_A)
    assert chain.calls == calls
    clock.t += st.CACHE_TTL_SEC + 1
    await reader.status(PID_A)
    assert chain.calls > calls


async def test_rpc_outage_uses_cache_within_grace_then_fails_closed():
    chain = FakeChain()
    chain.add(PID_A)
    clock = Clock()
    reader = _reader(chain, clock=clock)
    assert (await reader.status(PID_A)).active

    chain.fail = True
    clock.t += st.CACHE_TTL_SEC + 1
    s = await reader.status(PID_A)
    assert s.active and s.stale and "rpc down" in s.error

    clock.t += st.STALE_GRACE_SEC
    s = await reader.status(PID_A)
    assert not s.active and "rpc down" in s.error


async def test_rpc_outage_without_cache_is_inactive():
    chain = FakeChain()
    chain.fail = True
    s = await _reader(chain).status(PID_A)
    assert not s.active and s.error


# ---------------------------------------------------------------------------
# Directory
# ---------------------------------------------------------------------------
async def test_directory_skips_slots_a_withdrawal_emptied(monkeypatch):
    monkeypatch.setattr(st, "DIRECTORY_PAGE", 2)
    chain = FakeChain()
    pids = [format(i, "064x") for i in range(1, 6)]
    for p in pids:
        chain.add(p)
    chain.withdraw(pids[1])
    got = await _reader(chain).directory()
    assert got == [pids[0], pids[2], pids[3], pids[4]]


async def test_directory_pages_and_dedupes(monkeypatch):
    monkeypatch.setattr(st, "DIRECTORY_PAGE", 2)
    chain = FakeChain()
    pids = [format(i, "064x") for i in range(1, 6)]
    for p in pids:
        chain.add(p)
    chain.add(pids[0], contract=CONTRACT_2)
    got = await _reader(chain, contracts=(CONTRACT, CONTRACT_2)).directory()
    assert got == pids


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
def test_from_config_off_without_contracts():
    assert StakingReader.from_config({}) is None
    assert StakingReader.from_config({"staking_contracts": []}) is None


def test_from_config_uses_chain_table():
    r = StakingReader.from_config({"staking_contracts": [CONTRACT], "staking_chain_id": 50})
    assert r.rpc_url == "https://rpc.xinfin.network"
    r = StakingReader.from_config({"staking_contracts": [CONTRACT], "staking_chain_id": 51})
    assert r.rpc_url == "https://rpc.apothem.network"


def test_from_config_rpc_override_and_bad_addresses():
    r = StakingReader.from_config({"staking_contracts": [CONTRACT, "nope"],
                                   "staking_rpc": "https://my.rpc"})
    assert r.rpc_url == "https://my.rpc"
    assert r.contracts == [CONTRACT]
