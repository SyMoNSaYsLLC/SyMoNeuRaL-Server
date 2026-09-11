"""Lifted from server.py, 2026-09-11.

Runtime objects come off `core.context.ctx`; importing server would be a cycle.
"""
from __future__ import annotations

import streamer  # noqa: E402  -- the IPTV surface AND the Guide that filters
from streamer import guide  # noqa: E402  -- the library half: matching, clustering,
import studio  # noqa: E402  -- the local agent and the



def _application_docs_index() -> str:
    """The index of scoped application documentation, grouped by functional runtime.

    This sits at the TOP of `/docs` rather than at the bottom, and grouped by runtime rather
    than listed flat, because the two questions a visitor arrives with are "which application
    am I looking for" and "what actually runs it" -- and a flat alphabetical list of
    twenty-two slugs answers neither. The grouping is read from the registry, so a new
    application appears here the moment it is given an owner and never has to be added twice.

    Global versus scoped is stated rather than implied: this page is the platform-wide
    reference and every link below narrows it to one application's own routes.
    """
    by_runtime: dict[str, list] = {}
    for a in appdocs.APPLICATIONS:
        by_runtime.setdefault(a.runtime, []).append(a)

    blocks = []
    for runtime in appdocs.RUNTIMES:
        apps_here = [a for a in by_runtime.get(runtime, []) if a.parent is None]
        children = {a.parent: [] for a in by_runtime.get(runtime, []) if a.parent}
        for a in by_runtime.get(runtime, []):
            if a.parent:
                children.setdefault(a.parent, []).append(a)
        if not apps_here and not children:
            continue
        rows = []
        for a in apps_here:
            kids = children.get(a.id, [])
            kid_links = "".join(
                f'<a class="ar-appkid" href="/docs/{k.id}">{appdocs.e(k.label)}</a>'
                for k in kids)
            rows.append(
                f'<div class="ar-app"><a class="ar-applink" href="/docs/{a.id}">'
                f'<b>{appdocs.e(a.label)}</b></a>'
                + (f'<div class="ar-appkids">{kid_links}</div>' if kid_links else "")
                + "</div>")
        # A child whose parent runs on a DIFFERENT runtime still needs a home here, or it
        # would be silently absent from the index while having a perfectly good page.
        for parent_id, kids in children.items():
            if any(a.id == parent_id for a in apps_here):
                continue
            for k in kids:
                rows.append(f'<div class="ar-app"><a class="ar-applink" href="/docs/{k.id}">'
                            f'<b>{appdocs.e(k.label)}</b></a></div>')
        blocks.append(
            f'<div class="ar-rt"><h3>{appdocs.e(runtime)}</h3>'
            f'<p>{appdocs.e(appdocs.RUNTIMES[runtime])}</p>'
            f'<div class="ar-apps">{"".join(rows)}</div></div>')

    return (
        '<div class="ar-index">'
        '<h2>Documentation by application</h2>'
        '<p class="ar-note">This page is the <strong>platform-wide</strong> reference: every '
        'route this service mounts, from the schema it generates. Each link below is a '
        '<strong>scoped</strong> page carrying only that application&rsquo;s own routes, its '
        'runtime owner, its authentication boundary and its operational limits. Applications '
        'are grouped by the runtime that executes their work; indented entries are child '
        'surfaces of the application above them, not runtimes of their own.</p>'
        f'<div class="ar-runtimes">{"".join(blocks)}</div>'
        '</div>'
    )
