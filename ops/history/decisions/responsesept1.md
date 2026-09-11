SEPT1.md — CONTROLLED CORRECTION PASS ONLY

Sept1.md has completed independent review.

Do NOT begin implementation.

Do NOT modify:

  INTAKE.md
  PROJECT-TASKS.md
  backend/
  frontend/
  site/
  web/
  control/
  scripts/
  tools/
  training/
  engines/
  ops/
  services
  packages
  models
  runtime configuration

You are authorized to modify ONLY:

  /home/google/Symoneural/Sept1.md

This is a controlled DOCUMENT CORRECTION PASS.

Do not silently make product decisions.
Do not implement anything described by the plan.

======================================================================
1. LIVE STACK TAXONOMY CONTRADICTION
======================================================================

§5 currently says logical applications exclude shared infrastructure /
operator surfaces including accounts, gateway and controlboard/account, while
the 20-row master table counts Gateway, Controlboard and Accounts among the
logical applications.

Resolve this without simply changing 20 to 17.

Create an explicit taxonomy, for example:

  CUSTOMER_APPLICATION
  SHARED_APPLICATION
  EMBEDDED_APPLICATION_SURFACE
  PLATFORM_SURFACE
  OPERATOR_SURFACE
  INFORMATIONAL_PAGE

Reconcile every current table row into exactly one appropriate category.

Return separate counts for:

  customer applications
  shared applications
  embedded application surfaces
  platform/operator surfaces
  informational/non-application pages

Keep a total surface inventory, but do not call every user-visible surface an
application.

The customer-slot standard applies to CUSTOMER_APPLICATION objects, not
automatically to every platform/operator surface.

======================================================================
2. DONNIE SLOT — DEFINITION IS NOT IMPLEMENTATION
======================================================================

Correct §11 so normative architecture is never used as proof of CURRENT
implementation.

For every Donnie/DispatchOS indicator distinguish where needed:

  DEFINED
  PRESENT
  WIRED
  VERIFIED
  EXISTING-INCOMPLETE
  MISSING

In particular re-evaluate:

  CUSTOMER_IDENTITY
  AUTH_SLOT
  ENTITLEMENT_SLOT
  SHARED_SERVICE_MAP
  CONFIG_SLOT
  ASSET_SLOT
  EXPORT_SCOPE
  RELEASE_IDENTITY
  CUSTODY_RECORD
  TEST_PATH

Do not mark Donnie's CUSTOMER_IDENTITY fully CURRENT merely because the name
Donnie is defined if the required customer/account identity is not actually
represented in the shared accounts authority.

Do not mark SHARED_SERVICE_MAP CURRENT merely because the architecture says
those services should be consumed.

For each shared service distinguish:

  architecturally required
  referenced by source
  runtime wired
  runtime verified

======================================================================
3. PROVENANCE / LICENCE LANGUAGE
======================================================================

Correct D-1 and every equivalent statement.

Evidence currently establishes:

  28 weight-file inventory entries
  11 represented in PROVENANCE.json
  17 not represented there
  approximately 78 GiB associated with the unresolved group

Missing PROVENANCE.json coverage does NOT by itself prove:

  unlicensed

Use evidence-scoped language such as:

  PROVENANCE STATUS UNKNOWN/UNVERIFIED
  LICENCE STATUS UNKNOWN/UNVERIFIED

unless an independent licence authority proves otherwise.

Never invent provenance.
Never infer absence of licence solely from absence in PROVENANCE.json.

======================================================================
4. RECONCILE CURRENT MODEL-PAYLOAD BASELINE
======================================================================

This is READ-ONLY inventory for the document only.

Sept1.md currently states there are 28 weight files and 17 unresolved entries
totalling approximately 78 GiB.

Before planning control/models around that state, re-run the existing
read-only inventory authority and document:

  current exact object count
  current exact bytes
  current paths/root groups
  format/class
  payload present vs metadata/source fixture
  PROVENANCE.json match yes/no
  current selected status
  currently loaded/resident status
  acquisition/staging/cache/archive distinction

Do NOT hash huge files again unless the existing authority requires it.
Do NOT download.
Do NOT move.
Do NOT delete.
Do NOT activate.

If this count represents historical/stale output rather than current disk
state, correct Sept1.md.

If it represents current learned payloads, say so explicitly.

Do not collapse source fixtures or metadata into "weight files."

======================================================================
5. COMPLETE §13 SHIPPING MATRIX
======================================================================

§13 is currently a useful runtime matrix but is NOT yet the complete shipping
matrix required by this project.

Preserve the existing source/build/runtime rows, then add a distinct DELIVERY
MATRIX covering the established shipping dimensions.

At minimum inventory/plan:

  PACKAGE FORMAT
    DEB
    IPK

  TARGET ARCHITECTURE / MACHINE CLASS
    x86 where actually supported
    x86_64 / amd64
    ARM where actually supported
    arm64 / aarch64
    embedded targets separately where machine-specific

  YOCTO / OPENEMBEDDED
    relevant layer/recipe authority
    package generation authority
    image vs runtime package distinction
    build-only /yocto boundary

  SDK OUTPUTS
    current SDK/eSDK authorities
    intended target SDK matrix
    CURRENT vs PROPOSED clearly separated

  PACKAGE FEEDS
    DEB feed/index
    IPK feed/index
    repository metadata
    publication authority

  SIGNING
    unsigned build artifact
    signed release artifact
    signing authority
    verification authority
    no-secret/private-key handling
    explicit current gaps

  CHECKSUM / PROVENANCE / LICENCE / CUSTODY
    per release artifact

  NATIVE / CUDA
    compiler/toolchain identity
    target compute capability where applicable
    CUDA/runtime ABI
    dynamic library identity
    runtime verification
    model-free CUDA verification path

Do not claim a package/architecture/SDK target CURRENT unless repository or
build evidence proves it.

Use:

  CURRENT
  EXISTING-INCOMPLETE
  PROPOSED
  REQUIRED
  UNKNOWN

for every cell/row where necessary.

Do not turn the user's desired package matrix into a claim that those artifacts
already exist.

======================================================================
6. ENTITLEMENT / AUTH BOUNDARY
======================================================================

Correct A-3 and §19.

Do NOT specify a blanket:

  unentitled -> 403 on /api/dispatchos/*

until endpoint classes are defined.

Classify DispatchOS routes into:

  PUBLIC_BOOTSTRAP
  SHARED_AUTH
  AUTHENTICATED_APPLICATION
  ENTITLEMENT_REQUIRED
  OPERATOR_ONLY

The final target remains:

  accounts/auth = shared authentication authority
  customer->application mapping = shared entitlement authority

Protected DispatchOS application endpoints must fail closed for an authenticated
but unentitled customer.

Authentication/bootstrap endpoints required to establish identity must not be
made unreachable by the entitlement middleware itself.

D-3 remains a product decision until Garrett accepts it.

======================================================================
7. EXPORT — POSITIVE ALLOW-LIST FIRST
======================================================================

Strengthen §12/A-2.

The export implementation must:

  construct the export from an explicit customer/application ALLOW-LIST

and then independently enforce:

  global protected exclusions
  other-customer exclusions
  secret exclusions
  training/private exclusions
  canonical-repository/history exclusions
  runtime/evidence exclusions

Do NOT implement:

  whole repository
    minus
  deny-list

as the export architecture.

For the fail-closed sentinel test:

  use an isolated temporary/test fixture tree

Do NOT plant a sentinel into:

  training/corpus.jsonl
  protected training paths
  canonical project history
  another customer's data
  live runtime state

The negative test must prove:

  protected fixture present -> export exits nonzero
  zero customer archive emitted
  failure recorded

======================================================================
8. OPERATOR COMMAND SAFETY
======================================================================

Correct §18.

A. Do NOT instruct:

  sudo cat /etc/symoneural/api.env

because that can expose secrets/tokens into terminal transcripts or chat.

Replace it with a safe command/helper that displays ONLY the exact non-secret
SYMONEURAL_* enable/disable flags needed for the operation.

Never print token values.

B. Do not use sudo for model acquisition merely because Garrett authorizes the
network operation.

Determine whether the existing acquisition authority is intended to run as the
normal repository owner.

If sudo is not technically required, omit sudo so downloaded artifacts do not
become incorrectly root-owned.

C. A-8 says:

  start -> verify -> stop

so §18 must contain the complete safe operator lifecycle:

  capture pre-state
  start exact units
  verify
  stop exact units
  confirm inactive
  confirm intended enabled/disabled state is unchanged

Do not leave Gateway/Web running merely because the test passed.

======================================================================
9. VERIFICATION MATRIX STRENGTHENING
======================================================================

Correct §19.

A-7:
  screenshot alone is not proof of live data.

Require:
  real ASIC/API response
  UI consumes that response
  expected KPI value appears
  no console error
  screenshot only as supplemental visual evidence

A-6 generated pages:
  do not use one generic generator check for every generator.

For each affected generator:
  run generator
  run it a second time
  assert no second-run diff
  run its relevant test
  verify rendered page

Do not attribute all generator stability to test_build_progress.py unless that
test actually covers each affected generator.

A-3:
  test exact route classes from §6 of this correction rather than blanket
  /api/dispatchos/* behavior.

A-8:
  verify current binary/service identity, HTTP behavior, then restore pre-test
  service state.

======================================================================
10. ROLLBACK CONSISTENCY
======================================================================

Remove broad/manual rollback language that conflicts with §20.

A-1 currently suggests:

  rm -rf control/models

Do not use that as the canonical rollback after commits exist.

Canonical committed rollback:

  git revert <exact phase commit(s)>

For an uncommitted failed implementation attempt:

  use exact known files from that assignment
  do not use broad recursive deletion unless separately reviewed

Align every A-1...A-8 rollback statement with §20.

======================================================================
11. BASELINE WORDING
======================================================================

Correct §3 working-tree terminology.

Distinguish:

  BASELINE BEFORE Sept1.md
    tracked modifications = 0
    untracked Sept1.md = not yet present

from:

  CURRENT PLANNING-PASS END STATE
    tracked modifications = 0
    untracked = Sept1.md only

Do not call the latter simply "working tree clean."

======================================================================
12. ABSOLUTE-HISTORY LANGUAGE
======================================================================

Where Sept1.md says Gateway/Web were "never verified running", scope the claim.

Current disabled/inactive state does not prove an all-history negative.

Use a bounded statement such as:

  no successful run for the CURRENT binaries/current HEAD was established in
  this planning inventory

unless repository evidence proves a stronger historical statement.

======================================================================
13. PRESERVE WHAT IS ALREADY CORRECT
======================================================================

Do NOT rewrite the document from scratch.

Preserve:

  21-section structure
  normative customer-slot architecture
  no symoneural-dispatchos rule
  conceptual architecture != filesystem layout
  control/ additive model
  existing Studio reconciliation
  generated-vs-authored page distinction
  shared accounts direction
  fail-closed customer export policy
  proposed intake assignments
  decision register
  phase gates
  real-run verification rule
  no implementation authorization

======================================================================
14. AFTER CORRECTION — READ-ONLY SELF-CHECK
======================================================================

After editing Sept1.md only, verify:

  all 21 sections still present
  tracked repo modifications = 0
  Sept1.md remains the only intended untracked/project change
  no implementation files changed
  no service state changed
  no model state changed
  no downloads
  no commits

Return:

SEPT1 CORRECTION
  path=
  lines=
  sha256=
  sections=

LIVE STACK
  customer_applications=
  shared_applications=
  embedded_surfaces=
  platform_operator_surfaces=
  informational_pages=
  taxonomy_consistent=

DONNIE SLOT
  architecture_vs_runtime_separated=
  auth_state=
  entitlement_state=
  shared_service_map_state=

MODEL BASELINE
  objects=
  bytes=
  learned_payloads=
  metadata_source_fixtures=
  provenance_verified=
  provenance_unknown=
  licence_unknown=

SHIPPING
  runtime_matrix=
  delivery_matrix=
  deb=
  ipk=
  target_architectures=
  yocto_oe=
  sdk_matrix=
  feed_state=
  signing_state=
  cuda_native=

SAFETY
  secret_print_commands=
  sudo_model_acquisition=
  export_positive_allowlist=
  rollback_consistent=
  service_test_restores_prestate=

SCOPE
  implementation_changes=
  unauthorized_changes=
  tracked_modifications=
  untracked=

VERDICT

Exactly one:

  SEPT1_CORRECTED_READY_FOR_USER_DECISIONS

or

  STOP — USER ACTION REQUIRED

Then STOP.

NO IMPLEMENTATION.
NO INTAKE EDITS.
NO COMMITS.
