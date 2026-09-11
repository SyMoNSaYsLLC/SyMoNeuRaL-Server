Before pausing completely, record these answers to Q1–Q4 in the session context.

DO NOT resume the Sept1.md correction pass yet.
DO NOT edit Sept1.md from these answers yet.
DO NOT run additional inventory.
DO NOT implement anything.

I am answering the questions now so that when I later use /resume and say
"continue", you already have the decisions and can continue the remaining
correction pass without asking me these questions again.

======================================================================
Q1 — EMPTY MODEL STATE / A-1 SEQUENCING
======================================================================

ANSWER: Choose (a).

Keep A-1 control/models in its current early sequence even though the machine
currently contains zero learned model payloads.

The zero-model state is intentional and should be treated as a first-class,
valid operating state.

In fact, this is the correct baseline for validating control/models.

A-1 must work correctly when:

    learned model payloads = 0
    adapters = 0
    active defaults = 0
    resident models = 0

Expected behavior should include:

    models-list
        accurately reports no installed payloads

    models-active
        reports none selected

    models-loaded
        reports none resident

    models-provenance
        distinguishes historical metadata records from present payloads

    models-checksums
        reports that no current payload objects require verification

    models-compat
        can still inspect runtime/engine compatibility without a model

    models-gpu
        can inspect GPU/CUDA/runtime state independently of model presence

Do NOT acquire a model merely to make A-1 testing non-empty.

A "no model installed" result is a successful test condition when it accurately
represents the machine.

Model acquisition remains a separate explicitly authorized action.

======================================================================
Q2 — 11 PROVENANCE.json ENTRIES
======================================================================

ANSWER:

Do NOT treat the 11 PROVENANCE.json entries as the intended current model set.

Do NOT treat them as an approved reacquisition list.

The authoritative current machine state is:

    learned model payloads = 0
    adapters = 0
    active defaults = 0
    resident models = 0

The 11 records should currently be treated as retained historical/provenance
metadata describing prior model artifacts unless later evidence establishes
another purpose.

Preserve them.

Distinguish these states explicitly:

    PROVENANCE RECORD EXISTS
    PAYLOAD ABSENT
    ACTIVE = NO
    RESIDENT = NO
    REACQUISITION AUTHORIZED = NO

A provenance record is NOT authorization to download its referenced payload.

Future acquisition of any model requires explicit authorization from me.

Do not download, reacquire, restore, stage, activate, or infer approval for any
model because it appears in PROVENANCE.json.

When correction work resumes, rewrite D-1 around the actual current issue:

    historical provenance metadata exists
    current corresponding payloads are absent
    metadata/current-runtime reconciliation must be explicit

The earlier:

    28 weights
    17 unresolved
    ~78 GiB

state was stale and must not survive as a current-machine claim.

======================================================================
Q3 — IPK / YOCTO / SDK SCOPE
======================================================================

ANSWER:

Yes, /yocto is part of the shipping/build evidence you should inspect.

When the correction pass resumes, perform a READ-ONLY inventory of /yocto.

DO NOT modify /yocto.

The intended SyMoNeuRaL delivery architecture is broader than the repo-local
DEB tooling.

The intended package targets include:

    DEB
    IPK

for applicable target classes including:

    x86
    x86_64 / amd64
    ARM
    arm64 / aarch64

and multiple SDK/eSDK outputs as appropriate to the supported machines.

However, intended targets and CURRENT capability are different things.

In Sept1.md, determine current evidence from /yocto for:

    meta-symoneural*
    relevant recipes
    PACKAGE_CLASSES
    DISTRO/MACHINE configuration
    tune/architecture configuration
    DEB package generation
    IPK package generation
    package feeds/indexes
    SDK configuration
    eSDK configuration
    SDK/eSDK artifacts
    release metadata
    checksum authorities
    signing configuration
    signed/unsigned artifact state

Classify each as:

    CURRENT
    EXISTING-INCOMPLETE
    PROPOSED
    MISSING
    UNKNOWN

Do NOT mark IPK, SDK, eSDK, architecture support, feeds, or signing CURRENT
merely because I want them.

Actual build/output evidence determines CURRENT.

This correction pass remains read-only with respect to /yocto.

No BitBake builds.
No configuration edits.
No package generation.
No feed generation.
No SDK generation.

======================================================================
Q4 — ARCHITECTURE-SPECIFIC PACKAGING
======================================================================

ANSWER:

Architecture-independent packaging is NOT the intended final packaging model
for the complete SyMoNeuRaL product.

Package according to the actual contents.

Components that are genuinely architecture-neutral may use architecture-neutral
packaging, for example where technically correct:

    Python
    shell
    static web assets
    metadata/configuration

But components containing native output must be tied to the architecture they
were actually built for, including:

    Rust binaries
    Go binaries
    native C/C++ binaries
    CUDA binaries/libraries
    engine binaries
    architecture-specific shared libraries
    other compiled runtime components

The intended release matrix includes:

    x86
    x86_64 / amd64
    ARM
    arm64 / aarch64

where technically supported.

But Sept1.md must distinguish these maturity levels:

    source is portable
    build target is configured
    build completed successfully
    package generated successfully
    package installed successfully
    runtime tested successfully
    release artifact produced
    checksum recorded
    provenance/licence recorded
    artifact signed
    signature verified
    release/custody verified

These are NOT equivalent.

Mark only evidence-backed states CURRENT.

Mark desired but unproven targets PROPOSED or EXISTING-INCOMPLETE as
appropriate.

Also keep separate:

    DEB packaging
    IPK packaging
    SDK/eSDK outputs
    image builds
    runtime payload packages

A Yocto image or packagegroup is not evidence that a runtime payload package
exists for every intended architecture.

======================================================================
RESUME STATE
======================================================================

Record these answers as authoritative decisions for the remaining Sept1.md
controlled correction pass:

    Q1 = A-1 remains early; zero-model state is a valid test baseline
    Q2 = 11 provenance records are metadata only until proven otherwise;
         no reacquisition authorization
    Q3 = inspect /yocto read-only and evidence-classify DEB/IPK/SDK/eSDK/feed/
         signing capability
    Q4 = final product is architecture-aware; architecture-neutral packaging
         only where the actual payload is architecture-neutral

Do not continue the remaining correction work now.

Remain paused with:

    Sept1.md as currently saved
    no implementation
    no additional edits
    no commits
    no service changes
    no model changes
    no /yocto changes

When I later use /resume and say:

    continue

resume the remaining Sept1.md controlled correction pass from the saved
checkpoint, using these Q1–Q4 answers without asking them again.

Acknowledge that these four answers are recorded, give me the resume checkpoint,
then PAUSE.
