ACCEPT AUDIT EVIDENCE, BUT DO NOT USE THE CURRENT DECISION TABLE AS A
DELETION OR RENAME MANIFEST.

NO WRITES.
NO RENAMES.
NO DELETIONS.
NO SERVICE START.
NO DOWNLOADS.

The four SyMoNeuRaL services being stopped is now the expected purge-safe
baseline. Keep them stopped.

======================================================================
POLICY CORRECTIONS
======================================================================

1. ALL AI BLOBS ARE PURGE TARGETS

The user's final policy is:

  purge AI/model BLOB payloads
  preserve useful source/scripts/tooling
  preserve metadata sufficient for reacquisition
  do not preserve hidden copies of blobs

Therefore reclassify:

  backend/models/llm/symon-1.0-7b-q4_k_m.gguf
      PURGE-BLOB

  training/adapter/symoneural-lora.gguf
      PURGE-BLOB

  /var/lib/symon-agent/models/bonsai-27b/**
      PURGE-BLOB

  /var/lib/symon-imaging/models/z-image-turbo/**
      PURGE-BLOB

  ~/Downloads/model-0000*.safetensors
      PURGE-BLOB

  Chrome OptGuideOnDeviceModel learned weights
      PURGE-BLOB

And apply the same classification to every other proved learned model,
adapter, encoder, checkpoint, quantized model, converted model or learned
payload.

An active consumer does NOT change PURGE-BLOB into KEEP.

Do not rename a blob that will be purged.

======================================================================
2. SOURCE IS NOT BLOB
======================================================================

KEEP source/scripts/tooling unless separately classified obsolete.

Examples:

  *.py model implementations
  tokenizer source
  adapter source
  conversion scripts
  acquisition scripts
  training scripts
  CUDA source
  build scripts
  third-party source repositories

Do not purge based solely on AI-related filenames.

======================================================================
3. CANONICAL NAMING AUTHORITY
======================================================================

SymonSaysLLC
  legal / business / ownership

SyMoNeuRaL
  system / platform / network / ecosystem

symoneural-*
  platform/network/build/release/custody/infrastructure

Symon
  model / agent / runtime

symon-*
  executable / command / runtime / script / component / artifact

symon_*
  importable Python module where required

Therefore these FUTURE component identities are SYMON:

  symon-engine
  symon-gateway
  symon-api
  symon-web
  symon-cuda-test
  symon-blob-audit
  symon-blob-acquire
  symon-blob-verify
  symon-blob-purge
  symon-runtime-verify

Do not perform those renames now.

Reclassify the existing api/gateway/web runtime names as CURRENT LEGACY NAMES
with future namespace SYMON.

Platform-wide deployment/build/release/custody infrastructure may remain
SYMONEURAL when its actual responsibility is platform-wide.

Third-party/vendor names remain unchanged.

======================================================================
4. NO UNWIRED SCRIPT MIGRATION
======================================================================

/opt/symon/restream.sh:

  PROJECT SCRIPT
  UNWIRED
  TBD

Preserve its bytes.
Do not purge it.
Do not rename it into active Symon tooling.
It becomes eligible for Symon naming only if a current supported consumer is
later established.

/symonexecute:

  NON-AI
  OBSOLETE/GENERATED
  TBD recovery candidate

Do not treat it as a Symon component.

======================================================================
5. CLAUDE
======================================================================

Installed Claude application/runtime/state remains:

  PURGE-AI-RUNTIME

But preserve PROJECT SOURCE/SCRIPTS independently of where they are found.

For:

  ~/ClaudeAlienware
  ~/Claude
  ~/ClaudePromptLogs
  ~/.claude-science

perform a READ-ONLY structural inventory sufficient to distinguish:

  PROJECT SOURCE/SCRIPT
  personal/document material
  Claude runtime/cache/session state

Allowed evidence:

  path
  type
  size
  mode
  owner
  executable bit
  file/MIME classification
  SHA256

Do not copy contents.
Do not delete contents.
Do not expose secrets.

Anything proved to be reusable project source/script is NOT part of the
automatic Claude purge.

Everything proved to be Claude application/runtime/cache/session state becomes
PURGE-AI-RUNTIME.

Ambiguous material remains UNKNOWN.

======================================================================
6. HASH EVERY PURGE BLOB
======================================================================

Before any future deletion, every unique regular payload object must have a
SHA256 recorded.

For Hugging Face/content-addressed stores:

  retain repo id
  retain revision
  retain relative path
  retain content-addressed object identity
  AND calculate SHA256 of each unique regular blob object exactly once

Avoid hashing the same inode/object repeatedly through symlinks.

Repo/revision alone is provenance, not sufficient byte identity.

Update BLOB-SHA256.tsv accordingly.

No blob bytes may be copied into symoneural_tbd.

======================================================================
7. /boot/efi COVERAGE
======================================================================

The user requested all storage routes be covered.

Perform a read-only privileged inventory of /boot/efi.

If the current execution environment cannot perform sudo interactively:

  STOP — OPERATOR READ REQUIRED

and provide the exact minimal read-only sudo command.

Do not classify /boot/efi as out of scope.

======================================================================
8. XRDP REDIRECTED STORAGE
======================================================================

/home/google/thinclient_drives is currently a disconnected external XRDP FUSE
route.

Do not modify it.

Record:

  EXTERNAL_ROUTE_UNAVAILABLE

This does not block classification of local storage, but it DOES block the
eventual claim:

  ALL REACHABLE STORAGE ROUTES VERIFIED

until that route is available and scanned or the operator explicitly removes
it from the certification scope.

======================================================================
9. CUDA TEST
======================================================================

Retain CUDA/NVIDIA/native build infrastructure.

The existing --list-devices probe is only a partial reuse candidate.

Future symon-cuda-test must independently prove:

  CUDA device selection
  allocation
  host -> device copy
  GPU kernel execution
  synchronization
  device -> host copy
  deterministic result verification

with:

  NO model
  NO adapter
  NO tokenizer
  NO learned encoder
  NO inference framework dependency
  NO network

Do not implement yet.

======================================================================
10. RETURN REVISED EVIDENCE ONLY
======================================================================

Update the machine-readable audit evidence and decision table to reflect these
policy corrections.

NO destructive action.

Return:

  REVISED BLOB PURGE COUNT
  REVISED BLOB BYTE TOTAL
  REVISED SCRIPT/NAMESPACE TABLE
  CLAUDE STRUCTURAL CLASSIFICATION
  HF SHA256 COVERAGE
  /boot/efi coverage status
  XRDP route status
  remaining UNKNOWN rows

Then STOP.