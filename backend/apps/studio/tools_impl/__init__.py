"""The tool implementations, imported for their side effects.

`registry.TOOLS` is populated by the `@tool` decorator at **import** time, so a module that is
never imported contributes nothing and fails silently -- the agent simply comes up with fewer
tools, the system prompt renders a shorter list, and nothing anywhere raises. That is the worst
kind of bug in this package, so the import list is here, it is explicit, and
`test_studio.py::RegistryTests::test_the_whole_tool_inventory_is_registered` compares the
registered names against a written-out inventory *per defining module*, so a module dropped from
the line below fails by name rather than by a total nobody reads.

Import order is alphabetical and does not matter; the decorator refuses duplicate tool names,
so a collision is an ImportError at startup rather than one tool quietly shadowing another.
"""
from . import cleanroom, comfy_tool, fs, host, stack  # noqa: F401

__all__ = ["cleanroom", "comfy_tool", "fs", "host", "stack"]
