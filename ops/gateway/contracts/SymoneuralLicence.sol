// SPDX-License-Identifier: UNLICENSED
// © SymonSays LLC. All rights reserved.
//
// `UNLICENSED` is the SPDX token solc accepts for proprietary source, and it is the correct
// one here: `LICENSES.md` §7 puts our own code under "proprietary to SymonSays LLC", and this
// contract is the licensing business logic itself. Note what it does and does not mean —
// **deployed bytecode is public on any chain and this source will be published for
// verification on Tronscan.** Readable is not the same as licensed; this header reserves the
// right to copy it, which is the most a public contract can do.
pragma solidity 0.8.18;

/// @title SyMoNeuRaL Licence — a TRC-20-denominated licensing contract for the TRON TVM.
///
/// ## Why quotes, and not a price
///
/// The obvious contract has a public `price` and a `buy()`. This one deliberately does not,
/// because `.claude/CLAUDE.md` has a standing rule the site is built on: **licence fees are
/// quoted, not published.** A `price` variable is a published price list — permanently, on a
/// public ledger, for everyone, forever. So instead the operator signs an individual quote
/// off-chain and the buyer presents it here. Nothing is on-chain until someone actually pays,
/// and what is then on-chain is one settled transaction, which is unavoidable on any public
/// chain and is not a price list.
///
/// This also removes the worst failure mode of the naive design: there is no `setPrice` for an
/// operator to fat-finger by three decimal places on mainnet.
///
/// ## What this contract does NOT do, on purpose
///
/// - **It does not hold funds.** `redeem` moves the fee from the buyer straight to
///   `beneficiary`. A contract with a balance is a contract with a withdrawal function, an
///   owner key that can drain it, and an audit surface none of this needs.
/// - **It does not custody, mint, or price the token.** It is denominated in whatever TRC-20
///   the quote names — USDT on mainnet, a mock on a testnet — and touches it only through
///   `transferFrom`.
/// - **It does not gate access to anything.** It records that a payment cleared. What that
///   entitles anyone to is decided off-chain, by the operator, from the events below.
///   `docs/specs/symon-ml-review.md` finding 2 is the reason: a blockchain is public, so a
///   decryption key cannot live in it, and a contract cannot be the thing that keeps a secret.
/// - **It is not upgradeable.** No proxy, no `delegatecall`, no `selfdestruct`. If the terms
///   change, deploy a new one and point `SYMONEURAL_GATEWAY_CONTRACT` at it. An upgradeable licensing
///   contract means the operator can rewrite the terms of a licence somebody already bought.
///
/// ## Compilation target — this matters on TRON and is easy to get wrong
///
/// Built with **solc 0.8.18** and **evmVersion `istanbul`**. Not a style choice: solc 0.8.20+
/// emits the `PUSH0` opcode by default (Shanghai), which the TVM does not implement, and a
/// contract built that way deploys and then reverts on its first call — a failure that looks
/// like a bug in this source and is not. `ops/gateway/build.sh` pins both and refuses to
/// produce artefacts with any other setting.
interface ITRC20 {
    function transferFrom(address from, address to, uint256 value) external returns (bool);
}

contract SymoneuralLicence {
    /// The address whose signature makes a quote valid. Held on the operator's own machine —
    /// never in the environment of the public-facing web process. It is a *signing* key, not a
    /// funds key: it can authorise a quote and it cannot move anybody's money.
    address public quoteSigner;

    /// Where fees land. Separate from `quoteSigner` so the key that authorises and the account
    /// that receives are never the same key.
    address public beneficiary;

    address public owner;
    bool public paused;

    /// A settled licence, keyed by the quote's nonce so it is impossible to record two
    /// licences for one quote.
    struct Licence {
        address payer;
        address token;
        uint256 amount;
        bytes32 workspace;   // hash of the build configuration this licence covers
        uint64  atBlock;
        uint64  atTime;
    }

    mapping(uint256 => Licence) private _byNonce;
    uint256[] private _nonces;

    /// The read side the SyMoNeuRaL Gateway consumes. Everything below is a `view`; the
    /// gateway package on the server can call none of the state-changing functions because it
    /// cannot build, sign or broadcast a transaction, and its tests assert that.
    event LicenceIssued(
        uint256 indexed nonce,
        address indexed payer,
        bytes32 indexed workspace,
        address token,
        uint256 amount
    );
    event SignerChanged(address indexed from, address indexed to);
    event BeneficiaryChanged(address indexed from, address indexed to);
    event PausedSet(bool paused);
    event OwnerChanged(address indexed from, address indexed to);

    modifier onlyOwner() {
        require(msg.sender == owner, "not owner");
        _;
    }

    constructor(address quoteSigner_, address beneficiary_) {
        require(quoteSigner_ != address(0), "signer is zero");
        require(beneficiary_ != address(0), "beneficiary is zero");
        owner = msg.sender;
        quoteSigner = quoteSigner_;
        beneficiary = beneficiary_;
    }

    // ------------------------------------------------------------------ the one paying path

    /// Present an operator-signed quote and settle it.
    ///
    /// The buyer must have approved this contract for `amount` of `token` first — the ordinary
    /// TRC-20 two-step. `msg.sender` must be the `payer` the quote names, so a signed quote
    /// intercepted in transit is worthless to anyone else.
    ///
    /// Checks, effects, interactions — in that order, and the ordering is load-bearing. The
    /// nonce is burned *before* `transferFrom` is called, so a token whose transfer hook
    /// re-enters finds the nonce already spent.
    function redeem(
        uint256 nonce,
        address token,
        uint256 amount,
        bytes32 workspace,
        uint256 expiry,
        bytes calldata signature
    ) external {
        require(!paused, "paused");
        require(block.timestamp <= expiry, "quote expired");
        require(amount > 0, "amount is zero");
        require(_byNonce[nonce].payer == address(0), "quote already redeemed");

        // The chain id and this contract's own address are inside the digest, so a quote
        // signed for the Nile testnet cannot be replayed against the mainnet deployment, and
        // one signed for an older deployment cannot be replayed against its replacement.
        // Every detail line this surface prints names its network for the same reason.
        bytes32 digest = quoteDigest(
            msg.sender, nonce, token, amount, workspace, expiry
        );
        require(_recover(digest, signature) == quoteSigner, "quote not signed by the operator");

        _byNonce[nonce] = Licence({
            payer: msg.sender,
            token: token,
            amount: amount,
            workspace: workspace,
            atBlock: uint64(block.number),
            atTime: uint64(block.timestamp)
        });
        _nonces.push(nonce);

        // Checked, not assumed. A TRC-20 that returns false on failure instead of reverting
        // would otherwise leave a licence recorded that was never paid for — the exact shape
        // of a fail-open, one layer down.
        require(
            ITRC20(token).transferFrom(msg.sender, beneficiary, amount),
            "fee transfer failed"
        );

        emit LicenceIssued(nonce, msg.sender, workspace, token, amount);
    }

    /// The message the operator signs. Public so the off-chain signer and this contract can
    /// never disagree about what was signed — the signer calls this on a node to derive the
    /// digest rather than reimplementing the layout in Python.
    function quoteDigest(
        address payer,
        uint256 nonce,
        address token,
        uint256 amount,
        bytes32 workspace,
        uint256 expiry
    ) public view returns (bytes32) {
        bytes32 inner = keccak256(
            abi.encode(
                block.chainid, address(this), payer, nonce, token, amount, workspace, expiry
            )
        );
        // TRON wallets sign with the same "\x19Ethereum Signed Message:\n32" prefix Ethereum
        // uses; TronWeb's `sign` and `Trip`-style signers all produce it. Keeping the prefix
        // means an operator can sign a quote with an ordinary wallet and no bespoke tooling.
        return keccak256(abi.encodePacked("\x19Ethereum Signed Message:\n32", inner));
    }

    // ------------------------------------------------------------------------- the read side

    function licenceCount() external view returns (uint256) {
        return _nonces.length;
    }

    function nonceAt(uint256 i) external view returns (uint256) {
        return _nonces[i];
    }

    function licenceByNonce(uint256 nonce)
        external
        view
        returns (address payer, address token, uint256 amount, bytes32 workspace,
                 uint64 atBlock, uint64 atTime)
    {
        Licence storage l = _byNonce[nonce];
        return (l.payer, l.token, l.amount, l.workspace, l.atBlock, l.atTime);
    }

    /// `false` for every unknown pair, which is the only safe default. Nothing in this system
    /// treats an unreachable node or an unset nonce as a yes.
    function isLicensed(address payer, bytes32 workspace) external view returns (bool) {
        for (uint256 i = _nonces.length; i > 0; i--) {
            Licence storage l = _byNonce[_nonces[i - 1]];
            if (l.payer == payer && l.workspace == workspace) return true;
        }
        return false;
    }

    // ------------------------------------------------------------------------ operator admin

    function setQuoteSigner(address to) external onlyOwner {
        require(to != address(0), "signer is zero");
        emit SignerChanged(quoteSigner, to);
        quoteSigner = to;
    }

    function setBeneficiary(address to) external onlyOwner {
        require(to != address(0), "beneficiary is zero");
        emit BeneficiaryChanged(beneficiary, to);
        beneficiary = to;
    }

    /// Stops new redemptions. It cannot revoke a licence that already settled — somebody paid
    /// for that, and an owner key that can retract a purchased licence is a different and much
    /// worse product than this one.
    function setPaused(bool v) external onlyOwner {
        paused = v;
        emit PausedSet(v);
    }

    function transferOwnership(address to) external onlyOwner {
        require(to != address(0), "owner is zero");
        emit OwnerChanged(owner, to);
        owner = to;
    }

    // ------------------------------------------------------------------------------ internal

    /// 65-byte {r,s,v} recovery, with the two guards that every hand-rolled version omits.
    function _recover(bytes32 digest, bytes calldata sig) private pure returns (address) {
        require(sig.length == 65, "signature is not 65 bytes");
        bytes32 r;
        bytes32 s;
        uint8 v;
        assembly {
            r := calldataload(sig.offset)
            s := calldataload(add(sig.offset, 32))
            v := byte(0, calldataload(add(sig.offset, 64)))
        }
        if (v < 27) v += 27;
        // secp256k1 signatures are malleable: (r, s) and (r, n - s) both verify. Without this
        // bound a second, different-looking signature exists for every valid quote. It does
        // not let anyone forge a quote, but it does break "one signature, one quote".
        require(
            uint256(s) <= 0x7FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF5D576E7357A4501DDFE92F46681B20A0,
            "signature s is in the upper half"
        );
        require(v == 27 || v == 28, "signature v is invalid");
        address signer = ecrecover(digest, v, r, s);
        // ecrecover returns the zero address on failure rather than reverting, and
        // `quoteSigner` can never be zero (the constructor and setter both refuse it) — so
        // this is belt and braces on the one comparison that authorises a payment.
        require(signer != address(0), "signature does not recover");
        return signer;
    }
}
