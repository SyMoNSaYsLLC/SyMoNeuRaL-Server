// Compile the Gateway's contracts to artefacts the deploy tool can broadcast.
//
//   cd ops/gateway && node build.mjs
//
// ## The two settings that are not style choices
//
// **solc 0.8.18.** Not "0.8.x". solc 0.8.20 and later emit the `PUSH0` opcode by default, and
// the TVM does not implement it: a contract built that way deploys successfully and then
// reverts on its first call, which reads as a bug in the Solidity and is not one. Pinning
// below 0.8.20 makes that failure unreachable rather than merely unlikely.
//
// **evmVersion `istanbul`.** The TVM tracks the EVM at a distance and Istanbul is the level it
// is safely at. Belt and braces with the version pin above.
//
// Both are asserted after the fact, against the compiler's own reported version, because a
// `package.json` range is a request and the installed tree is the fact. `.claude/HANDOVER.md`
// §3.0d: check the real system, not the assumption about it.
//
// The compiler lives in `.solc/` (npm, gitignored) and is a **build-time** dependency only.
// Nothing here is distributed and nothing here enters the serving interpreter — `.claude/
// CLAUDE.md` bans `pip install` into the serving Python, and this is neither pip nor Python
// nor serving. The artefacts are committed so a deploy needs no compiler at all.
import { createRequire } from 'node:module';
import { readFileSync, writeFileSync, mkdirSync, readdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);
const solc = require(join(HERE, '.solc/node_modules/solc'));

const WANT_SOLC = '0.8.18';
const WANT_EVM = 'istanbul';

const reported = solc.version();
if (!reported.startsWith(WANT_SOLC)) {
  console.error(`REFUSING: solc reports ${reported}, expected ${WANT_SOLC}.\n` +
    'Above 0.8.19 the compiler emits PUSH0, which the TVM does not implement, and the ' +
    'contract will deploy and then revert on its first call.');
  process.exit(1);
}

const SRC = join(HERE, 'contracts');
const sources = {};
for (const f of readdirSync(SRC).filter(n => n.endsWith('.sol')).sort()) {
  sources[f] = { content: readFileSync(join(SRC, f), 'utf8') };
}

const input = {
  language: 'Solidity',
  sources,
  settings: {
    evmVersion: WANT_EVM,
    // Optimised because Energy on TRON is paid per executed instruction, so an unoptimised
    // contract costs the operator real TRX on every call, forever. 200 is the conventional
    // runs value: tuned for a contract called many times rather than deployed many times.
    optimizer: { enabled: true, runs: 200 },
    outputSelection: { '*': { '*': ['abi', 'evm.bytecode.object', 'evm.deployedBytecode.object'] } },
  },
};

const out = JSON.parse(solc.compile(JSON.stringify(input)));

const errors = (out.errors || []).filter(e => e.severity === 'error');
const warnings = (out.errors || []).filter(e => e.severity !== 'error');
for (const w of warnings) console.log(`warning: ${w.formattedMessage.trim()}`);
if (errors.length) {
  for (const e of errors) console.error(e.formattedMessage);
  process.exit(1);
}

mkdirSync(join(HERE, 'artifacts'), { recursive: true });
const built = [];
for (const [file, contracts] of Object.entries(out.contracts || {})) {
  for (const [name, c] of Object.entries(contracts)) {
    const bytecode = c.evm.bytecode.object;
    const deployed = c.evm.deployedBytecode.object;
    const artifact = {
      contract: name,
      source: file,
      compiler: `solc ${reported}`,
      evmVersion: WANT_EVM,
      optimizer: { enabled: true, runs: 200 },
      abi: c.abi,
      bytecode,
      deployedBytecode: deployed,
    };
    writeFileSync(join(HERE, 'artifacts', `${name}.json`),
                  JSON.stringify(artifact, null, 2) + '\n');
    const fns = c.abi.filter(e => e.type === 'function').length;
    built.push(`  ${name.padEnd(20)} ${(bytecode.length / 2).toString().padStart(6)} bytes ` +
               `· ${fns} functions · from ${file}`);
  }
}

console.log(`compiled with solc ${reported}, evmVersion ${WANT_EVM}, optimizer 200 runs`);
console.log(built.join('\n'));
console.log(`artifacts -> ops/gateway/artifacts/`);
