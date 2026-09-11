// SPDX-License-Identifier: UNLICENSED
// © SymonSays LLC. All rights reserved. See the header of SymoneuralLicence.sol — proprietary
// per LICENSES.md §7, and public-by-nature once deployed. Those two are not in conflict.
pragma solidity 0.8.18;

/// @title A test-only TRC-20, for exercising the licensing path on Nile or Shasta.
///
/// **There is no USDT on a TRON testnet.** Mainnet USDT is
/// `TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t` and it is not deployed on Nile or Shasta — verified
/// by `python3 -m apps.gateway`, which reads that exact address on all three networks and gets
/// a contract back from one of them. So a testnet rehearsal needs a token to denominate in,
/// and this is it: free, ours, and dependent on nobody.
///
/// ## It is not USDT and the page must never imply that it is
///
/// Exercising the mechanism on Nile demonstrates **the mechanism** — the quote, the approval,
/// the transfer, the event, the confirmation. It demonstrates nothing whatever about real
/// stablecoin settlement, liquidity, or fees. `docs/specs/gateway-completion.md` §5 says this
/// and the gateway module forces the network name into every detail line it prints, which is
/// the defence that stops a testnet rehearsal being mistaken for production.
///
/// Six decimals, matching USDT on TRON, so the amounts in a testnet rehearsal have the same
/// shape as the amounts in the real thing and nobody has to re-derive them by a factor of
/// 10^12 when the deployment moves to mainnet.
contract MockTRC20 {
    string public constant name = "SyMoNeuRaL Test Dollar";
    string public constant symbol = "SYMTEST";
    uint8 public constant decimals = 6;

    uint256 public totalSupply;
    address public immutable minter;

    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;

    event Transfer(address indexed from, address indexed to, uint256 value);
    event Approval(address indexed owner, address indexed spender, uint256 value);

    constructor() {
        minter = msg.sender;
    }

    /// Open to the deployer only. A public faucet mint would be fine on a testnet and is
    /// omitted anyway: this contract exists to rehearse a payment, not to be a faucet, and a
    /// mint anyone can call is one more thing to explain on a page about honest measurement.
    function mint(address to, uint256 value) external {
        require(msg.sender == minter, "not minter");
        totalSupply += value;
        balanceOf[to] += value;
        emit Transfer(address(0), to, value);
    }

    function transfer(address to, uint256 value) external returns (bool) {
        _move(msg.sender, to, value);
        return true;
    }

    function approve(address spender, uint256 value) external returns (bool) {
        allowance[msg.sender][spender] = value;
        emit Approval(msg.sender, spender, value);
        return true;
    }

    function transferFrom(address from, address to, uint256 value) external returns (bool) {
        uint256 allowed = allowance[from][msg.sender];
        // Unlimited approval is left untouched rather than decremented, the convention every
        // real TRC-20 follows. `SymoneuralLicence` checks the boolean return either way.
        if (allowed != type(uint256).max) {
            require(allowed >= value, "allowance exceeded");
            allowance[from][msg.sender] = allowed - value;
        }
        _move(from, to, value);
        return true;
    }

    function _move(address from, address to, uint256 value) private {
        require(to != address(0), "transfer to zero");
        uint256 bal = balanceOf[from];
        require(bal >= value, "balance exceeded");
        unchecked {
            balanceOf[from] = bal - value;
            balanceOf[to] += value;
        }
        emit Transfer(from, to, value);
    }
}
