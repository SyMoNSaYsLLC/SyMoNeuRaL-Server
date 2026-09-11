"""`python3 -m cryptominer <cmd>`, run from backend/.

A package needs this file for `-m` to work at all; `if __name__ == "__main__"` inside
`__init__.py` is never reached that way. The dispatch itself lives in `__init__.main()` so
there is one copy of it and `python3 backend/cryptominer/__init__.py` keeps working.
"""
from . import main

raise SystemExit(main())
