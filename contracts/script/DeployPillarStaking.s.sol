// SPDX-License-Identifier: AGPL-3.0-or-later
pragma solidity 0.8.24;

import {Script, console2} from "forge-std/Script.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {PillarStaking} from "../src/PillarStaking.sol";

/// forge script script/DeployPillarStaking.s.sol --rpc-url apothem --broadcast
///
/// Env:
///   REFI_TOKEN      token address (mainnet REFI: 0x2D010d707da973E194e41D7eA52617f8F969BD23)
///   STAKING_ADMIN   the multisig that may set the fee recipient and grant ORACLE_ROLE
///   FEE_RECIPIENT   the rewards pool that receives inactivity fees
///   ORACLE          optional: the liveness monitor's address, granted ORACLE_ROLE
///                   (only when the deployer is also STAKING_ADMIN)
contract DeployPillarStaking is Script {
    function run() external returns (PillarStaking staking) {
        address token = vm.envAddress("REFI_TOKEN");
        address admin = vm.envAddress("STAKING_ADMIN");
        address feeRecipient = vm.envAddress("FEE_RECIPIENT");
        address oracle = vm.envOr("ORACLE", address(0));

        vm.startBroadcast();
        staking = new PillarStaking(IERC20(token), admin, feeRecipient);
        bool granted = oracle != address(0) && admin == msg.sender;
        if (granted) {
            staking.grantRole(staking.ORACLE_ROLE(), oracle);
        }
        vm.stopBroadcast();

        console2.log("PillarStaking:", address(staking));

        // STAKING_ADMIN is meant to be a multisig, in which case the deployer
        // cannot grant the role and the contract ships with no oracle. Say so
        // loudly: a silent skip leaves nobody recording inactive days and
        // nothing to notice it by.
        if (oracle != address(0) && !granted) {
            console2.log("");
            console2.log("!! ORACLE_ROLE WAS NOT GRANTED.");
            console2.log("!! The admin below is not the deployer, so it must grant the role itself:");
            console2.log("!!   admin :", admin);
            console2.log("!!   oracle:", oracle);
            console2.log("!! Call grantRole(ORACLE_ROLE, oracle) on the contract above, e.g.");
            console2.log("!!   cast send <staking> 'grantRole(bytes32,address)' \\");
            console2.log("!!     $(cast keccak ORACLE_ROLE) <oracle> --from <admin>");
            console2.log("!! Until then no inactive day can be recorded.");
        } else if (oracle == address(0)) {
            console2.log("");
            console2.log("Note: ORACLE not set; grant ORACLE_ROLE before the monitor can submit.");
        }
    }
}
