# SymonSaysLLC Core Identity  
## ├── SymonSaysLLC builds SyMoNeuRaL  
## ├── SyMoNeuRaL-* are systems  
## ├── Symon-* models inside SyMoNeuRaL  
## └── Symon-* software on SyMoNeuRaL  
  
## ==SyMoNeuRaL-*==  
###            ==| symoneural-platform==  
          ==│   ├── system architecture==  
    ==│   ├── application environment==  
    ==│   ├── runtime orchestration==  
    ==│   └── platform integration==  
  
```
    ├── symoneural-network
```
```
    │   ├── service communication
    │   ├── routing
    │   ├── inter-component comms
    │   └── connectivity
```
```
    │
```
```
    ├── symoneural-build
    │   ├── source builds
    │   ├── toolchains
    │   ├── packaging
    │   ├── Yocto/OE integration
    │   └── Build workflows (repeat)
```
```
    │
```
```
    ├── symoneural-release
    │   ├── release artifacts
    │   ├── package publication
    │   ├── versioning
    │   ├── checksums
    │   └── release verification
```
```
    │
```
```
    ├── symoneural-custody
    │   ├── provenance
    │   ├── licensing records
    │   ├── artifact identity
    │   ├── recovery metadata
    │   ├── private custody
    │   └── integrity verification
```
  
```
        Symon-*
```
```
        │
```
```
        ├── symon-engine
        │   ├── native runtime
        │   ├── CUDA execution
        │   ├── inference engine
        │   └── runtime libraries
```
```
        │
```
```
        ├── symon-gateway
        │   ├── request routing
        │   ├── service gateway
        │   └── runtime communication
```
```
        │
```
```
        ├── symon-api
        │   ├── application API
        │   ├── control plane
        │   └── web ui interface
        │
        ├── symon-web
        │   ├── web runtime
        │   ├── frontend delivery
        │   └── web integration
```
```
        │
```
```
        ├── symon-cuda-test
        │   ├── CUDA-only
        │   ├── GPU allocation
        │   ├── GPU kernel execution
        │   ├── transfer verification
        │   └── model-free validation
```
```
        │
```
```
        ├── symon-blob-audit
        │   ├── blob discovery
        │   ├── classification
        │   ├── filesystem inventory
        │   ├── runtime inventory
        │   └── AI payload detection
```
```
        │
```
```
        ├── symon-blob-acquire
        │   ├── blob download
        │   ├── source verification
        │   ├── revision verification
        │   └── acquisition logging
```
```
        │
```
```
        ├── symon-blob-verify
        │   ├── SHA256 verified
        │   ├── artifact identity
        │   ├── format verified
        │   ├── provenance verified
        │   └── activation eligibility
```
```
        │
```
```
        ├── symon-blob-purge
        │   ├── approved blob deletion
        │   ├── model weight purge
        │   ├── adapter purge
        │   ├── encoder purge
        │   ├── checkpoint purge
        │   ├── AI cache purge
        │   └── deletion logging
```
```
        │
```
```
        ├── symon-runtime-verify
        │   ├── process verified
        │   ├── binary identified
        │   ├── dependency verified
        │   ├── service verified
        │   └── runtime integrity
```
```
        │
```
```
        └── Symon Artifacts
            ├── `symon-*`
            ├── `symon-model-*`
            ├── `symon-adapter-*`
            ├── `symon-encoder-*`
            └── `symon-runtime-*`
```
  
```
Third-Party / Vendor / System Components
├── retain upstream names  
├── do not rebrand  
├── preserve upstream provenance  
├── preserve upstream licensing  
└── examples  
    ├── NVIDIA  
    ├── CUDA  
    ├── TensorRT  
    ├── PyTorch  
    ├── OpenEmbedded  
    ├── BitBake  
    ├── Caddy  
    └── PostgreSQL  
```
  
```
Naming Conventions
│
├── SymonSaysLLC
│   ├── legal identity
│   ├── business identity
│   └── ownership identity
│
├── SyMoNeuRaL
│   ├── system identity
│   ├── platform identity
│   ├── network identity
│   └── ecosystem identity
│
├── symoneural-*
│   ├── system-level components
│   ├── platform-level components
│   └── infrastructure components
│
├── Symon
│   ├── model identity
│   ├── agent identity
│   └── runtime identity
│
├── symon-*
│   ├── executable identity
│   ├── command identity
│   ├── runtime identity
│   ├── script identity
│   ├── component identity
│   └── artifact identity
│
├── symon_*
│   └── importable Python module identity when required
│
└── third-party names
    └── unchanged
```
```

```
  
  
Prompt to coder  
  
RESUME — PRE-MUTATION AUDIT ONLY  
  
The canonical naming authority is now:  
  
SymonSaysLLC  
  = legal / business / ownership identity  
  
SyMoNeuRaL  
  = system / platform / network / ecosystem identity  
  
symoneural-*  
  = system / platform / infrastructure components  
  
Symon  
  = model / agent / runtime identity  
  
symon-*  
  = executable / command / runtime / script / component / artifact identity  
  
symon_*  
  = importable Python module identity when required  
  
Third-party/vendor/system names  
  = retain upstream identity unchanged  
  
Core rule:  
  
  SymonSaysLLC builds SyMoNeuRaL  
  SyMoNeuRaL-* are systems  
  Symon-* models exist inside SyMoNeuRaL  
  Symon-* software runs on SyMoNeuRaL  
  
Canonical project root remains:  
  
  /home/google/Symoneural  
  
======================================================================  
CURRENT AUTHORIZATION  
======================================================================  
  
AUDIT / CLASSIFICATION ONLY.  
  
NO blob deletion.  
NO file deletion.  
NO rename.  
NO move.  
NO service rename.  
NO binary rename.  
NO systemd modification.  
NO source modification.  
NO commit.  
NO stash.  
NO reset.  
NO model download.  
NO package installation/removal.  
NO Claude removal yet.  
  
Evidence/log files may be created ONLY outside the repository under one  
timestamped audit directory.  
  
======================================================================  
GOAL  
======================================================================  
  
Before rebranding or purging anything, determine:  
  
1. Which current scripts/tools are actually required.  
2. Which current scripts/tools are actually wired.  
3. Which scripts overlap or duplicate another authority.  
4. Which project-owned scripts should eventually become symon-*.  
5. Which platform/system tooling should remain/become symoneural-*.  
6. Which files are third-party and must retain upstream names.  
7. Which AI objects are actual blobs to purge.  
8. Which AI-looking files are source/scripts and must NOT be purged.  
9. Which installed AI applications/runtimes, including Claude, are separate  
   purge targets.  
10. Whether the current runtime can operate in a blob-ABSENT state using the  
    future symon-cuda-test path.  
  
======================================================================  
A. SCRIPT / TOOL WIRING AUDIT  
======================================================================  
  
Inventory project-owned executable/tooling candidates across the canonical  
project.  
  
Include at minimum:  
  
  *.sh  
  executable *.py  
  *.mjs used as commands/tests/build tools  
  executable native helper programs  
  ops/  
  scripts/  
  tools/  
  tests/  
  training tooling  
  build tooling  
  deploy tooling  
  model acquisition/conversion/verification tooling  
  
Do NOT classify a file as a script merely from its extension.  
  
For every candidate determine:  
  
  current absolute path  
  owner: PROJECT / THIRD-PARTY / UNKNOWN  
  executable or importable module  
  current responsibility  
  current consumer(s)  
  invocation path  
  inputs  
  outputs  
  dependencies  
  whether used by:  
      systemd  
      another retained script  
      application source  
      build system  
      packaging  
      Yocto recipe  
      test harness  
      supported operator workflow  
  duplicate/overlap with another tool  
  current test/verification path  
  current status:  
      WIRED  
      PARTIALLY_WIRED  
      UNWIRED  
      DUPLICATE  
      THIRD_PARTY  
      UNKNOWN  
  
Then map each PROJECT-owned candidate to one proposed namespace:  
  
  SYMON  
  SYMONEURAL  
  TBD  
  UNKNOWN  
  
Do NOT rename yet.  
  
For SYMON candidates propose a future name only, for example:  
  
  symon-engine-*  
  symon-runtime-*  
  symon-blob-*  
  symon-cuda-*  
  symon-api-*  
  symon-web-*  
  symon-gateway-*  
  
For system/platform-level tools propose symoneural-* only when their  
responsibility genuinely spans the SyMoNeuRaL system rather than operating  
as a Symon component.  
  
======================================================================  
B. "NO UNWIRED MIGRATION" RULE  
======================================================================  
  
A project-owned tool is eligible for canonical migration/rebranding only if  
one of these can be proven:  
  
  systemd consumer  
  application consumer  
  build-system consumer  
  packaging consumer  
  test-harness consumer  
  another retained canonical tool  
  explicit supported operator command with a defined verification procedure  
  
A script that merely exists or "could be useful" is NOT wired.  
  
Do not propose an UNWIRED script for active migration.  
  
Instead classify it:  
  
  TBD / historical  
  DUPLICATE  
  or UNKNOWN  
  
======================================================================  
C. DUPLICATE AUTHORITY AUDIT  
======================================================================  
  
Identify tools that appear to perform the same responsibility.  
  
Examples:  
  
  multiple engine-build scripts  
  multiple model-download scripts  
  multiple runtime verification scripts  
  multiple deployment scripts  
  multiple CUDA probes  
  multiple model verification tools  
  multiple purge/audit scripts  
  
For every overlap determine:  
  
  which is currently consumed  
  which is newer  
  which contains unique behavior  
  whether behavior can eventually consolidate into one authority  
  
Do NOT merge them in this phase.  
  
======================================================================  
D. BLOB PURGE CLASSIFICATION  
======================================================================  
  
Separately inventory actual AI payload/blob candidates.  
  
The purge target includes learned/downloaded/generated payloads such as:  
  
  model weights  
  GGUF models  
  safetensors weights  
  checkpoints  
  LoRA/adapter weights  
  learned embeddings  
  learned text/image encoders  
  VAE weights  
  UNet weights  
  transformer weight shards  
  quantized/converted model outputs  
  model-specific caches  
  downloaded model repositories containing payloads  
  
Do NOT classify source as a blob merely because its name contains:  
  
  model  
  llama  
  adapter  
  tokenizer  
  encoder  
  transformer  
  diffusion  
  CUDA  
  AI  
  
Examples that are normally SOURCE rather than blobs:  
  
  modeling_llama.py  
  adapter.py  
  tokenizer.py  
  conversion scripts  
  training scripts  
  CUDA source  
  test code  
  
Generic extensions such as:  
  
  .bin  
  .pt  
  .pth  
  
must be content/context classified.  
  
Do NOT assume every file with those extensions is a model.  
  
======================================================================  
E. STORAGE ROUTES  
======================================================================  
  
Use the previously established mount topology.  
  
Cover persistent/local and intentionally reachable external routes,  
including:  
  
  /  
  /home  
  /yocto  
  /boot/efi  
  /mnt/gdrive  
  /home/google/thinclient_drives  
  /run/user/1000/gvfs  
  /run/user/1000/doc  
  /run  
  /tmp  
  /dev/shm  
  
Handle mounted filesystems individually.  
  
Pseudo-filesystems:  
  
  /proc  
  /sys  
  /dev  
  cgroups  
  debugfs  
  tracefs  
  EFI variables  
  
must use their specialized audit method rather than ordinary recursive blob  
deletion logic.  
  
Do not modify external Google Drive or XRDP storage.  
  
Inventory/classify only.  
  
======================================================================  
F. CLAUDE / INSTALLED AI SOFTWARE  
======================================================================  
  
Claude remains a future purge target, but it is NOT a model blob.  
  
Inventory its complete installed/runtime footprint separately.  
  
Known examples from prior evidence include:  
  
  /home/google/.local/bin/claude  
  /home/google/.local/share/claude/versions/2.1.236  
  /usr/lib/claude-desktop/resources/chrome-native-host  
  /home/google/.claude/  
  /home/google/.config/Claude/  
  
Determine:  
  
  install method  
  package ownership  
  binaries  
  desktop integration  
  processes  
  services/daemon state  
  user configuration  
  caches  
  logs  
  session state  
  
Also identify whether anything under the canonical SyMoNeuRaL source tree  
named ".claude" contains PROJECT HISTORY/SOURCE versus disposable Claude  
runtime state.  
  
Do NOT delete any of it yet.  
  
======================================================================  
G. CUDA / NATIVE RUNTIME RETENTION  
======================================================================  
  
Explicitly preserve:  
  
  NVIDIA driver  
  CUDA 13.3  
  CUDA device infrastructure  
  native Symon engine source  
  native runtime libraries  
  compiler/build tooling  
  
Determine what existing project-owned CUDA tests/probes can be reused for the  
future:  
  
  symon-cuda-test  
  
The future test must require:  
  
  NO model  
  NO adapter  
  NO tokenizer  
  NO learned encoder  
  NO AI framework inference  
  NO network download  
  
It must verify actual CUDA operation:  
  
  GPU detected  
  allocation  
  host→device transfer  
  kernel execution  
  synchronization  
  device→host transfer  
  deterministic result validation  
  clean failure reporting  
  
Do not implement or rename it yet.  
  
======================================================================  
H. PURGE RECOVERY METADATA  
======================================================================  
  
For every true blob candidate record enough information to reacquire it  
without retaining another local copy:  
  
  original absolute path  
  size  
  SHA256  
  component/model identity  
  format  
  upstream source when known  
  revision when known  
  provenance record when known  
  license identity when known  
  current consumer when known  
  
UNKNOWN remains UNKNOWN.  
  
Do not invent provenance.  
  
symoneural_tbd must NOT become a hidden model/blob backup.  
  
======================================================================  
I. EVIDENCE  
======================================================================  
  
Create exactly one timestamped evidence root outside the repository:  
  
  /home/google/symoneural-prepurge-audit-<UTC timestamp>/  
  
Use machine-readable/plain evidence.  
  
Include at minimum:  
  
  SCRIPT-WIRING.tsv  
  SCRIPT-OVERLAP.tsv  
  PROPOSED-NAMING.tsv  
  BLOB-CANDIDATES.tsv  
  BLOB-SHA256.tsv  
  CLAUDE-INVENTORY.tsv  
  CUDA-RETAIN.tsv  
  UNKNOWN.tsv  
  ERRORS.log  
  SHA256SUMS  
  
Do not create narrative Markdown reports.  
  
Do not alter /home/google/Symoneural while producing this evidence.  
  
======================================================================  
J. REQUIRED FINAL DECISION TABLE  
======================================================================  
  
Return a concise table in terminal/chat containing:  
  
CURRENT PATH  
OWNER  
CURRENT ROLE  
CONSUMER  
WIRING  
OVERLAP  
CLASSIFICATION  
FUTURE NAMESPACE  
PROPOSED NAME  
ACTION  
  
Allowed ACTION values:  
  
  MIGRATE  
  CONSOLIDATE  
  KEEP-UPSTREAM  
  PURGE-BLOB  
  PURGE-AI-RUNTIME  
  TBD  
  UNKNOWN-STOP  
  
This table is a proposal only.  
  
NO action may actually be performed yet.  
  
======================================================================  
STOP CONDITIONS  
======================================================================  
  
STOP if:  
  
  ownership cannot be determined  
  source vs blob cannot be determined  
  a supposedly unwired script has an unexpected live consumer  
  a supposedly disposable blob is required by something outside the expected  
  AI runtime  
  a third-party source would require rebranding  
  provenance would have to be guessed  
  a required path cannot be read  
  an audit command fails in a way that makes coverage incomplete  
  
Return:  
  
  STOP — USER ACTION REQUIRED  
  
with the exact unresolved object and reason.  
  
======================================================================  
END STATE OF THIS PHASE  
======================================================================  
  
NO FILES RENAMED.  
NO FILES DELETED.  
NO BLOBS PURGED.  
NO CLAUDE REMOVED.  
NO SERVICES MODIFIED.  
NO DOWNLOADS.  
NO REPOSITORY MODIFICATIONS.  
  
Only evidence/classification exists.  
  
Then STOP and give me the decision tables.  
  
