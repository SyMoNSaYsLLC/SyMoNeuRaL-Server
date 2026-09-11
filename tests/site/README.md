# tests/site/ — the pages, and what they claim

9 files. These check the published site against the service behind it.

```
test_api_reference.py         /docs renders from the live schema, not a snapshot
test_page_families.py         every page family exists and links resolve
test_site_css.py              one stylesheet, no orphan rules
test_dashboard_page.py        the dashboard's markup matches what the API returns
test_maintenance_banner.py    ui.js and MAINTENANCE-SURFACES.md agree on which surfaces
test_operator_console.py      the console generator's output
test_brand_boundary.py        no vendor name where ours belongs
test_reference_isolation.py   the reference page carries no third-party bundle
test_ui_verification_runner.py the smoke record exists and is current
```

## What these cannot do

**None of them proves a page renders.** They read markup and compare it to the schema; a
browser is what proves a page works, and #94 shipped a desktop client whose eighteen checks
were all green and whose chat surface was dead on arrival.

Where rendering matters, the evidence is a smoke record in `ops/smoke/` — that file cannot
be written honestly without opening the page.

## The failure these exist for

A live figure typed into markup. The chat page said `SymonChat S1-7B` through three model
changes because nothing read it. Anything that can change is fetched from `/api/status` or
`/openapi.json`, and a test here should fail when it is typed instead.
