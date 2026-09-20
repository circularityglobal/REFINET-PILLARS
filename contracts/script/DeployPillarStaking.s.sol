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
        if (oracle != address(0) && admin == msg.sender) {
            staking.grantRole(staking.ORACLE_ROLE(), oracle);
        }
        vm.stopBroadcast();

        console2.log("PillarStaking:", address(staking));
    }
}
