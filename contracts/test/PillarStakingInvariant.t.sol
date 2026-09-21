// SPDX-License-Identifier: AGPL-3.0-or-later
pragma solidity 0.8.24;

import {Test} from "forge-std/Test.sol";
import {StdInvariant} from "forge-std/StdInvariant.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {PillarStaking} from "../src/PillarStaking.sol";
import {MockREFI} from "./PillarStaking.t.sol";

/// Drives every state-changing entry point over a small fixed set of actors
/// and PIDs, so the fuzzer explores orderings rather than addresses.
contract Handler is Test {
    PillarStaking public staking;
    MockREFI public token;
    address public oracle;

    address[] public actors;
    bytes32[] public pids;

    /// Every fee the contract has ever charged, summed independently.
    uint256 public ghostFeesCharged;

    constructor(PillarStaking staking_, MockREFI token_, address oracle_) {
        staking = staking_;
        token = token_;
        oracle = oracle_;
        for (uint256 i = 0; i < 3; i++) {
            address a = address(uint160(0xA11CE + i));
            actors.push(a);
            token_.mint(a, 10_000_000 ether);
            vm.prank(a);
            token_.approve(address(staking_), type(uint256).max);
        }
        for (uint256 i = 0; i < 5; i++) pids.push(keccak256(abi.encode("pid", i)));
    }

    function pidCount() external view returns (uint256) {
        return pids.length;
    }

    function pidAt(uint256 i) external view returns (bytes32) {
        return pids[i];
    }

    function _actor(uint256 seed) internal view returns (address) {
        return actors[seed % actors.length];
    }

    function _pid(uint256 seed) internal view returns (bytes32) {
        return pids[seed % pids.length];
    }

    function register(uint256 aSeed, uint256 pSeed, uint256 amount) external {
        amount = bound(amount, 100_000 ether, 300_000 ether);
        vm.prank(_actor(aSeed));
        try staking.register(_pid(pSeed), amount, "peer.example") {} catch {}
    }

    function topUp(uint256 aSeed, uint256 pSeed, uint256 amount) external {
        amount = bound(amount, 1, 50_000 ether);
        vm.prank(_actor(aSeed));
        try staking.topUp(_pid(pSeed), amount) {} catch {}
    }

    function requestUnstake(uint256 aSeed, uint256 pSeed) external {
        vm.prank(_actor(aSeed));
        try staking.requestUnstake(_pid(pSeed)) {} catch {}
    }

    function cancelUnstake(uint256 aSeed, uint256 pSeed) external {
        vm.prank(_actor(aSeed));
        try staking.cancelUnstake(_pid(pSeed)) {} catch {}
    }

    function withdraw(uint256 aSeed, uint256 pSeed) external {
        vm.prank(_actor(aSeed));
        try staking.withdraw(_pid(pSeed)) {} catch {}
    }

    function recordInactive(uint256 pSeed, uint256 daysBack, uint256 batchSeed) external {
        uint32 today = uint32(block.timestamp / 1 days);
        uint32 back = uint32(bound(daysBack, 1, 7));
        if (back >= today) return;

        uint256 n = bound(batchSeed, 1, pids.length);
        bytes32[] memory batch = new bytes32[](n);
        for (uint256 i = 0; i < n; i++) batch[i] = _pid(pSeed + i);

        uint256 before = staking.pendingFees();
        vm.prank(oracle);
        try staking.recordInactive(batch, today - back) {
            ghostFeesCharged += staking.pendingFees() - before;
        } catch {}
    }

    function sweepFees() external {
        try staking.sweepFees() {} catch {}
    }

    function warp(uint256 secs) external {
        vm.warp(block.timestamp + bound(secs, 1 hours, 3 days));
    }
}

contract PillarStakingInvariantTest is StdInvariant, Test {
    MockREFI refi;
    PillarStaking staking;
    Handler handler;

    address admin = makeAddr("admin");
    address oracle = makeAddr("oracle");
    address pool = makeAddr("rewardsPool");

    uint256 lastPillarCount;

    function setUp() public {
        vm.warp(1_750_000_000);
        refi = new MockREFI();
        staking = new PillarStaking(IERC20(address(refi)), admin, pool);
        bytes32 oracleRole = staking.ORACLE_ROLE();
        vm.prank(admin);
        staking.grantRole(oracleRole, oracle);

        handler = new Handler(staking, refi, oracle);
        targetContract(address(handler));
    }

    /// Every token the contract holds is either someone's stake or an
    /// unswept fee. Nothing is unaccounted for, and nothing is double-counted.
    function invariant_Solvency() public view {
        assertEq(
            refi.balanceOf(address(staking)),
            staking.totalStaked() + staking.pendingFees(),
            "contract balance diverged from its own accounting"
        );
    }

    /// The promise in the contract header: no sequence of fees can take an
    /// operator below 99,999 REFI.
    function invariant_NeverBelowFloor() public view {
        for (uint256 i = 0; i < handler.pidCount(); i++) {
            bytes32 pid = handler.pidAt(i);
            if (staking.operatorOf(pid) == address(0)) continue;
            assertGe(staking.stakeOf(pid), staking.FEE_FLOOR(), "a fee went below the floor");
        }
    }

    /// `isActive` never disagrees with the state it is derived from.
    function invariant_ActiveImpliesLive() public view {
        uint256 today = block.timestamp / 1 days;
        for (uint256 i = 0; i < handler.pidCount(); i++) {
            bytes32 pid = handler.pidAt(i);
            if (!staking.isActive(pid)) continue;
            PillarStaking.Pillar memory p = staking.pillarOf(pid);
            assertTrue(p.operator != address(0), "active but unregistered");
            assertEq(p.unstakeRequestedAt, 0, "active while unstaking");
            assertGe(p.staked, staking.THRESHOLD(), "active below the threshold");
            assertTrue(
                p.lastInactiveDay == 0
                    || today > uint256(p.lastInactiveDay) + staking.INACTIVE_GRACE_DAYS(),
                "active inside the inactivity grace window"
            );
        }
    }

    /// Fees are conserved: everything charged is either still pending or has
    /// been swept to the fee recipient. None is created or destroyed.
    function invariant_FeesAreConserved() public view {
        assertEq(
            refi.balanceOf(pool) + staking.pendingFees(),
            handler.ghostFeesCharged(),
            "fees charged do not match fees held plus fees swept"
        );
    }

    /// Directory slots are append-only: a reader paging across several calls
    /// can never have a live Pillar move beneath it.
    function invariant_DirectoryIsAppendOnly() public {
        uint256 n = staking.pillarCount();
        assertGe(n, lastPillarCount, "the directory shrank");
        lastPillarCount = n;

        bytes32[] memory page = staking.pidsPage(0, type(uint256).max);
        assertEq(page.length, n, "paging disagrees with the count");
        for (uint256 i = 0; i < page.length; i++) {
            if (page[i] == bytes32(0)) continue;
            for (uint256 j = i + 1; j < page.length; j++) {
                assertTrue(page[i] != page[j], "a PID occupies two live slots");
            }
        }
    }
}
