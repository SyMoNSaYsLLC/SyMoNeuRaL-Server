# backend/dispatchos/

> **Write this paragraph.** What is this surface for, who calls it, and what will bite
> someone changing it? The table below is generated and cannot answer any of those.
> Delete this block when you have.

<!-- generated: do not edit below -->

## Operations — 17

|  | path | what it does |
|---|---|---|
| POST | `/api/dispatchos/ask` | Ask SyMon AI about the board |
| GET | `/api/dispatchos/board` | Bookings visible to the signed-in user |
| POST | `/api/dispatchos/bookings` | Request a trip |
| GET | `/api/dispatchos/bookings/{bid}` | One booking, with its record trail |
| POST | `/api/dispatchos/bookings/{bid}/advance` | Move a booking one step |
| POST | `/api/dispatchos/bookings/{bid}/message` | Compose a reminder or review request (never sent) |
| POST | `/api/dispatchos/bookings/{bid}/quote` | Quote a trip against the operator's rules |
| GET | `/api/dispatchos/drivers` | Drivers |
| POST | `/api/dispatchos/drivers` | Add a driver |
| POST | `/api/dispatchos/login` | Sign in to DispatchOS |
| POST | `/api/dispatchos/logout` | Sign out |
| GET | `/api/dispatchos/me` | The signed-in user |
| GET | `/api/dispatchos/rules` | The operator's rate rules |
| PUT | `/api/dispatchos/rules` | Set the operator's rate rules |
| GET | `/api/dispatchos/status` | Whether DispatchOS is switched on here |
| GET | `/demo/dispatchos` | The application page. |
| GET | `/demo/dispatchos/docs` | DispatchOS documentation for the CUSTOMER surface, at the customer's own |

## Library — no routes, no side effects on import

| file |  |
|---|---|
| `ai.py` | SyMon AI for DispatchOS -- the managed assistant layer, and what it refuses to do. |
| `store.py` | DispatchOS persistence: users, bookings, the lifecycle, and the record trail. |

## Programs — runnable, or driven by a route

| file |  |
|---|---|
| `authz.py` | Route authorization classes for this application, as an explicit dependency seam. |
| `page.py` | The DispatchOS page, as one self-contained string. |
| `quotes.py` | The quote engine: the operator's own rules, applied to the operator's own jobs. |

<!-- end generated -->
