# backend/news/

> **Write this paragraph.** What is this surface for, who calls it, and what will bite
> someone changing it? The table below is generated and cannot answer any of those.
> Delete this block when you have.

<!-- generated: do not edit below -->

## Operations — 1

|  | path | what it does |
|---|---|---|
| GET | `/api/news/ticker` | The headlines the news refresher last collected |

## Library — no routes, no side effects on import

| file |  |
|---|---|
| `fetch.py` | One outbound GET, with the three limits that make it safe to run on a public box. |

## Programs — runnable, or driven by a route

| file |  |
|---|---|
| `collect.py` | One pass: fetch every enabled source and every query, parse, and report what failed. |
| `feeds.py` | Where the news comes from. Every URL in this file is a literal, and that is a security property. |
| `parse.py` | One parser for both feed formats, using stdlib `xml.etree` only. |
| `rank.py` | Which of a few hundred items belong on a ticker, in what order, and only once each. |

<!-- end generated -->
