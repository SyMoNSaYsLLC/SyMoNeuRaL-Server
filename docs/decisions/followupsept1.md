BUILD SEPT1.md — COMPLETE SERVER / APPLICATION / CUSTOMER DELIVERY PLAN

This is a PLANNING AND INVENTORY PASS.

Do not begin implementing the features below.

Do not restructure the repository.
Do not create another symoneural-server/ consolidation.
Do not move backend/, ops/, scripts/, engines/, frontend/, site/, web/, control/,
or other working canonical paths merely to make the tree visually cleaner.

The previous consolidation attempt established that this is unnecessary and
high-risk.

The correct organizational model is:

    existing canonical implementation paths
            +
    additive control/ operator surface
            +
    documented architecture / ownership boundaries

The control/ directory is now the central operator/control-board surface.
Extend it where appropriate; do not use it as justification to duplicate
implementations.

Your only new project deliverable in this pass is:

    /home/google/Symoneural/Sept1.md

Sept1.md must become the complete reviewed implementation plan that I can edit,
return to you, and then use as the authority for the next build phase.

Do not modify INTAKE.md, PROJECT-TASKS.md, implementation source, services,
runtime state, packages, models, or deployment configuration during this pass.

======================================================================
A. CONTROL/MODELS
======================================================================

Plan the extension:

    control/models/

This must follow the same philosophy as the existing control/ board:

    additive
    thin wrappers
    existing implementation remains authoritative
    no second source of truth
    no copied runtime implementation
    runnable from the central control surface
    documented
    testable

First inventory the existing model-management authorities before proposing any
new launcher.

Include at minimum existing tooling related to:

    model inventory
    model acquisition
    model staging
    model verification
    model activation/swap
    model release/unload
    conversion
    quantization
    fine-tuning
    adapters / LoRA
    weight handling
    model identity
    rebranding
    provenance
    licensing
    checksums
    runtime compatibility

Explicitly inspect existing locations including:

    control/
    tools/modelops_inventory.py
    scripts/modelops/
    training/
    backend model-management code
    engine/runtime tooling
    custody/provenance tooling

Do not report an authority missing until the complete relevant subtree has been
searched.

For each proposed control/models launcher document:

    launcher name
    purpose
    existing underlying authority
    exact existing implementation it wraps
    read/write behavior
    model required yes/no
    GPU required yes/no
    network required yes/no
    privileged operation yes/no
    verification command
    STOP conditions

I want operator-facing README/launcher coverage for things such as:

    what models are currently present
    what model is selected
    what is actually loaded
    runtime compatibility
    acquire a model
    verify a model
    stage a model
    activate/swap a model
    unload/release a model
    add authorized weights
    create/use adapters
    fine-tune
    conversion
    quantization
    rebrand project-owned model artifacts
    inspect provenance
    inspect license
    inspect checksums
    inspect GPU/runtime state

Do NOT download models during this planning pass.

The system must remain valid when model payloads are absent.

"No model installed" must be a normal explicit state, not something hidden by
a CPU fallback or fake success.

======================================================================
B. COMPLETE LIVE STACK INVENTORY + INTAKE PLAN
======================================================================

Do not assume there are only eight applications.

Discover the actual Live Stack from current source and wiring.

Cross-check at minimum:

    control/status-all.sh
    frontend routes
    site pages
    backend/apps/
    mounted API routes
    application manifests/registries
    Live Stack UI
    tests/smoke records
    documentation

Create a master application table in Sept1.md.

For EVERY discovered application/surface include:

    application identity
    slug
    customer-specific or shared
    frontend path
    backend path
    API namespace
    public route
    current implementation status
    auth status
    entitlement status
    runtime dependency
    model dependency
    shared service dependencies
    test coverage
    UI/reference status
    export/delivery status
    known defects
    missing work
    proposed INTAKE assignment
    acceptance checks

Write all required future INTAKE assignments into Sept1.md as proposed
assignments.

Do not modify INTAKE.md yet.

Each assignment needs:

    reason
    existing implementation
    missing implementation
    files/systems likely affected
    dependencies
    risk
    explicit exclusions
    check: lines
    end-to-end runtime test where applicable
    rollback expectation

======================================================================
C. STUDIO + MODEL OPERATIONS USER EXPERIENCE
======================================================================

SyMoNeuRaL Studio is intended for advanced users familiar with tools such as
ComfyUI and model/runtime playground interfaces.

Do NOT rebuild Studio blindly.

First reconcile what already exists under the Studio implementation, including
its graph/node/custom-node/MCP/ComfyUI integration.

Sept1.md must define the gap between CURRENT Studio and TARGET Studio.

Target concepts include:

    graphical/node workflow
    model selection
    runtime selection
    model inspection
    model lifecycle visibility
    adapter management
    fine-tuning controls
    conversion/quantization controls where appropriate
    job/status visibility
    logs
    GPU state
    artifact provenance
    checksums
    explicit activation/release
    fail-closed operations

The GUI and control/models/ launchers must operate against the SAME underlying
authorities.

Do not create one implementation for CLI/control and another unrelated
implementation for Studio.

======================================================================
D. APPLICATION LOOK / FEEL
======================================================================

Audit every Live Stack application's existing UI before designing replacements.

Use the references I supplied, including:

    DeepSeek Harness quickstart/workflow references
    the supplied screenshots
    /home/google/Downloads/minerlooknfee

as workflow/density/layout references.

Preserve SyMoNeuRaL identity.

The goal is not to clone another product.

The goal is:

    each SyMoNeuRaL application should visually communicate what class of
    application it is while remaining part of one coherent SyMoNeuRaL product.

For every Live Stack application, Sept1.md must document:

    current UI
    reference UI
    elements worth preserving
    elements needing redesign
    shared SyMoNeuRaL shell elements
    application-specific workspace elements
    responsive requirements
    accessibility requirements
    required screenshots/tests

======================================================================
E. CUSTOMER LOGIN / APPLICATION ACCESS / DONNIE
======================================================================

Do not build a second authentication system.

Audit the existing accounts implementation first.

Map the required customer flow:

    customer enters SyMoNeuRaL
        ->
    account creation/login
        ->
    customer identity established
        ->
    entitlement resolved
        ->
    authorized applications displayed
        ->
    customer selects application
        ->
    customer application opens

Reference example:

    Donnie
        ->
    DispatchOS entitlement
        ->
    DispatchOS
        ->
    /demo/dispatchos or approved production route

Sept1.md must determine what existing account/auth functionality already
satisfies this and what is actually missing.

======================================================================
F. CUSTOMER DOWNLOAD / DELIVERY
======================================================================

The customer needs a GitHub-like download function inside the authorized
application.

This is NOT authorization for a whole-repository ZIP.

The written export policy remains authoritative.

Customer export must be:

    customer scoped
    application scoped
    manifest driven
    fail closed
    versioned
    checksummed
    custody recorded

Before proposing implementation, determine the current state of the sanctioned
export tooling, including whether tools/export_snapshot.sh now exists or is
still only specified.

The plan must define:

    customer/application identity
    exact allowed artifact set
    protected exclusions
    unrelated customer exclusions
    repository/source exclusions
    training/private-data exclusions
    secret exclusions
    internal evidence exclusions
    manifest
    checksum
    version/release identity
    provenance/license handling
    download UX
    test proving protected content cannot escape

======================================================================
G. CORE IDENTITY / ARCHITECTURE ALIGNMENT
======================================================================

Use the customer-slotting architecture below as normative architecture.

Core identity remains:

    SymonSaysLLC
        = company / legal / ownership identity

    SyMoNeuRaL
        = shared system / platform / network / ecosystem

    symoneural-*
        = system/platform/infrastructure authority

    Symon
        = model / agent / runtime / software identity

    symon-*
        = executable/runtime/component/artifact identity

    symon_*
        = importable Python module when required

    customer applications
        = application-layer identities

    third-party names
        = retained upstream

Do not invent:

    symoneural-dispatchos

merely because DispatchOS runs on SyMoNeuRaL.

The architecture is:

    shared SyMoNeuRaL platform
        +
    shared Symon runtime/software
        +
    customer/application slots

Donnie/DispatchOS is the reference customer slot.

Every future customer must fit the same logical application-slot contract.

======================================================================
H. NEW-CUSTOMER SLOT STANDARD
======================================================================

Sept1.md must incorporate the full customer slot indicators from the architecture
below.

For every customer/application, explicitly define:

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

Donnie/DispatchOS must be filled out as the reference implementation.

Also provide one blank reusable customer-slot template.

Do not copy Donnie-specific business logic into future customers.

======================================================================
I. CURRENT SERVER AUTHORITIES THAT MUST NOT BE MISREAD
======================================================================

Carry the following findings from this session into the plan:

1. Do not revive the symoneural-server/ consolidation.
   It was reverted.

2. control/ is the accepted additive control-board model.

3. scripts/deploy.sh remains load-bearing manual deployment tooling.
   Do not classify it as obsolete merely because the old deploy service is gone.

4. symoneural-deploy.service was intentionally removed.
   Do not silently recreate it.

5. scripts/gcommit.sh is supported interactive operator tooling.
   Zero source-code references do not make it orphaned.

6. scripts/modelops/symoneural-modelops-stage.sh exists.
   Search nested tool directories before declaring modelops functionality absent.

7. Existing implementations must be extended/reconciled instead of duplicated.

======================================================================
J. SERVER / RUNTIME / LIBRARY / BINARY SHIPPING SCOPE
======================================================================

Sept1.md must describe the COMPLETE eventual server-update scope necessary to
reach a shippable state.

Do NOT perform that work yet.

For every runtime/service/application define the chain:

    source authority
        ->
    build authority
        ->
    generated binary/library
        ->
    runtime location
        ->
    configuration
        ->
    service/launcher
        ->
    application consumer
        ->
    smoke/runtime test
        ->
    package/release artifact
        ->
    checksum
        ->
    provenance/license record
        ->
    release/custody verification

Inventory:

    executables
    native libraries
    runtime libraries
    API
    gateway
    web runtime
    CUDA/native engine
    application runtimes
    scripts
    launchers
    service units/templates
    build tools
    packaging
    release tooling

Distinguish clearly:

    source
    generated build artifact
    installed runtime
    package artifact
    customer-delivery artifact

Do not commit generated binaries into Git merely because they are required for
shipping.

======================================================================
K. ISSUES / DECISIONS / OPERATOR ACTIONS
======================================================================

Sept1.md must contain a dedicated decision register.

For every unresolved issue provide:

    ISSUE
    EVIDENCE
    CURRENT STATE
    OPTIONS
    TRADEOFF
    YOUR RECOMMENDATION
    DECISION REQUIRED FROM GARRETT
    BLOCKS WHAT
    SAFE DEFAULT

Do not make product/architecture decisions silently.

Also provide a separate OPERATOR COMMANDS section.

Only include commands that I genuinely need to run myself because of privilege,
physical-console, account, secret, or other operator-only requirements.

Do not pad this section with commands you can execute yourself later.

======================================================================
L. BUILD SEQUENCING
======================================================================

Give me the recommended implementation order.

The sequence should minimize duplicated work and avoid changing live serving
paths before their dependencies and verification paths exist.

At minimum consider the dependency relationship among:

    intake/task gates
    control/models
    modelops authorities
    customer/auth/entitlement
    customer export
    Studio
    Live Stack UI pass
    customer slotting
    server packaging/release
    final runtime verification

For each phase define:

    authorization required
    files/systems touched
    prerequisites
    expected result
    exact verification
    STOP condition
    commit boundary

======================================================================
M. SEPT1.md REQUIRED STRUCTURE
======================================================================

Write Sept1.md so I can edit it and return it as the complete implementation
authority.

Required major sections:

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

======================================================================
N. DEFINITION OF DONE FOR THIS PASS
======================================================================

This pass is complete when:

    Sept1.md exists

AND it inventories actual existing implementation rather than assumptions

AND every Live Stack application is represented

AND every proposed feature has an intake assignment

AND the Donnie/customer architecture is integrated

AND future customers have a reusable slot template

AND existing authorities are distinguished from missing work

AND all unresolved issues are explicit

AND implementation dependencies are sequenced

AND verification requirements are defined

AND commit boundaries are proposed

AND no feature implementation has begun.

Then STOP.

I will review/update Sept1.md and send it back.

Only after I return the reviewed document will implementation authorization
begin.

Below this instruction is the authoritative:

    SyMoNeuRaL Customer Application Slotting Architecture

Preserve its architectural meaning in Sept1.md.


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
  tools/modelops_inventory.py
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

  tools/export_snapshot.sh

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

eveDo not start implementation.

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
