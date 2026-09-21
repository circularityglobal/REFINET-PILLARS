// SPDX-License-Identifier: AGPL-3.0-or-later
pragma solidity 0.8.24;

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {AccessControl} from "@openzeppelin/contracts/access/AccessControl.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";

/// @title REFInet Pillar staking
/// @notice A Pillar is admitted to the REFInet mesh while its operator keeps
///         at least 100,000 REFI staked against its Pillar ID (PID).
///
///         An inactive day costs 1 REFI, but a fee can never take a stake
///         below 99,999 REFI. Nothing here can take more than that from an
///         operator.
///
///         The fee is a price, not the enforcement. What deactivates a
///         Pillar is the recorded day itself: a day recorded inactive keeps
///         it out for INACTIVE_GRACE_DAYS however much it has staked. The
///         fee alone could not do that job, because it stops at 99,999 REFI
///         and so a Pillar holding a large buffer above the threshold would
///         stay admitted for as many days as it holds REFI above it.
///
///         The contract is also the mesh directory: every registered PID
///         carries the public endpoint (a domain) where its Pillar answers,
///         so Pillars on different networks find each other without a
///         bootstrap node.
///
///         Not upgradeable, on purpose. If a successor is ever deployed,
///         Pillars accept stake in either contract (config lists several)
///         and operators move by requesting an unstake here; no role can
///         block `withdraw`.
contract PillarStaking is AccessControl, ReentrancyGuard {
    using SafeERC20 for IERC20;

    /// @notice May record inactive days. Held by the liveness monitor.
    bytes32 public constant ORACLE_ROLE = keccak256("ORACLE_ROLE");

    uint256 public constant THRESHOLD = 100_000 ether; // REFI has 18 decimals
    uint256 public constant FEE_PER_DAY = 1 ether;
    uint256 public constant FEE_FLOOR = THRESHOLD - FEE_PER_DAY; // 99,999 REFI
    uint256 public constant COOLDOWN = 14 days;
    /// @notice How many completed days back the oracle may still record.
    uint32 public constant MAX_BACKFILL_DAYS = 7;
    /// @notice A DNS name is at most 253 characters.
    uint256 public constant MAX_ENDPOINT_LENGTH = 253;
    /// @notice How long a Pillar stays deactivated after a day it was
    ///         recorded inactive while it was supposed to be up. Must exceed
    ///         the oracle's recording lag (a day is recorded the day after it
    ///         ends) or the deactivation would never be observable.
    uint32 public constant INACTIVE_GRACE_DAYS = 2;

    IERC20 public immutable token;
    address public feeRecipient;
    /// @notice The sum of every Pillar's stake. Held for the operators.
    uint256 public totalStaked;
    /// @notice Fees charged but not yet swept to the fee recipient. Kept
    ///         separate so recording an inactive day never depends on the
    ///         recipient being able to receive.
    uint256 public pendingFees;

    struct Pillar {
        address operator;
        uint256 staked;
        uint64 registeredAt;
        uint64 unstakeRequestedAt; // 0 while staked
        // The latest stretch of days this Pillar spent deactivated by its own
        // unstake request: open-ended while the request stands, closed on
        // cancel. Days inside it are recorded but never charged, even once the
        // request is cancelled, because the Pillar earned nothing on them.
        // Only the latest stretch is kept; an operator who toggles twice
        // inside the 7-day backfill window keeps only the newer one.
        uint32 unstakeFromDay;
        uint32 unstakeToDay;
        // The most recent day this Pillar was recorded inactive while it was
        // supposed to be up. Deactivates it for INACTIVE_GRACE_DAYS however
        // large its stake, so a buffer above the threshold can no longer buy
        // immunity from ejection. Packs into the slot above; costs no gas.
        uint32 lastInactiveDay;
        string endpoint;
    }

    mapping(bytes32 pid => Pillar) private _pillars;
    /// @notice Whether a (pid, UTC day number) has been recorded inactive.
    mapping(bytes32 pid => mapping(uint32 day => bool)) public inactiveRecorded;

    bytes32[] private _pids;
    mapping(bytes32 pid => uint256) private _pidIndexPlusOne;

    event Registered(bytes32 indexed pid, address indexed operator, uint256 amount, string endpoint);
    event ToppedUp(bytes32 indexed pid, uint256 amount, uint256 staked);
    event EndpointSet(bytes32 indexed pid, string endpoint);
    event UnstakeRequested(bytes32 indexed pid, uint256 availableAt);
    event UnstakeCancelled(bytes32 indexed pid);
    event Withdrawn(bytes32 indexed pid, address indexed operator, uint256 amount);
    /// @notice Emitted for every recorded inactive day, including ones that
    ///         cost nothing because the stake was already at the floor.
    ///         Reward accounting reads these: no rewards for inactive days.
    event InactiveDay(bytes32 indexed pid, uint32 indexed day, uint256 fee, uint256 staked);
    event FeeRecipientSet(address feeRecipient);
    event FeesSwept(address indexed to, uint256 amount);
    event ExcessSwept(address indexed to, uint256 amount);

    error ZeroAddress();
    error ZeroPid();
    error AlreadyRegistered();
    error NotRegistered();
    error NotOperator();
    error BelowThreshold();
    error ZeroAmount();
    error Unstaking();
    error NotUnstaking();
    error CooldownActive(uint256 availableAt);
    error EndpointTooLong();
    error DayOutOfRange(uint32 day);

    constructor(IERC20 token_, address admin, address feeRecipient_) {
        if (
            address(token_) == address(0) || admin == address(0) || feeRecipient_ == address(0)
                || feeRecipient_ == address(this)
        ) {
            revert ZeroAddress();
        }
        token = token_;
        feeRecipient = feeRecipient_;
        emit FeeRecipientSet(feeRecipient_);
        _grantRole(DEFAULT_ADMIN_ROLE, admin);
    }

    // ------------------------------------------------------------------
    // Operator actions
    // ------------------------------------------------------------------

    /// @notice Register a Pillar and stake at least THRESHOLD against it.
    ///         The caller becomes its operator: the wallet that must also be
    ///         bound to this PID in the Pillar's /identity/v3.json.
    function register(bytes32 pid, uint256 amount, string calldata endpoint) external nonReentrant {
        if (pid == bytes32(0)) revert ZeroPid();
        if (_pillars[pid].operator != address(0)) revert AlreadyRegistered();
        if (bytes(endpoint).length > MAX_ENDPOINT_LENGTH) revert EndpointTooLong();

        uint256 received = _pull(amount);
        // A PID is SHA-256 of an Ed25519 public key, which this chain cannot
        // verify, so registering one proves nothing about holding that key:
        // anyone may register any PID, and the first caller wins. What that
        // buys an impostor is nothing but denial — every Pillar verifies a
        // peer's own signed identity document against operatorOf(pid) before
        // trusting it, so a registration whose key the caller does not hold
        // is never admitted to the mesh. Requiring the full stake up front
        // prices the nuisance; it does not authenticate the PID.
        if (received < THRESHOLD) revert BelowThreshold();

        Pillar storage p = _pillars[pid];
        p.operator = msg.sender;
        p.staked = received;
        p.registeredAt = uint64(block.timestamp);
        p.endpoint = endpoint;
        totalStaked += received;

        _pids.push(pid);
        _pidIndexPlusOne[pid] = _pids.length;

        emit Registered(pid, msg.sender, received, endpoint);
    }

    /// @notice Add stake. Topping back up to THRESHOLD resumes rewards.
    function topUp(bytes32 pid, uint256 amount) external nonReentrant {
        Pillar storage p = _operatorPillar(pid);
        if (p.unstakeRequestedAt != 0) revert Unstaking();
        uint256 received = _pull(amount);
        // Re-checked after the transfer: a token with a transfer hook could
        // have re-entered requestUnstake, which would put this deposit on an
        // already-running cooldown.
        if (p.unstakeRequestedAt != 0) revert Unstaking();
        p.staked += received;
        totalStaked += received;
        emit ToppedUp(pid, received, p.staked);
    }

    function setEndpoint(bytes32 pid, string calldata endpoint) external {
        Pillar storage p = _operatorPillar(pid);
        if (bytes(endpoint).length > MAX_ENDPOINT_LENGTH) revert EndpointTooLong();
        p.endpoint = endpoint;
        emit EndpointSet(pid, endpoint);
    }

    /// @notice Leave the network. The Pillar stops being active at once;
    ///         the stake can be withdrawn after COOLDOWN. No fees are
    ///         recorded while unstaking.
    function requestUnstake(bytes32 pid) external {
        Pillar storage p = _operatorPillar(pid);
        if (p.unstakeRequestedAt != 0) revert Unstaking();
        p.unstakeRequestedAt = uint64(block.timestamp);
        p.unstakeFromDay = uint32(block.timestamp / 1 days);
        p.unstakeToDay = type(uint32).max;   // open until cancelled
        emit UnstakeRequested(pid, block.timestamp + COOLDOWN);
    }

    function cancelUnstake(bytes32 pid) external {
        Pillar storage p = _operatorPillar(pid);
        if (p.unstakeRequestedAt == 0) revert NotUnstaking();
        p.unstakeRequestedAt = 0;
        p.unstakeToDay = uint32(block.timestamp / 1 days);
        emit UnstakeCancelled(pid);
    }

    /// @notice Withdraw the whole stake after the cooldown and free the PID.
    function withdraw(bytes32 pid) external nonReentrant {
        Pillar storage p = _operatorPillar(pid);
        if (p.unstakeRequestedAt == 0) revert NotUnstaking();
        uint256 availableAt = uint256(p.unstakeRequestedAt) + COOLDOWN;
        if (block.timestamp < availableAt) revert CooldownActive(availableAt);

        uint256 amount = p.staked;
        address operator = p.operator;
        totalStaked -= amount;
        _removePid(pid);
        delete _pillars[pid];

        token.safeTransfer(operator, amount);
        emit Withdrawn(pid, operator, amount);
    }

    // ------------------------------------------------------------------
    // Oracle
    // ------------------------------------------------------------------

    /// @notice Record `day` (UTC day number, block.timestamp / 1 days) as
    ///         inactive for each PID. Idempotent per (pid, day). Skips PIDs
    ///         that are unregistered, unstaking, or were registered that day
    ///         or later. Each record costs min(1 REFI, stake - 99,999 REFI).
    function recordInactive(bytes32[] calldata pids, uint32 day) external onlyRole(ORACLE_ROLE) nonReentrant {
        uint32 today = uint32(block.timestamp / 1 days);
        if (day >= today || uint256(day) + MAX_BACKFILL_DAYS < today) revert DayOutOfRange(day);

        uint256 total;
        for (uint256 i = 0; i < pids.length; i++) {
            bytes32 pid = pids[i];
            Pillar storage p = _pillars[pid];
            if (p.operator == address(0)) continue;
            if (day <= uint32(p.registeredAt / 1 days)) continue;
            if (inactiveRecorded[pid][day]) continue;

            // The day is always recorded, whatever the Pillar's state now:
            // an operator who could suppress the record by sitting in (or
            // sandwiching the oracle's call with) the unstaking state would
            // erase the evidence that rewards are withheld on.
            inactiveRecorded[pid][day] = true;
            // The fee, though, is judged for the day itself: a Pillar that
            // had already asked to unstake was deactivated and earning
            // nothing, so it is recorded and not charged.
            // Only days spent ENTIRELY in the unstaking state are exempt.
            // The bounds are exclusive because the request and cancel days
            // are days the Pillar was up for all but a moment: an inclusive
            // range let an operator request at 23:59:50 and cancel at
            // 00:00:10 to buy two whole days for twenty seconds offline.
            bool unstakingThatDay =
                p.unstakeFromDay != 0 && day > p.unstakeFromDay && day < p.unstakeToDay;
            uint256 fee;
            if (!unstakingThatDay) {
                // Recorded against the Pillar whether or not a fee was owed:
                // this, not the stake level, is what deactivates it, so a
                // large buffer above the threshold no longer buys immunity.
                if (day > p.lastInactiveDay) p.lastInactiveDay = day;
                if (p.staked > FEE_FLOOR) {
                    uint256 headroom = p.staked - FEE_FLOOR;
                    fee = headroom < FEE_PER_DAY ? headroom : FEE_PER_DAY;
                    p.staked -= fee;
                    total += fee;
                }
            }
            emit InactiveDay(pid, day, fee, p.staked);
        }
        // Accrued, not sent: a recipient that cannot receive (a paused or
        // blocklisting token) must never be able to stop days being recorded,
        // because those records are what reward accounting reads.
        if (total > 0) {
            totalStaked -= total;
            pendingFees += total;
        }
    }

    // ------------------------------------------------------------------
    // Sweeps — permissionless, and only ever to the fee recipient
    // ------------------------------------------------------------------

    /// @notice Send accrued inactivity fees to the fee recipient. Anyone may
    ///         call it; the destination is not the caller's to choose.
    function sweepFees() external nonReentrant {
        uint256 amount = pendingFees;
        if (amount == 0) revert ZeroAmount();
        pendingFees = 0;
        address to = feeRecipient;
        token.safeTransfer(to, amount);
        emit FeesSwept(to, amount);
    }

    /// @notice Send tokens transferred to this contract outside `register` or
    ///         `topUp` to the fee recipient. Cannot touch stake or pending
    ///         fees: both are accounted, and only the surplus is movable.
    function sweepExcess() external nonReentrant {
        uint256 excess = token.balanceOf(address(this)) - totalStaked - pendingFees;
        if (excess == 0) revert ZeroAmount();
        address to = feeRecipient;
        token.safeTransfer(to, excess);
        emit ExcessSwept(to, excess);
    }

    // ------------------------------------------------------------------
    // Admin
    // ------------------------------------------------------------------

    /// @notice Where inactivity fees go (the rewards pool). Never this
    ///         contract: its balance is operators' stake.
    function setFeeRecipient(address feeRecipient_) external onlyRole(DEFAULT_ADMIN_ROLE) {
        // address(this) would strand every later fee in staked-but-unowned
        // balance, so it is refused alongside the zero address.
        if (feeRecipient_ == address(0) || feeRecipient_ == address(this)) revert ZeroAddress();
        feeRecipient = feeRecipient_;
        emit FeeRecipientSet(feeRecipient_);
    }

    // ------------------------------------------------------------------
    // Views — what Pillars and the portal read
    // ------------------------------------------------------------------

    /// @notice Admitted to the mesh and earning: at least THRESHOLD staked,
    ///         no unstake pending, and no inactive day recorded against it in
    ///         the last INACTIVE_GRACE_DAYS days.
    ///
    ///         The liveness term is what actually ejects an offline Pillar.
    ///         The stake term alone could not: the fee stops at FEE_FLOOR, so
    ///         a Pillar staked well above THRESHOLD would stay admitted for as
    ///         many days as it holds REFI above it. Nothing here takes more
    ///         from an operator than before — it only stops paying for a
    ///         buffer being mistaken for being online.
    function isActive(bytes32 pid) public view returns (bool) {
        Pillar storage p = _pillars[pid];
        if (p.operator == address(0) || p.unstakeRequestedAt != 0 || p.staked < THRESHOLD) {
            return false;
        }
        if (p.lastInactiveDay == 0) return true;
        return block.timestamp / 1 days > uint256(p.lastInactiveDay) + INACTIVE_GRACE_DAYS;
    }

    function pillarOf(bytes32 pid) external view returns (Pillar memory) {
        return _pillars[pid];
    }

    function operatorOf(bytes32 pid) external view returns (address) {
        return _pillars[pid].operator;
    }

    function stakeOf(bytes32 pid) external view returns (uint256) {
        return _pillars[pid].staked;
    }

    function endpointOf(bytes32 pid) external view returns (string memory) {
        return _pillars[pid].endpoint;
    }

    /// @notice Directory slots to walk, including slots emptied by a
    ///         withdrawal. It is the paging bound, not a count of Pillars.
    function pillarCount() external view returns (uint256) {
        return _pids.length;
    }

    /// @notice A page of directory slots. A slot holds a registered PID or
    ///         zero where one was withdrawn; readers skip the zeros. Slots
    ///         never move, so a reader paging through the directory across
    ///         several calls cannot miss a Pillar because another one left.
    function pidsPage(uint256 offset, uint256 limit) external view returns (bytes32[] memory page) {
        uint256 n = _pids.length;
        if (offset >= n) return new bytes32[](0);
        // limit may be uint256.max ("the rest"), so never add before comparing
        uint256 end = limit > n - offset ? n : offset + limit;
        page = new bytes32[](end - offset);
        for (uint256 i = offset; i < end; i++) {
            page[i - offset] = _pids[i];
        }
    }

    // ------------------------------------------------------------------
    // Internals
    // ------------------------------------------------------------------

    function _operatorPillar(bytes32 pid) private view returns (Pillar storage p) {
        p = _pillars[pid];
        if (p.operator == address(0)) revert NotRegistered();
        if (p.operator != msg.sender) revert NotOperator();
    }

    /// @dev Credits what actually arrived, not what was asked for.
    function _pull(uint256 amount) private returns (uint256 received) {
        if (amount == 0) revert ZeroAmount();
        uint256 before = token.balanceOf(address(this));
        token.safeTransferFrom(msg.sender, address(this), amount);
        received = token.balanceOf(address(this)) - before;
    }

    /// @dev Clears the slot instead of swapping the last PID into it: moving
    ///      a PID to a lower index would hide it from a reader that had
    ///      already paged past that index.
    function _removePid(bytes32 pid) private {
        _pids[_pidIndexPlusOne[pid] - 1] = bytes32(0);
        delete _pidIndexPlusOne[pid];
    }
}
