# business/ — what this company is and sells

Not operations, not code. These were mixed into a 97-file `ops/docs/` where an operator
looking for a port number had to read past a revenue model.

```
IDENTITY.md                        SymonSays LLC, SyMoNeuRaL, and which name goes where
SYMONEURAL-EMAIL-IDENTITY-POLICY.md
REPOSITORY-PURPOSE.md              what this repository is for
scope-of-work-2026-08-22.md
symoneural-appliance.md            the box as a product
symoneural-commercial-mode.md      what changes when it is sold rather than run
symoneural-marketplace.md
symoneural-platform-targets.md     which platforms are in scope
symoneural-cloud-local-targets.md  what runs local, what could run hosted
symoneural-revenue-edge.md
symoneural-trust-report.md         what a customer is told, and what backs it
symoneural-website-look-feel.md
share-previews/                    customer landing pages, and what building them taught
```

## The rule these all serve

A claim made here has to be true of the box. The site's whole argument is that its published
numbers are the real ones, so a figure in this directory is subject to the same rule as one
in `ops/registry/`: it carries the commit it was measured on, or it does not get published.

`IDENTITY.md` settles a question that recurs: **a `symoneural-*` name is a runtime or build
identity, not a claim of authorship.** Several directories carrying that prefix contain
upstream software under its own licence. See `LICENSES.md` and `ops/audits/LICENSE-AUDIT.md`.
