// Execute the compiled contracts in a local EVM at the same hardfork the TVM tracks.
//
//   cd ops/gateway && node test_contracts.mjs
//
// ## Why this exists
//
// `build.mjs` proves the Solidity compiles. It proves nothing about whether `redeem` works,
// and "it compiled" is the licensing-contract version of "curl proved the endpoint answered"
// — the exact mistake `.claude/CLAUDE.md` records under *test in a real browser, not with
// curl*. A contract whose happy path has never executed is worse than one that is honestly
// absent, because it looks finished. Every revert below costs a real deployment cycle and,
// on mainnet, real TRX, so they are much cheaper to find here.
//
// **This is an EVM, not the TVM.** They are close but not identical, and this file does not
// claim otherwise. What it settles is contract *logic* — signature recovery, the replay guard,
// expiry, the checks-effects-interactions ordering, the TRC-20 boolean check. What it cannot
// settle is TVM-specific execution, Energy accounting, or address-format handling; those are
// settled by the Nile rehearsal in DEPLOY.md and by nothing before it.
//
// Run at the `istanbul` hardfork to match `build.mjs`'s `evmVersion`, so the code under test
// is the code that will be deployed rather than a re-compilation at friendlier settings.
import { createRequire } from 'node:module';
import { readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);
const M = (n) => join(HERE, '.solc/node_modules', n);

// `require`, not `import`: these packages expose CommonJS entry points via package.json
// `main`, and a bare ESM directory import of them is an ERR_UNSUPPORTED_DIR_IMPORT.
const { EVM } = require(M('@ethereumjs/evm'));
const { Common, Hardfork, Chain } = require(M('@ethereumjs/common'));
const { DefaultStateManager } = require(M('@ethereumjs/statemanager'));
const util = require(M('@ethereumjs/util'));
const { secp256k1 } = require(M('@noble/curves/secp256k1'));
const { keccak256: keccak_256 } = require(M('ethereum-cryptography/keccak.js'));

const { Address, hexToBytes, bytesToHex, concatBytes, setLengthLeft, bigIntToBytes } = util;

const art = (n) => JSON.parse(readFileSync(join(HERE, 'artifacts', `${n}.json`), 'utf8'));
const LICENCE = art('SymoneuralLicence');
const TOKEN = art('MockTRC20');

const results = [];
const check = (name, ok, detail = '') => {
  results.push({ name, ok });
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? '  -- ' + detail : ''}`);
};

// ------------------------------------------------------------------ accounts and helpers

const key = (n) => setLengthLeft(bigIntToBytes(BigInt(n)), 32);
const addrOf = (k) => new Address(keccak_256(secp256k1.getPublicKey(k, false).slice(1)).slice(-20));

const OPERATOR = key(0x5117);   // signs quotes. Not a funds key.
const BUYER = key(0xB0);
const IMPOSTOR = key(0xBAD);
const BENEFICIARY = new Address(hexToBytes('0x00000000000000000000000000000000000000be'));
const DEPLOYER = new Address(hexToBytes('0x00000000000000000000000000000000000000d0'));

const common = new Common({ chain: Chain.Mainnet, hardfork: Hardfork.Istanbul });
const stateManager = new DefaultStateManager();
const evm = await EVM.create({ common, stateManager });

const CHAIN_ID = common.chainId();

// The EVM's default block has `timestamp = 0`, which quietly made the expiry test vacuous:
// every expiry in the past is still in the future when now is the epoch, so the first run of
// this file reported "an expired quote is refused" as a FAIL and was right to. Give the chain
// a real clock so `block.timestamp <= expiry` is exercised in both directions.
const NOW = 1_786_000_000n;                 // a fixed point in 2026, not a wall clock
const BLOCK = {
  header: {
    number: 1n, timestamp: NOW, difficulty: 0n, gasLimit: 30_000_000n,
    coinbase: Address.zero(), prevRandao: new Uint8Array(32), baseFeePerGas: undefined,
    getBlobGasPrice: () => undefined,
  },
};

const word = (v) => setLengthLeft(typeof v === 'bigint' ? bigIntToBytes(v) : v, 32);
const sel = (sig) => keccak_256(new TextEncoder().encode(sig)).slice(0, 4);
const enc = (sig, ...words) => concatBytes(sel(sig), ...words.map(word));

async function deploy(artifact, args = new Uint8Array()) {
  const r = await evm.runCall({
    caller: DEPLOYER, to: undefined, gasLimit: 20_000_000n, block: BLOCK,
    data: concatBytes(hexToBytes('0x' + artifact.bytecode), args),
  });
  if (r.execResult.exceptionError) throw new Error(`deploy ${artifact.contract}: ${r.execResult.exceptionError.error}`);
  return r.createdAddress;
}

async function call(to, caller, data, { expectRevert = false } = {}) {
  const r = await evm.runCall({ caller, to, gasLimit: 20_000_000n, data, block: BLOCK });
  const err = r.execResult.exceptionError;
  if (err && !expectRevert) throw new Error(`call reverted: ${err.error} ${reason(r)}`);
  return { ok: !err, reason: reason(r), ret: r.execResult.returnValue };
}

// Solidity revert strings are ABI-encoded behind the Error(string) selector.
function reason(r) {
  const v = r.execResult.returnValue;
  if (!v || v.length < 68) return '';
  const len = Number(BigInt(bytesToHex(v.slice(36, 68))));
  return new TextDecoder().decode(v.slice(68, 68 + len));
}

// ------------------------------------------------------------------------------ deployment

const tokenAddr = await deploy(TOKEN);
const licenceAddr = await deploy(LICENCE, concatBytes(word(addrOf(OPERATOR).bytes), word(BENEFICIARY.bytes)));
check('both contracts deploy', !!tokenAddr && !!licenceAddr,
      `licence at ${licenceAddr.toString().slice(0, 10)}…`);

const buyer = addrOf(BUYER);
const FEE = 250_000_000n;                 // 250.000000 of a 6-decimal token. A test amount.
const WORKSPACE = keccak_256(new TextEncoder().encode('debian-13 · cuda-12.8 · sm_120'));

await call(tokenAddr, DEPLOYER, enc('mint(address,uint256)', buyer.bytes, FEE * 4n));
await call(tokenAddr, buyer, enc('approve(address,uint256)', licenceAddr.bytes, FEE * 4n));

// -------------------------------------------------------------------------- quote signing
// The digest layout is read back OUT of the contract rather than reimplemented here. If the
// two ever disagree the contract is the one that is right, and a test that reimplements the
// layout would agree with itself while disagreeing with the chain.
async function digestFor({ payer, nonce, token, amount, workspace, expiry }) {
  const r = await call(licenceAddr, DEPLOYER, enc(
    'quoteDigest(address,uint256,address,uint256,bytes32,uint256)',
    payer.bytes, nonce, token.bytes, amount, workspace, expiry));
  return r.ret;
}

function sign(digest, k) {
  const s = secp256k1.sign(digest, k);
  // 65-byte {r, s, v} with v in {27, 28}, the layout the contract's assembly reads.
  return concatBytes(setLengthLeft(bigIntToBytes(s.r), 32),
                     setLengthLeft(bigIntToBytes(s.s), 32),
                     new Uint8Array([s.recovery + 27]));
}

const FUTURE = NOW + 86_400n;    // a day out, comfortably unexpired
const PAST = NOW - 1n;           // one second ago -- expired, and only just, on purpose

async function redeem({ nonce, amount = FEE, expiry = FUTURE, signer = OPERATOR,
                        caller = buyer, sigFor = null }) {
  const q = { payer: sigFor || caller, nonce, token: tokenAddr, amount, workspace: WORKSPACE, expiry };
  const sig = sign(await digestFor(q), signer);
  return call(licenceAddr, caller, concatBytes(
    sel('redeem(uint256,address,uint256,bytes32,uint256,bytes)'),
    word(nonce), word(tokenAddr.bytes), word(amount), WORKSPACE, word(expiry),
    word(0xc0n),                       // offset to the bytes argument
    word(BigInt(sig.length)), concatBytes(sig, new Uint8Array(32 - sig.length % 32)),
  ), { expectRevert: true });
}

// ------------------------------------------------------------------------------ the happy path

let r = await redeem({ nonce: 1n });
check('a correctly signed quote redeems', r.ok, r.reason);

const bal = async (who) => {
  const x = await call(tokenAddr, DEPLOYER, enc('balanceOf(address)', who.bytes));
  return BigInt(bytesToHex(x.ret));
};
check('the fee reaches the beneficiary, and the contract holds nothing',
      (await bal(BENEFICIARY)) === FEE && (await bal(new Address(licenceAddr.bytes))) === 0n,
      `beneficiary ${await bal(BENEFICIARY)}, contract ${await bal(new Address(licenceAddr.bytes))}`);

const lic = await call(licenceAddr, DEPLOYER, enc('isLicensed(address,bytes32)', buyer.bytes, WORKSPACE));
check('the licence reads back as issued', BigInt(bytesToHex(lic.ret)) === 1n);

const cnt = await call(licenceAddr, DEPLOYER, sel('licenceCount()'));
check('licenceCount is 1', BigInt(bytesToHex(cnt.ret)) === 1n);

// --------------------------------------------------------------- the refusals, one per rule
// Each of these is a way the naive contract silently grants a licence. They are the whole
// reason this file exists — `docs/specs/symon-ml-review.md` finding 1 is a check that failed
// open, and every case below is that same failure wearing a different hat.

r = await redeem({ nonce: 1n });
check('a replayed quote is refused', !r.ok && /already redeemed/.test(r.reason), r.reason);

r = await redeem({ nonce: 2n, expiry: PAST });
check('an expired quote is refused', !r.ok && /expired/.test(r.reason), r.reason);

r = await redeem({ nonce: 3n, signer: IMPOSTOR });
check('a quote signed by anyone else is refused', !r.ok && /not signed by the operator/.test(r.reason), r.reason);

// Signed for the buyer, presented by someone else. The digest binds the payer, so recovery
// yields a different address and the signer check fails.
r = await redeem({ nonce: 4n, caller: addrOf(IMPOSTOR), sigFor: buyer });
check('a quote presented by someone other than its payer is refused',
      !r.ok && /not signed by the operator/.test(r.reason), r.reason);

// The amount is inside the digest, so raising it invalidates the signature rather than
// silently charging more.
{
  const q = { payer: buyer, nonce: 5n, token: tokenAddr, amount: FEE, workspace: WORKSPACE, expiry: FUTURE };
  const sig = sign(await digestFor(q), OPERATOR);
  r = await call(licenceAddr, buyer, concatBytes(
    sel('redeem(uint256,address,uint256,bytes32,uint256,bytes)'),
    word(5n), word(tokenAddr.bytes), word(FEE * 2n), WORKSPACE, word(FUTURE),
    word(0xc0n), word(BigInt(sig.length)), concatBytes(sig, new Uint8Array(32 - sig.length % 32)),
  ), { expectRevert: true });
  check('tampering with the amount invalidates the quote',
        !r.ok && /not signed by the operator/.test(r.reason), r.reason);
}

r = await redeem({ nonce: 6n, amount: 0n });
check('a zero-amount quote is refused', !r.ok && /amount is zero/.test(r.reason), r.reason);

// A licence that was never paid for must not be recorded. This is checks-effects-interactions
// seen from the outside: the state write is rolled back with the failed transfer.
{
  const poor = addrOf(key(0xF00D));
  const q = { payer: poor, nonce: 7n, token: tokenAddr, amount: FEE, workspace: WORKSPACE, expiry: FUTURE };
  const sig = sign(await digestFor(q), OPERATOR);
  r = await call(licenceAddr, poor, concatBytes(
    sel('redeem(uint256,address,uint256,bytes32,uint256,bytes)'),
    word(7n), word(tokenAddr.bytes), word(FEE), WORKSPACE, word(FUTURE),
    word(0xc0n), word(BigInt(sig.length)), concatBytes(sig, new Uint8Array(32 - sig.length % 32)),
  ), { expectRevert: true });
  const after = await call(licenceAddr, DEPLOYER, enc('isLicensed(address,bytes32)', poor.bytes, WORKSPACE));
  check('an unpaid quote records no licence', !r.ok && BigInt(bytesToHex(after.ret)) === 0n,
        `reverted with "${r.reason}", isLicensed=${BigInt(bytesToHex(after.ret))}`);
}

// Signature malleability: (r, s) and (r, n-s) both recover the same signer, so without the
// upper-half bound a second distinct signature exists for every quote.
{
  const N = secp256k1.CURVE.n;
  const q = { payer: buyer, nonce: 8n, token: tokenAddr, amount: FEE, workspace: WORKSPACE, expiry: FUTURE };
  const d = await digestFor(q);
  const s0 = secp256k1.sign(d, OPERATOR);
  const flipped = concatBytes(setLengthLeft(bigIntToBytes(s0.r), 32),
                              setLengthLeft(bigIntToBytes(N - s0.s), 32),
                              new Uint8Array([(s0.recovery ^ 1) + 27]));
  r = await call(licenceAddr, buyer, concatBytes(
    sel('redeem(uint256,address,uint256,bytes32,uint256,bytes)'),
    word(8n), word(tokenAddr.bytes), word(FEE), WORKSPACE, word(FUTURE),
    word(0xc0n), word(BigInt(flipped.length)), concatBytes(flipped, new Uint8Array(32 - flipped.length % 32)),
  ), { expectRevert: true });
  check('a malleated signature is refused', !r.ok && /upper half/.test(r.reason), r.reason);
}

// ------------------------------------------------------------------------------ operator admin

r = await call(licenceAddr, buyer, enc('setPaused(bool)', 1n), { expectRevert: true });
check('a stranger cannot pause the contract', !r.ok && /not owner/.test(r.reason), r.reason);

await call(licenceAddr, DEPLOYER, enc('setPaused(bool)', 1n));
r = await redeem({ nonce: 9n });
check('pausing stops new redemptions', !r.ok && /paused/.test(r.reason), r.reason);

// The licence bought before the pause survives it. An owner key that can retract a purchased
// licence is a different and much worse product than this one.
const still = await call(licenceAddr, DEPLOYER, enc('isLicensed(address,bytes32)', buyer.bytes, WORKSPACE));
check('pausing does not revoke a licence already paid for', BigInt(bytesToHex(still.ret)) === 1n);

await call(licenceAddr, DEPLOYER, enc('setPaused(bool)', 0n));
r = await redeem({ nonce: 10n });
check('unpausing restores redemption', r.ok, r.reason);

// ------------------------------------------------- a fixture for the Python decoding side
//
// `licensing/verify.py` decodes this exact return shape, and its own tests build the fake
// node response with OUR encoder -- so a wrong belief about the layout would agree with
// itself and pass. Write out what the EVM actually returned and let Python decode that
// instead. bytes32 is left-aligned while every other word is right-aligned, which is the
// specific thing a self-consistent test cannot catch.
const rec = await call(licenceAddr, DEPLOYER, enc('licenceByNonce(uint256)', 1n));
check('licenceByNonce returns six words for a settled licence', rec.ok && rec.ret.length === 192,
      `${rec.ret.length} bytes`);

const fixture = {
  note: 'Emitted by ops/gateway/test_contracts.mjs from a real EVM run. Do not hand-edit.',
  signature: 'licenceByNonce(uint256)',
  nonce: 1,
  raw: bytesToHex(rec.ret).replace(/^0x/, ''),
  expect: {
    payer_hex: bytesToHex(buyer.bytes).replace(/^0x/, ''),
    token_hex: bytesToHex(tokenAddr.bytes).replace(/^0x/, ''),
    amount: FEE.toString(),
    workspace_hex: bytesToHex(WORKSPACE).replace(/^0x/, ''),
  },
};
writeFileSync(new URL('./artifacts/licence-record.json', import.meta.url),
              JSON.stringify(fixture, null, 2) + '\n');
console.log('\nwrote artifacts/licence-record.json for the Python decoder tests');

// -------------------------------------------------------------------------------- the verdict
const bad = results.filter(x => !x.ok).length;
console.log(`\n${results.length - bad}/${results.length} passed`);
process.exit(bad ? 1 : 0);
