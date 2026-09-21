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

/// Reverts any transfer to a blocked address, the way a pausable or
/// blocklisting token would. Used to prove recording cannot be halted.
contract BlocklistToken is ERC20 {
    address public blocked;

    constructor() ERC20("Block", "BLK") {}

    function mint(address to, uint256 amount) external {
        _mint(to, amount);
    }

    function block_(address who) external {
        blocked = who;
    }

    function _update(address from, address to, uint256 value) internal override {
        require(to != blocked, "blocked");
        super._update(from, to, value);
    }
}

/// Hands control to a chosen contract on every transfer, the way an ERC777
/// style hook would. The staking contract must survive that.
contract HookToken is ERC20 {
    ReentrantOperator public hookTarget;

    constructor() ERC20("Hook", "HK") {}

    function mint(address to, uint256 amount) external {
        _mint(to, amount);
    }

    function setHook(ReentrantOperator target) external {
        hookTarget = target;
    }

    function _update(address from, address to, uint256 value) internal override {
        super._update(from, to, value);
        if (address(hookTarget) != address(0) && from != address(0)) hookTarget.hook();
    }
}

/// An operator that is a contract, so a token hook can hand it control in the
/// middle of its own staking call.
contract ReentrantOperator {
    PillarStaking public staking;
    bytes32 public pid;
    bytes private _reentry;
    bool private _armed;

    constructor(PillarStaking staking_, IERC20 token_, bytes32 pid_) {
        staking = staking_;
        pid = pid_;
        token_.approve(address(staking_), type(uint256).max);
    }

    function arm(bytes memory reentry) external {
        _reentry = reentry;
        _armed = true;
    }

    function hook() external {
        if (!_armed) return;
        _armed = false; // fire once, or the recursion never ends
        (bool ok, bytes memory ret) = address(staking).call(_reentry);
        if (!ok) {
            assembly {
                revert(add(ret, 32), mload(ret))
            }
        }
    }

    function doRegister(uint256 amount) external {
        staking.register(pid, amount, "reentrant.example");
    }

    function doTopUp(uint256 amount) external {
        staking.topUp(pid, amount);
    }

    function doRequestUnstake() external {
        staking.requestUnstake(pid);
    }

    function doWithdraw() external {
        staking.withdraw(pid);
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
        // The fee is accrued, and reaches the pool when anyone sweeps.
        assertEq(staking.pendingFees(), 1 ether);
        staking.sweepFees();
        assertEq(refi.balanceOf(pool), 1 ether);
        assertEq(staking.pendingFees(), 0);
    }

    function test_FeesStopAtFloor() public {
        _register(alice, PID, T);
        _advanceDays(8);
        for (uint32 d = _today() - 7; d < _today(); d++) {
            _record(PID, d);
        }
        // Seven inactive days, but only the first one cost anything
        assertEq(staking.stakeOf(PID), 99_999 ether);
        assertEq(staking.pendingFees(), 1 ether);
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

    /// A buffer above the threshold absorbs the fee, but it is not evidence
    /// of being online: the recorded day deactivates the Pillar regardless of
    /// how much stake sits on top of it.
    function test_BufferAboveThresholdAbsorbsTheFeeButNotTheEjection() public {
        _register(alice, PID, T + 3 ether);
        _advanceDays(5);
        uint32 today = _today();
        // A day backfilled from well inside the window still costs the
        // buffer, but it says nothing about now: its grace lapsed days ago.
        _record(PID, today - 4);
        assertEq(staking.stakeOf(PID), T + 2 ether, "the buffer paid the fee");
        assertTrue(staking.isActive(PID), "an old backfilled day must not deactivate");

        // Yesterday does deactivate it -- while it still holds a buffer well
        // above the threshold. This is what a large stake used to buy off.
        _record(PID, today - 1);
        assertEq(staking.stakeOf(PID), T + 1 ether);
        assertGt(staking.stakeOf(PID), staking.THRESHOLD(), "still above the threshold");
        assertFalse(staking.isActive(PID), "a buffer must not buy admission");
    }

    function test_TopUpResumesOnceTheGraceWindowLapses() public {
        _register(alice, PID, T);
        _record(PID, _advanceDays(2));
        assertFalse(staking.isActive(PID));

        vm.prank(alice);
        staking.topUp(PID, 1 ether);
        // The stake is whole again, but a top-up is not evidence of being
        // online either -- otherwise 1 REFI would buy instant readmission.
        assertFalse(staking.isActive(PID), "a top-up must not buy instant readmission");

        vm.warp(block.timestamp + (staking.INACTIVE_GRACE_DAYS() + 1) * 1 days);
        assertTrue(staking.isActive(PID), "readmitted with no further action");
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
        assertEq(staking.pendingFees(), 2 ether);
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
        assertEq(staking.pendingFees(), expectedFee);
        assertEq(staking.totalStaked(), staked);
        // Solvency: every token held is either stake or an unswept fee.
        assertEq(refi.balanceOf(address(staking)), staking.totalStaked() + staking.pendingFees());
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
        // The request and cancel days are charged: the Pillar was up for all
        // but a moment of each. Only the whole days between them are free.
        assertEq(staking.stakeOf(PID), T + 8 ether, "only whole unstaking days are free");
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
        assertEq(staking.stakeOf(PID), T + 7 ether, "the request day is charged too");
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
        staking.sweepFees();
        assertEq(refi.balanceOf(newPool), 1 ether);
    }

    // --------------------------------------------------------------
    // Liveness (audit H-1)
    // --------------------------------------------------------------

    function test_GraceExpiresWithoutOperatorAction() public {
        _register(alice, PID, T + 10 ether);
        _record(PID, _advanceDays(2));
        assertFalse(staking.isActive(PID));
        assertGe(staking.stakeOf(PID), staking.THRESHOLD(), "never dropped below the threshold");

        vm.warp(block.timestamp + (staking.INACTIVE_GRACE_DAYS() + 1) * 1 days);
        assertTrue(staking.isActive(PID), "self-heals once the oracle stops recording it");
    }

    // --------------------------------------------------------------
    // Fees accrue; sweeps are permissionless (audit M-1)
    // --------------------------------------------------------------

    /// A fee recipient that cannot receive must never stop days being
    /// recorded: those records are what reward accounting reads.
    function test_RecordingSurvivesARevertingFeeRecipient() public {
        BlocklistToken bad = new BlocklistToken();
        PillarStaking s = new PillarStaking(IERC20(address(bad)), admin, pool);
        bad.mint(alice, 1_000_000 ether);
        vm.startPrank(alice);
        bad.approve(address(s), type(uint256).max);
        s.register(PID, T + 10 ether, "x");
        vm.stopPrank();
        // Hoisted: an external call in the argument would consume the prank.
        bytes32 oracleRole = s.ORACLE_ROLE();
        vm.prank(admin);
        s.grantRole(oracleRole, oracle);
        bad.block_(pool); // the pool can no longer receive

        vm.warp(block.timestamp + 2 days);
        bytes32[] memory pids = new bytes32[](1);
        pids[0] = PID;
        vm.prank(oracle);
        s.recordInactive(pids, uint32(block.timestamp / 1 days) - 1);

        assertTrue(s.inactiveRecorded(PID, uint32(block.timestamp / 1 days) - 1), "day recorded");
        assertEq(s.pendingFees(), 1 ether, "fee accrued rather than lost");

        vm.expectRevert("blocked");
        s.sweepFees();

        address goodPool = makeAddr("goodPool");
        vm.prank(admin);
        s.setFeeRecipient(goodPool);
        s.sweepFees();
        assertEq(bad.balanceOf(goodPool), 1 ether, "fee delivered once a recipient can receive");
    }

    function test_SweepFeesRevertsWhenNothingAccrued() public {
        vm.expectRevert(PillarStaking.ZeroAmount.selector);
        staking.sweepFees();
    }

    /// Tokens sent straight to the contract used to be stranded forever.
    function test_SweepExcessRecoversDonationsAndCannotTouchStake() public {
        _register(alice, PID, T);
        vm.prank(bob);
        refi.transfer(address(staking), 500 ether);

        staking.sweepExcess();
        assertEq(refi.balanceOf(pool), 500 ether, "only the donation moved");
        assertEq(staking.stakeOf(PID), T, "stake untouched");
        assertEq(refi.balanceOf(address(staking)), staking.totalStaked() + staking.pendingFees());

        vm.expectRevert(PillarStaking.ZeroAmount.selector);
        staking.sweepExcess();
    }

    function test_TotalStakedTracksEveryPath() public {
        _register(alice, PID, T + 5 ether);
        _register(bob, PID_B, T);
        assertEq(staking.totalStaked(), 2 * T + 5 ether);

        vm.prank(alice);
        staking.topUp(PID, 10 ether);
        assertEq(staking.totalStaked(), 2 * T + 15 ether);

        _record(PID, _advanceDays(2));
        assertEq(staking.totalStaked(), 2 * T + 14 ether, "the fee left the stake");

        vm.prank(bob);
        staking.requestUnstake(PID_B);
        vm.warp(block.timestamp + 14 days);
        vm.prank(bob);
        staking.withdraw(PID_B);
        assertEq(staking.totalStaked(), T + 14 ether);
        assertEq(refi.balanceOf(address(staking)), staking.totalStaked() + staking.pendingFees());
    }

    // --------------------------------------------------------------
    // Reentrancy (audit M-3)
    // --------------------------------------------------------------

    function _hookSetup() internal returns (HookToken tok, PillarStaking s, ReentrantOperator op) {
        tok = new HookToken();
        s = new PillarStaking(IERC20(address(tok)), admin, pool);
        op = new ReentrantOperator(s, IERC20(address(tok)), PID);
        tok.mint(address(op), 1_000_000 ether);
        // Hoisted: an external call in the argument would consume the prank.
        bytes32 oracleRole = s.ORACLE_ROLE();
        vm.prank(admin);
        s.grantRole(oracleRole, oracle);
    }

    /// The re-check after `_pull` in topUp exists for exactly this: a hook
    /// that slips an unstake request in while the deposit is in flight.
    function test_ReentrantRequestUnstakeDuringTopUpIsCaught() public {
        (HookToken tok, PillarStaking s, ReentrantOperator op) = _hookSetup();
        op.doRegister(T);
        tok.setHook(op);
        op.arm(abi.encodeCall(PillarStaking.requestUnstake, (PID)));

        vm.expectRevert(PillarStaking.Unstaking.selector);
        op.doTopUp(10 ether);

        assertEq(s.stakeOf(PID), T, "the deposit did not land on a running cooldown");
    }

    function test_ReentrantRegisterIsBlockedByTheGuard() public {
        (HookToken tok,, ReentrantOperator op) = _hookSetup();
        tok.setHook(op);
        op.arm(abi.encodeCall(PillarStaking.register, (PID_B, T, "b")));

        vm.expectRevert(bytes4(keccak256("ReentrancyGuardReentrantCall()")));
        op.doRegister(T);
    }

    function test_ReentrantWithdrawIsBlockedByTheGuard() public {
        (HookToken tok,, ReentrantOperator op) = _hookSetup();
        op.doRegister(T);
        op.doRequestUnstake();
        vm.warp(block.timestamp + 14 days);
        tok.setHook(op);
        op.arm(abi.encodeCall(PillarStaking.withdraw, (PID)));

        vm.expectRevert(bytes4(keccak256("ReentrancyGuardReentrantCall()")));
        op.doWithdraw();
    }

    /// Withdraw clears the Pillar before it pays out, so a hook that comes
    /// back in finds nothing left to act on.
    function test_WithdrawClearsStateBeforePayingOut() public {
        (HookToken tok, PillarStaking s, ReentrantOperator op) = _hookSetup();
        op.doRegister(T);
        op.doRequestUnstake();
        vm.warp(block.timestamp + 14 days);
        tok.setHook(op);
        op.arm(abi.encodeCall(PillarStaking.requestUnstake, (PID)));

        vm.expectRevert(PillarStaking.NotRegistered.selector);
        op.doWithdraw();
    }

    // --------------------------------------------------------------
    // Hygiene (audit L-1, L-2)
    // --------------------------------------------------------------

    /// A re-registered PID keeps the old operator's records in storage, but
    /// the cooldown is longer than the backfill window, so none of them can
    /// reach the new registration.
    function test_StaleInactiveRecordsCannotChargeAReRegisteredPid() public {
        _register(alice, PID, T + 10 ether);
        uint32 staleDay = _advanceDays(2);
        _record(PID, staleDay);
        assertTrue(staking.inactiveRecorded(PID, staleDay));

        vm.prank(alice);
        staking.requestUnstake(PID);
        vm.warp(block.timestamp + 14 days);
        vm.prank(alice);
        staking.withdraw(PID);

        _register(bob, PID, T);
        assertTrue(staking.inactiveRecorded(PID, staleDay), "the record survives deletion");
        assertTrue(staking.isActive(PID), "but it does not follow the new operator");
        assertEq(staking.stakeOf(PID), T);

        bytes32[] memory pids = new bytes32[](1);
        pids[0] = PID;
        vm.prank(oracle);
        vm.expectRevert(abi.encodeWithSelector(PillarStaking.DayOutOfRange.selector, staleDay));
        staking.recordInactive(pids, staleDay);
    }

    function test_ConstructorRejectsItselfAsFeeRecipient() public {
        address predicted = vm.computeCreateAddress(address(this), vm.getNonce(address(this)));
        vm.expectRevert(PillarStaking.ZeroAddress.selector);
        new PillarStaking(IERC20(address(refi)), admin, predicted);
    }

    // --------------------------------------------------------------
    // Audit regressions: the two ejection bypasses (H-1, H-2)
    //
    // Both assert the secure behaviour and both failed against the
    // contract as first written. They are the reason isActive carries a
    // liveness term and the unstaking exemption is exclusive.
    // --------------------------------------------------------------

    /// H-1: stake above the threshold is headroom the 1 REFI/day fee must
    /// chew through before `isActive` can ever go false. At 250,000 REFI
    /// that is 150,000 offline days. No attack required — just over-stake.
    function test_Exploit_OverStakeGrantsImmunityFromEjection() public {
        _register(alice, PID, 250_000 ether);

        // 200 consecutive offline days, recorded honestly by the oracle.
        // The registration day itself is never charged, hence 199.
        for (uint256 i = 0; i < 200; i++) {
            vm.warp(block.timestamp + 1 days);
            _record(PID, _today() - 1);
        }

        assertEq(staking.stakeOf(PID), 250_000 ether - 199 ether, "every day charged");
        assertFalse(
            staking.isActive(PID),
            "EXPLOIT H-1: offline for 200 days and still admitted to the mesh"
        );
    }

    /// H-2: the unstaking exemption is granted per whole UTC day, but the
    /// deactivation it pays for is measured in seconds. Only the latest
    /// stretch is kept, so blind toggling does NOT work -- but an operator
    /// who back-runs the oracle's daily transaction keeps the one stretch
    /// always covering the day being recorded, and pays nothing while being
    /// deactivated for roughly 90 minutes per two days.
    function test_Exploit_BackRunningTheOracleGrantsFeeImmunity() public {
        _register(alice, PID, T); // exactly at threshold: one fee would eject it
        uint32 regDay = _today();

        // 23:59 on the day after registration.
        vm.warp((uint256(regDay) + 1) * 1 days + 1 days - 60);

        for (uint256 cycle = 0; cycle < 10; cycle++) {
            uint32 x = _today();

            vm.prank(alice);
            staking.requestUnstake(PID); // 23:59 day X -> stretch [X, max]

            vm.warp((uint256(x) + 1) * 1 days + 1 hours);
            _record(PID, x); // oracle records day X at 01:00 -- inside the stretch

            vm.warp(block.timestamp + 30 minutes);
            vm.prank(alice);
            staking.cancelUnstake(PID); // 01:30 day X+1 -> stretch [X, X+1]

            vm.warp((uint256(x) + 2) * 1 days + 1 hours);
            _record(PID, x + 1); // oracle records day X+1 -- still inside it

            vm.warp((uint256(x) + 2) * 1 days + 1 days - 60); // 23:59 day X+2
        }

        assertEq(staking.stakeOf(PID), 99_999 ether, "EXPLOIT H-2: paid nothing for 20 days offline");
        assertFalse(staking.isActive(PID), "EXPLOIT H-2: offline the whole time, still active");
    }
}
