FOLLOW-UP — SEPT1.md SELF-AUDIT / SCOPE-COMPLIANCE REVIEW

Do NOT begin implementation.

Your previous authorization was:

  planning + inventory only

with the sole intended project deliverable:

  /home/google/Symoneural/Sept1.md

Before I review Sept1.md, perform a complete READ-ONLY compliance review of
the work you just performed.

======================================================================
1. VERIFY YOU STAYED INSIDE AUTHORIZATION
======================================================================

Inspect the repository and system state.

Report every filesystem or repository change made during the Sept1.md pass.

The intended result is:

  Sept1.md created/updated

and NO implementation changes.

Specifically prove that you did NOT modify:

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
  systemd units
  runtime configuration
  model payloads
  packages
  services

Do not rely on memory.

Use git status, git diff, file timestamps where useful, and the actual current
repository state.

If you made an unauthorized change:

  DO NOT silently revert it.
  DO NOT continue implementation.

Report:

  exact path
  exact change
  why it occurred
  whether it is tracked/untracked
  whether it existed before this pass
  recommended recovery

Then:

  STOP — USER ACTION REQUIRED

======================================================================
2. VERIFY Sept1.md IS PLANNING, NOT IMPLEMENTATION
======================================================================

Read the completed:

  /home/google/Symoneural/Sept1.md

Confirm it does not contain claims that unimplemented work is already complete.

Distinguish clearly:

  CURRENT
  EXISTING BUT INCOMPLETE
  PROPOSED
  REQUIRED
  DECISION NEEDED
  FUTURE IMPLEMENTATION

Do not turn proposed architecture into claims about current wiring.

======================================================================
3. VERIFY EXISTING AUTHORITIES WERE INVENTORIED BEFORE NEW WORK WAS PROPOSED
======================================================================

Cross-check Sept1.md against the actual repository.

At minimum verify coverage of:

  control/
  control/models planning
  tools/lib/modelops_inventory.py
  scripts/modelops/
  training/
  backend model-management code
  Studio
  accounts/auth
  customer/export tooling
  Live Stack application discovery
  runtime/build tooling
  custody/provenance/licensing/checksum tooling

Confirm that an existing authority was not incorrectly described as missing
because only a shallow directory search was performed.

Explicitly remember these established examples:

  scripts/gcommit.sh
      interactive operator tooling; zero source references does not make it dead

  scripts/modelops/symoneural-modelops-stage.sh
      exists in a nested directory; do not report it missing

  scripts/deploy.sh
      retained manual deployment authority; do not classify it obsolete merely
      because symoneural-deploy.service was removed

======================================================================
4. VERIFY LIVE STACK INVENTORY COMPLETENESS
======================================================================

Do not assume the Live Stack contains eight applications.

Compare the application list in Sept1.md against actual current authorities,
including where applicable:

  backend/apps/
  frontend routes
  site/
  control/status-all.sh
  API/status surface registry
  application manifests/registries
  smoke/application records
  documentation

Produce:

  DISCOVERED_APPLICATION_COUNT=
  SEPT1_APPLICATION_COUNT=
  MATCH=YES/NO

List any omitted or duplicate applications.

Do not modify Sept1.md yet if there is a discrepancy.

======================================================================
5. VERIFY CUSTOMER SLOT ARCHITECTURE
======================================================================

Confirm Sept1.md preserves the approved architecture:

  SymonSaysLLC
      company/legal/ownership

  SyMoNeuRaL
      shared platform/system/network/ecosystem

  symoneural-*
      platform/system/infrastructure

  Symon / symon-*
      model/runtime/software/component identities

  customer application
      application-layer slot using shared SyMoNeuRaL/Symon capabilities

Reference:

  Donnie
      ->
  DispatchOS
      ->
  customer/application slot

Do NOT promote DispatchOS into:

  symoneural-dispatchos

unless a separate future architecture decision explicitly authorizes that.

Verify that Sept1.md includes the reusable indicators for future customers:

  CUSTOMER_IDENTITY
  APPLICATION_IDENTITY
  APPLICATION_SLUG
  FRONTEND_SLOT
  BACKEND_SLOT
  API_SLOT
  CUSTOMER_ROUTE
  AUTH_SLOT
  ENTITLEMENT_SLOT
  WORKFLOW_SLOT
  CONFIG_SLOT
  ASSET_SLOT
  SHARED_SERVICE_MAP
  EXPORT_SCOPE
  PROTECTED_EXCLUSIONS
  RELEASE_IDENTITY
  CUSTODY_RECORD
  TEST_PATH
  LIVE_STACK_ENTRY

Required:

  Donnie/DispatchOS populated reference slot
  blank reusable future-customer slot template

======================================================================
6. VERIFY CUSTOMER EXPORT POLICY
======================================================================

Confirm Sept1.md does NOT propose whole-repository customer ZIP export.

The plan must preserve the existing export security boundary:

  customer scoped
  application scoped
  manifest driven
  fail closed

and must account for protected content such as:

  unrelated customer data
  private source
  training/private data
  secrets
  internal audit/evidence
  non-deliverable runtime/internal assets

Confirm the actual state of:

  tools/data/export_snapshot.sh

Do not state that it exists if it is only specified.
Do not state that it is missing if it now exists.

Use the filesystem as authority.

======================================================================
7. VERIFY STUDIO PLAN BUILDS ON CURRENT STUDIO
======================================================================

Confirm Sept1.md recognizes the existing Studio implementation rather than
proposing a blind replacement.

Check actual current Studio authorities and ensure the plan distinguishes:

  existing implementation
  missing capabilities
  proposed extensions

The target may use ComfyUI / model-playground interaction patterns as
references, but must remain SyMoNeuRaL and share the same underlying authorities
as control/models.

No duplicate model-management backend should be proposed for Studio.

======================================================================
8. VERIFY SHIPPING MATRIX
======================================================================

Confirm Sept1.md distinguishes:

  source
  build authority
  generated binary/library
  installed runtime
  service/launcher
  package artifact
  customer-delivery artifact
  release artifact

For each major runtime/service/application, the eventual chain should be
planned as:

  source
    ->
  build
    ->
  binary/library
    ->
  runtime location
    ->
  configuration
    ->
  launcher/service
    ->
  consumer
    ->
  runtime/smoke verification
    ->
  package/release
    ->
  checksum
    ->
  provenance/license
    ->
  custody verification

Do not imply generated binaries belong in Git simply because they are required
for shipping.

======================================================================
9. VERIFY DECISION REGISTER
======================================================================

Every unresolved architecture/product/implementation issue must be explicit.

For each unresolved item Sept1.md should provide:

  ISSUE
  EVIDENCE
  CURRENT STATE
  OPTIONS
  TRADEOFF
  RECOMMENDATION
  DECISION REQUIRED FROM GARRETT
  BLOCKS WHAT
  SAFE DEFAULT

Do not silently choose unresolved product decisions.

======================================================================
10. VERIFY IMPLEMENTATION SEQUENCING
======================================================================

Confirm the plan sequences dependencies rather than treating all work as one
large build.

At minimum evaluate ordering among:

  task/intake gates
  control/models
  shared modelops authorities
  customer auth/entitlement
  customer export
  Studio
  application UI pass
  customer slotting
  runtime/package/release work
  final server verification

Every implementation phase should have:

  authorization
  prerequisite
  scope
  expected result
  verification
  STOP condition
  commit boundary

======================================================================
11. VERIFY Sept1.md STRUCTURE
======================================================================

Confirm these sections exist and contain substantive content:

  1. Executive Scope
  2. Frozen Architecture / Naming Rules
  3. Current Server Baseline
  4. Existing Authority Inventory
  5. Complete Live Stack Inventory
  6. control/models Plan
  7. Studio Plan
  8. Per-Application UI Plan
  9. Customer Account/Auth/Entitlement Plan
  10. Customer Application Slotting Standard
  11. Donnie/DispatchOS Reference Slot
  12. Customer Export/Download Plan
  13. Runtime / Library / Binary Shipping Matrix
  14. Proposed INTAKE Assignments
  15. Dependencies / Sequencing
  16. Risks / Known Issues
  17. Decision Register
  18. Operator Commands Required
  19. Verification Matrix
  20. Commit / Release Plan
  21. Definition of Done

Report any weak, empty, duplicated, or assumption-based section.

======================================================================
12. DO NOT FIX YET
======================================================================

This follow-up is REVIEW ONLY.

Do not modify Sept1.md during this review.

Do not fix omissions silently.

Do not start implementation.

I want the review findings first so I can decide whether Sept1.md needs one
controlled correction pass.

======================================================================
RETURN ONLY
======================================================================

SCOPE COMPLIANCE
  unauthorized_changes=
  Sept1_only_expected_change=
  repository_status=

AUTHORITY INVENTORY
  missing_existing_authorities=
  falsely_missing_authorities=
  duplicate_authorities_proposed=

LIVE STACK
  discovered_applications=
  Sept1_applications=
  match=

CUSTOMER ARCHITECTURE
  donnie_reference_slot=
  reusable_customer_template=
  naming_alignment=

EXPORT
  policy_alignment=
  export_snapshot_actual_state=

STUDIO
  existing_authority_reconciled=
  duplicate_backend_proposed=

SHIPPING
  source_runtime_package_distinction=
  matrix_complete=

DECISIONS
  unresolved_decisions_explicit=
  silent_decisions=

SEQUENCING
  dependency_order_defined=
  commit_boundaries_defined=

SEPT1 STRUCTURE
  sections_present=
  weak_or_missing_sections=

VERDICT

Exactly one:

  SEPT1_READY_FOR_USER_REVIEW

or

  SEPT1_NEEDS_CONTROLLED_CORRECTION

or

  STOP — USER ACTION REQUIRED

Then STOP.

NO IMPLEMENTATION.
NO CORRECTION PASS YET.
