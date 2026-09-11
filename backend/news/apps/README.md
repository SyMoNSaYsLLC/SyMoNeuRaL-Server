# `backend/news/apps/` — Programs for `news`

Runnable, or driven by a route. **Not imported by the router** -- these may spawn a
subprocess, hold a file, or run for minutes, none of which belongs on a request path.

A program invoked by a route is invoked as a subprocess or a task, never imported and
called inline.

| file |  |
|---|---|
| `collect.py` | One pass: fetch every enabled source and every query, parse, and report what failed. |
| `feeds.py` | Where the news comes from. Every URL in this file is a literal, and that is a security property. |
| `parse.py` | One parser for both feed formats, using stdlib `xml.etree` only. |
| `rank.py` | Which of a few hundred items belong on a ticker, in what order, and only once each. |

See [`../README.md`](../README.md) for what `news` is and why.
