"""The application packages.

This file exists so `apps.<x>` is a declared package rather than a namespace package that
happens to work, and so that `backend/apps` never needs to be on `sys.path`.

Putting it there opens a SECOND route to every module underneath: `import gateway` and
`import apps.gateway` load the same file into two module objects, and every class in them is
a distinct type. Three `SymonClient` classes once resolved ambiguously for exactly that
reason. `apps/test_one_route_to_each_module.py` pins the one-route property.
"""
