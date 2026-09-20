// SPDX-License-Identifier: AGPL-3.0-or-later
pragma solidity 0.8.24;

import {Test} from "forge-std/Test.sol";
import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {IAccessControl} from "@openzeppelin/contracts/access/IAccessControl.sol";
import {PillarStaking} from "../src/PillarStaking.sol";

contract MockREFI is ERC20 {
    constructor() ERC20("Regenerative Finance", "REFI") {}

    function mint(address to, uint256 amount) external {
        _mint(to, amount);
    }
}

/// Takes 1% on every transfer — REFI does not, but the contract must not
/// credit more than it received if a token ever does.
contract FeeOnTransferToken is ERC20 {
    constructor() ERC20("Fee", "FEE") {}

    function mint(address to, uint256 amount) external {
        _mint(to, amount);
    }

    function _update(address from, address to, uint256 value) internal override {
        if (from != address(0) && to != address(0)) {
            uint256 fee = value / 100;
            super._update(from, address(0xdead), fee);
            value -= fee;
        }
        super._update(from, to, value);
    }
}

contract PillarStakingTest is Test {
    MockREFI refi;
    PillarStaking staking;

    address admin = makeAddr("admin");
    address oracle = makeAddr("oracle");
    address pool = makeAddr("rewardsPool");
    address alice = makeAddr("alice");
    address bob = makeAddr("bob");

    bytes32 constant PID = keccak256("pillar-a");
    bytes32 constant PID_B = keccak256("pillar-b");

    uint256 constant T = 100_000 ether;

    function setUp() public {
        vm.warp(1_750_000_000); // a realistic "now", so day numbers are large
        refi = new MockREFI();
        staking = new PillarStaking(IERC20(address(refi)), admin, pool);
        bytes32 oracleRole = staking.ORACLE_ROLE();
        vm.prank(admin);
        staking.grantRole(oracleRole, oracle);

        refi.mint(alice, 1_000_000 ether);
        refi.mint(bob, 1_000_000 ether);
        vm.prank(alice);
        refi.approve(address(staking), type(uint256).max);
        vm.prank(bob);
        refi.approve(address(staking), type(uint256).max);
    }

    function _register(address who, bytes32 pid, uint256 amount) internal {
        vm.prank(who);
        staking.register(pid, amount, "pillar.example.com");
    }

    function _today() internal view returns (uint32) {
        return uint32(block.timestamp / 1 days);
    }

    function _record(bytes32 pid, uint32 day) internal {
        bytes32[] memory pids = new bytes32[](1);
        pids[0] = pid;
        vm.prank(oracle);
        staking.recordInactive(pids, day);
    }

    /// Move to `n` whole days after registration day, and return yesterday.
    function _advanceDays(uint256 n) internal returns (uint32 yesterday) {
        vm.warp(block.timestamp + n * 1 days);
        return _today() - 1;
    }

    // --------------------------------------------------------------
    // The constants the plan fixes
    // --------------------------------------------------------------

    function test_Constants() public view {
        assertEq(staking.THRESHOLD(), 100_000 ether);
        assertEq(staking.FEE_PER_DAY(), 1 ether);
        assertEq(staking.FEE_FLOOR(), 99_999 ether);
        assertEq(staking.COOLDOWN(), 14 days);
    }

    // --------------------------------------------------------------
    // Registering
    // --------------------------------------------------------------

    function test_RegisterAtThresholdIsActive() public {
        _register(alice, PID, T);
        assertTrue(staking.isActive(PID));
        assertEq(staking.operatorOf(PID), alice);
        assertEq(staking.stakeOf(PID), T);
        assertEq(staking.endpointOf(PID), "pillar.example.com");
        assertEq(staking.pillarCount(), 1);
    }

    function test_RegisterBelowThresholdReverts() public {
        vm.expectRevert(PillarStaking.BelowThreshold.selector);
        _register(alice, PID, T - 1);
    }

    function test_RegisterAboveThresholdAllowed() public {
        _register(alice, PID, 250_000 ether);
        assertTrue(staking.isActive(PID));
        assertEq(staking.stakeOf(PID), 250_000 ether);
    }

    function test_CannotRegisterTakenPid() public {
        _register(alice, PID, T);
        vm.expectRevert(PillarStaking.AlreadyRegistered.selector);
        _register(bob, PID, T);
    }

    function test_ZeroPidReverts() public {
        vm.expectRevert(PillarStaking.ZeroPid.selector);
        _register(alice, bytes32(0), T);
    }

    function test_EndpointLengthCapped() public {
        bytes memory longName = new bytes(254);
        for (uint256 i = 0; i < longName.length; i++) longName[i] = "a";
        vm.prank(alice);
        vm.expectRevert(PillarStaking.EndpointTooLong.selector);
        staking.register(PID, T, string(longName));
    }

    function test_OnlyOperatorManagesPillar() public {
        _register(alice, PID, T);
        vm.startPrank(bob);
        vm.expectRevert(PillarStaking.NotOperator.selector);
        staking.topUp(PID, 1 ether);
        vm.expectRevert(PillarStaking.NotOperator.selector);
        staking.setEndpoint(PID, "evil.example");
        vm.expectRevert(PillarStaking.NotOperator.selector);
        staking.requestUnstake(PID);
        vm.stopPrank();
    }

    function test_SetEndpoint() public {
        _register(alice, PID, T);
        vm.prank(alice);
        staking.setEndpoint(PID, "pillars.google.com");
        assertEq(staking.endpointOf(PID), "pillars.google.com");
    }

    function test_CreditsWhatArrivedNotWhatWasAsked() public {
        FeeOnTransferToken fot = new FeeOnTransferToken();
        PillarStaking s = new PillarStaking(IERC20(address(fot)), admin, pool);
        fot.mint(alice, 1_000_000 ether);
        vm.startPrank(alice);
        fot.approve(address(s), type(uint256).max);
        // 100,000 sent arrives as 99,000: below the threshold
        vm.expectRevert(PillarStaking.BelowThreshold.selector);
        s.register(PID, T, "");
        s.register(PID, 102_000 ether, "");
        vm.stopPrank();
        assertEq(s.stakeOf(PID), 100_980 ether);
    }

    // --------------------------------------------------------------
    // Inactivity fees: a trigger, never a penalty
    // --------------------------------------------------------------

    function test_OneInactiveDayAtExactlyThresholdPauses() public {
        _register(alice, PID, T);
        uint32 day = _advanceDays(2);
        _record(PID, day);
        assertEq(staking.stakeOf(PID), 99_999 ether);
        assertFalse(staking.isActive(PID));
        assertEq(refi.balanceOf(pool), 1 ether);
    }

    function test_FeesStopAtFloor() public {
        _register(alice, PID, T);
        _advanceDays(8);
        for (uint32 d = _today() - 7; d < _today(); d++) {
            _record(PID, d);
        }
        // Seven inactive days, but only the first one cost anything
        assertEq(staking.stakeOf(PID), 99_999 ether);
        assertEq(refi.balanceOf(pool), 1 ether);
    }

    function test_FloorDayStillRecordedForRewards() public {
        _register(alice, PID, T);
        uint32 d1 = _advanceDays(2);
        _record(PID, d1);
        uint32 d2 = _advanceDays(1);
        vm.expectEmit(true, true, false, true);
        emit PillarStaking.InactiveDay(PID, d2, 0, 99_999 ether);
        _record(PID, d2);
        assertTrue(staking.inactiveRecorded(PID, d2));
    }

    function test_BufferAboveThreshold() public {
        _register(alice, PID, T + 3 ether);
        _advanceDays(5);
        uint32 today = _today();
        _record(PID, today - 4);
        _record(PID, today - 3);
        _record(PID, today - 2);
        assertEq(staking.stakeOf(PID), T);
        assertTrue(staking.isActive(PID), "three days of buffer used, still active");
        _record(PID, today - 1);
        assertFalse(staking.isActive(PID));
        assertEq(staking.stakeOf(PID), 99_999 ether);
    }

    function test_TopUpResumes() public {
        _register(alice, PID, T);
        _record(PID, _advanceDays(2));
        assertFalse(staking.isActive(PID));
        vm.prank(alice);
        staking.topUp(PID, 1 ether);
        assertTrue(staking.isActive(PID));
    }

    function test_RecordIsIdempotent() public {
        _register(alice, PID, T + 10 ether);
        uint32 day = _advanceDays(2);
        _record(PID, day);
        _record(PID, day);
        assertEq(staking.stakeOf(PID), T + 9 ether);
    }

    function test_RegistrationDayNeverCharged() public {
        _register(alice, PID, T);
        uint32 regDay = _today();
        _advanceDays(1);
        _record(PID, regDay);
        assertEq(staking.stakeOf(PID), T);
        assertFalse(staking.inactiveRecorded(PID, regDay));
    }

    function test_DayRange() public {
        _register(alice, PID, T);
        _advanceDays(20);
        bytes32[] memory pids = new bytes32[](1);
        pids[0] = PID;
        uint32 today = _today();
        vm.startPrank(oracle);
        vm.expectRevert(abi.encodeWithSelector(PillarStaking.DayOutOfRange.selector, today));
        staking.recordInactive(pids, today); // today is not over yet
        vm.expectRevert(abi.encodeWithSelector(PillarStaking.DayOutOfRange.selector, today - 8));
        staking.recordInactive(pids, today - 8); // beyond the backfill window
        staking.recordInactive(pids, today - 7); // oldest allowed
        vm.stopPrank();
        assertTrue(staking.inactiveRecorded(PID, today - 7));
        assertEq(staking.stakeOf(PID), 99_999 ether, "the oldest allowed day is charged");
    }

    function test_OnlyOracleRecords() public {
        _register(alice, PID, T);
        uint32 day = _advanceDays(2);
        bytes32[] memory pids = new bytes32[](1);
        pids[0] = PID;
        bytes32 oracleRole = staking.ORACLE_ROLE();
        vm.prank(bob);
        vm.expectRevert(
            abi.encodeWithSelector(IAccessControl.AccessControlUnauthorizedAccount.selector, bob, oracleRole)
        );
        staking.recordInactive(pids, day);
    }

    function test_UnknownPidsSkippedInBatch() public {
        _register(alice, PID, T);
        _register(bob, PID_B, T + 5 ether);
        uint32 day = _advanceDays(2);
        bytes32[] memory pids = new bytes32[](3);
        pids[0] = PID;
        pids[1] = keccak256("nobody");
        pids[2] = PID_B;
        vm.prank(oracle);
        staking.recordInactive(pids, day);
        assertEq(staking.stakeOf(PID), 99_999 ether);
        assertEq(staking.stakeOf(PID_B), T + 4 ether);
        assertEq(refi.balanceOf(pool), 2 ether);
    }

    /// No sequence of inactive days can take a stake below 99,999 REFI,
    /// and every fee lands in the pool.
    function testFuzz_NeverBelowFloor(uint256 extra, uint8 days_) public {
        extra = bound(extra, 0, 50 ether);
        uint256 n = bound(days_, 1, 7);
        _register(alice, PID, T + extra);
        _advanceDays(n + 1);
        uint32 today = _today();
        for (uint32 i = 1; i <= n; i++) {
            _record(PID, today - i);
        }
        uint256 staked = staking.stakeOf(PID);
        assertGe(staked, 99_999 ether);
        // Headroom above the floor is extra + 1 REFI; each day takes up to 1 REFI of it
        uint256 headroom = extra + 1 ether;
        uint256 expectedFee = n * 1 ether < headroom ? n * 1 ether : headroom;
        assertEq(T + extra - staked, expectedFee);
        assertEq(refi.balanceOf(pool), expectedFee);
        assertEq(refi.balanceOf(address(staking)), staked);
    }

    // --------------------------------------------------------------
    // Unstaking: 14-day cooldown
    // --------------------------------------------------------------

    function test_UnstakeDeactivatesImmediately() public {
        _register(alice, PID, T);
        vm.prank(alice);
        staking.requestUnstake(PID);
        assertFalse(staking.isActive(PID));
    }

    function test_WithdrawAfterCooldown() public {
        _register(alice, PID, 150_000 ether);
        uint256 before = refi.balanceOf(alice);
        vm.prank(alice);
        staking.requestUnstake(PID);
        uint256 availableAt = block.timestamp + 14 days;

        vm.warp(availableAt - 1);
        vm.prank(alice);
        vm.expectRevert(abi.encodeWithSelector(PillarStaking.CooldownActive.selector, availableAt));
        staking.withdraw(PID);

        vm.warp(availableAt);
        vm.prank(alice);
        staking.withdraw(PID);
        assertEq(refi.balanceOf(alice), before + 150_000 ether);
        assertEq(staking.operatorOf(PID), address(0));
        // The slot stays, emptied: directory indexes never move (see
        // test_DirectoryIndexesNeverMove)
        assertEq(staking.pillarCount(), 1);
        assertEq(staking.pidsPage(0, 1)[0], bytes32(0));
    }

    function test_UnstakingDayIsRecordedButNotCharged() public {
        _register(alice, PID, T);
        vm.prank(alice);
        staking.requestUnstake(PID);
        uint32 day = _advanceDays(2);
        _record(PID, day);
        assertEq(staking.stakeOf(PID), T, "deactivated by its own request: no fee");
        // Recorded all the same: rewards are withheld on this flag, and an
        // operator who could suppress it would be paid for days it was down
        assertTrue(staking.inactiveRecorded(PID, day));
    }

    /// An operator who sandwiches the oracle's call with requestUnstake /
    /// cancelUnstake must not erase the record of a day it was offline.
    function test_UnstakeSandwichCannotEraseInactivity() public {
        _register(alice, PID, T + 30 ether);
        uint32 firstDay = _today() + 1;
        for (uint256 i = 0; i < 30; i++) {
            vm.warp(block.timestamp + 1 days);
            uint32 day = _today() - 1;
            if (day < firstDay) continue;
            vm.prank(alice);
            staking.requestUnstake(PID);      // front-run
            _record(PID, day);
            vm.prank(alice);
            staking.cancelUnstake(PID);       // back-run
            assertTrue(staking.inactiveRecorded(PID, day), "day erased");
        }
        // The sandwich saves nothing either: the request always arrives
        // after the day being judged, so every one of those days is charged.
        assertEq(staking.stakeOf(PID), T + 1 ether, "29 days offline, 29 REFI");
    }

    /// Sitting out the whole backfill window must not erase it either.
    function test_SittingInUnstakingDoesNotEraseTheWindow() public {
        _register(alice, PID, T);
        vm.prank(alice);
        staking.requestUnstake(PID);
        _advanceDays(8);
        uint32 today = _today();
        for (uint32 d = today - 7; d < today; d++) _record(PID, d);
        vm.prank(alice);
        staking.cancelUnstake(PID);
        for (uint32 d = today - 7; d < today; d++) {
            assertTrue(staking.inactiveRecorded(PID, d), "window erased");
        }
    }

    /// Cancelling an unstake must not make the deactivated days chargeable.
    function test_CancelledUnstakeDaysAreStillNotCharged() public {
        _register(alice, PID, T + 10 ether);
        _advanceDays(1);
        uint32 requestDay = _today();
        vm.prank(alice);
        staking.requestUnstake(PID);          // deactivated from here
        _advanceDays(3);
        vm.prank(alice);
        staking.cancelUnstake(PID);           // active again
        assertTrue(staking.isActive(PID));

        _advanceDays(1);
        for (uint32 d = requestDay; d < _today(); d++) _record(PID, d);
        assertEq(staking.stakeOf(PID), T + 10 ether, "charged for deactivated days");
        for (uint32 d = requestDay; d < _today(); d++) {
            assertTrue(staking.inactiveRecorded(PID, d), "day not recorded");
        }
    }

    /// Days before the unstake request are charged; days from it are not.
    function test_DaysBeforeTheRequestAreStillCharged() public {
        _register(alice, PID, T + 10 ether);
        _advanceDays(3);                       // two whole days offline
        uint32 today = _today();
        vm.prank(alice);
        staking.requestUnstake(PID);           // deactivates from today
        _record(PID, today - 2);
        _record(PID, today - 1);
        assertEq(staking.stakeOf(PID), T + 8 ether, "both earlier days charged");
        _advanceDays(1);
        _record(PID, today);                   // the request day itself
        assertEq(staking.stakeOf(PID), T + 8 ether, "not charged from the request on");
        assertTrue(staking.inactiveRecorded(PID, today));
    }

    function test_CancelUnstake() public {
        _register(alice, PID, T);
        vm.startPrank(alice);
        staking.requestUnstake(PID);
        staking.cancelUnstake(PID);
        vm.stopPrank();
        assertTrue(staking.isActive(PID));
    }

    function test_CannotTopUpWhileUnstaking() public {
        _register(alice, PID, T);
        vm.startPrank(alice);
        staking.requestUnstake(PID);
        vm.expectRevert(PillarStaking.Unstaking.selector);
        staking.topUp(PID, 1 ether);
        vm.stopPrank();
    }

    function test_WithdrawWithoutRequestReverts() public {
        _register(alice, PID, T);
        vm.prank(alice);
        vm.expectRevert(PillarStaking.NotUnstaking.selector);
        staking.withdraw(PID);
    }

    function test_PidReusableAfterWithdraw() public {
        _register(alice, PID, T);
        vm.prank(alice);
        staking.requestUnstake(PID);
        vm.warp(block.timestamp + 14 days);
        vm.prank(alice);
        staking.withdraw(PID);
        _register(bob, PID, T);
        assertEq(staking.operatorOf(PID), bob);
    }

    /// Every lever the admin and the oracle still hold, pulled against a
    /// pending withdrawal: none of them can stop it.
    function test_NoRoleCanBlockWithdraw() public {
        _register(alice, PID, T);
        vm.prank(alice);
        staking.requestUnstake(PID);

        address attackerPool = makeAddr("attackerPool");
        vm.startPrank(admin);
        staking.setFeeRecipient(attackerPool);
        staking.grantRole(staking.ORACLE_ROLE(), admin);
        staking.revokeRole(staking.ORACLE_ROLE(), oracle);
        vm.stopPrank();

        _advanceDays(3);
        bytes32[] memory pids = new bytes32[](1);
        pids[0] = PID;
        vm.prank(admin);
        staking.recordInactive(pids, _today() - 1);

        vm.warp(block.timestamp + 14 days);
        vm.prank(alice);
        staking.withdraw(PID);
        assertEq(refi.balanceOf(alice), 1_000_000 ether, "stake returned in full");
        assertEq(refi.balanceOf(attackerPool), 0, "and nothing was taken from it");
    }

    // --------------------------------------------------------------
    // Directory
    // --------------------------------------------------------------

    /// A node paging the directory across several calls must not lose a
    /// Pillar because a different one withdrew between two pages.
    function test_DirectoryIndexesNeverMove() public {
        bytes32[] memory pids = new bytes32[](5);
        for (uint256 i = 0; i < 5; i++) {
            pids[i] = keccak256(abi.encode("pillar", i));
            _register(alice, pids[i], T);
        }
        // The node reads the first page, then pids[0] withdraws
        bytes32[] memory first = staking.pidsPage(0, 2);
        vm.startPrank(alice);
        staking.requestUnstake(pids[0]);
        vm.warp(block.timestamp + 14 days);
        staking.withdraw(pids[0]);
        vm.stopPrank();

        bytes32[] memory seen = new bytes32[](8);
        uint256 n;
        for (uint256 i = 0; i < first.length; i++) if (first[i] != bytes32(0)) seen[n++] = first[i];
        for (uint256 offset = 2; offset < staking.pillarCount(); offset += 2) {
            bytes32[] memory page = staking.pidsPage(offset, 2);
            for (uint256 i = 0; i < page.length; i++) if (page[i] != bytes32(0)) seen[n++] = page[i];
        }
        // Every Pillar that is still registered was seen exactly once
        for (uint256 i = 1; i < 5; i++) {
            uint256 hits;
            for (uint256 j = 0; j < n; j++) if (seen[j] == pids[i]) hits++;
            assertEq(hits, 1, "a live Pillar was missed or double-counted");
        }
        // 5, not 4: the page read before the withdrawal still names the
        // Pillar that has since left. A reader re-checks isActive anyway;
        // what must never happen is a live Pillar going unseen.
        assertEq(n, 5);
        assertEq(staking.pidsPage(5, 10).length, 0);
    }

    function test_PidsPageTakesAnUnboundedLimit() public {
        _register(alice, PID, T);
        _register(bob, PID_B, T);
        assertEq(staking.pidsPage(0, type(uint256).max).length, 2);
        assertEq(staking.pidsPage(1, type(uint256).max).length, 1);
    }

    function test_WithdrawnPidCanBeRegisteredAgainInAFreshSlot() public {
        _register(alice, PID, T);
        vm.startPrank(alice);
        staking.requestUnstake(PID);
        vm.warp(block.timestamp + 14 days);
        staking.withdraw(PID);
        vm.stopPrank();
        _register(bob, PID, T);
        assertEq(staking.operatorOf(PID), bob);
        assertEq(staking.pillarCount(), 2);
        assertEq(staking.pidsPage(0, 2)[0], bytes32(0));
        assertEq(staking.pidsPage(0, 2)[1], PID);
    }

    // --------------------------------------------------------------
    // Admin
    // --------------------------------------------------------------

    function test_SetFeeRecipient() public {
        address newPool = makeAddr("newPool");
        vm.prank(admin);
        staking.setFeeRecipient(newPool);
        _register(alice, PID, T);
        _record(PID, _advanceDays(2));
        assertEq(refi.balanceOf(newPool), 1 ether);
    }
}
