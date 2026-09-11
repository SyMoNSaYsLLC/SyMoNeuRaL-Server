# backend/retired/ — routes that answer so an old link does not 404

Paths that used to exist. They redirect, or explain, rather than disappearing.

## Why they are not deleted

A removed page and a page that never existed return the same 404, and a visitor holding a
bookmark cannot tell which happened. A retired route says *this moved, and here is where* —
which costs one line and saves the question.

`_RETIRED_PAGES` in `backend/core/config.py` is the list. A page joins it when it is removed,
in the same commit that removes it. It leaves when nothing has requested it for long enough
that the redirect is only serving crawlers.

Nothing here is mounted in the schema. `include_in_schema=False` on every route: the API
reference documents what the service *is*, not what it was.
