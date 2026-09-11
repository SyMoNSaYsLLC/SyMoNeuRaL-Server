"""NVRTC compilation with a process-wide cache.

Compiling a kernel is expensive: ``vectorAdd`` takes ~3.6 s on its first run and
almost all of that is NVRTC, not the kernel. Nothing in a serving path should
pay that twice, so :class:`KernelCache` compiles each (source, arch, options)
combination once and hands out the resulting kernels thereafter.

**Include paths.** ``reduction_cg`` includes ``<cooperative_groups.h>``, which
transitively includes ``<cuda/std/type_traits>``. On this box those live in two
*different* places -- the CUDA include dir has cooperative_groups, and libcu++
ships in the ``cuda-cccl`` pip package. Passing only one of them fails with::

    catastrophic error: cannot open source file "cuda/std/type_traits"

That is the exact failure the ``reductionMultiBlockCG`` sample hits when invoked
without both directories. :func:`resolve_include_paths` finds them so callers
never have to.
"""

from __future__ import annotations

import functools
import os
import pathlib
from dataclasses import dataclass, field
from typing import Any, Iterable

from ..core.errors import CompilationError
from .kernels import ALL_SOURCES, TEMPLATE_INSTANTIATIONS

try:
    from cuda.core import Program, ProgramOptions
except ImportError as exc:  # pragma: no cover
    raise ImportError("cuda-core is required") from exc


@functools.lru_cache(maxsize=1)
def resolve_include_paths() -> tuple[str, ...]:
    """Locate the CUDA and libcu++ include directories.

    Order of preference:

    1. ``SYMONEURAL_CUDA_INCLUDE`` (``os.pathsep``-separated), for overrides.
    2. ``cuda.cccl.headers.get_include_paths()`` -- the authoritative source
       when cuda-cccl is installed.
    3. Filesystem probing of the usual toolkit locations.

    Returns every directory that exists, deduplicated, order preserved.
    """
    found: list[str] = []

    env = os.environ.get("SYMONEURAL_CUDA_INCLUDE")
    if env:
        found.extend(p for p in env.split(os.pathsep) if p)

    try:
        from cuda.cccl.headers import get_include_paths  # type: ignore

        paths = get_include_paths()
        for attr in ("cuda", "libcudacxx", "cub", "thrust"):
            v = getattr(paths, attr, None)
            if v:
                found.append(str(v))
    except Exception:
        pass

    for base in ("/usr/local/cuda", "/usr/local/cuda-13", "/usr/local/cuda-13.3"):
        for sub in ("targets/x86_64-linux/include", "include"):
            found.append(str(pathlib.Path(base) / sub))

    seen: set[str] = set()
    out: list[str] = []
    for p in found:
        if p not in seen and pathlib.Path(p).is_dir():
            seen.add(p)
            out.append(p)
    return tuple(out)


@dataclass
class CompiledModule:
    """A compiled module plus its kernels, keyed by name."""

    name: str
    module: Any
    kernels: dict[str, Any] = field(default_factory=dict)

    def get(self, kernel_name: str) -> Any:
        if kernel_name not in self.kernels:
            try:
                self.kernels[kernel_name] = self.module.get_kernel(kernel_name)
            except Exception as exc:
                raise CompilationError(
                    kernel_name,
                    f"module {self.name!r} has no kernel {kernel_name!r}: {exc}",
                ) from exc
        return self.kernels[kernel_name]


class KernelCache:
    """Compile-once, reuse-forever kernel store for one device architecture."""

    def __init__(self, arch: str, std: str = "c++17") -> None:
        self.arch = arch if arch.startswith("sm_") else f"sm_{arch}"
        self.std = std
        self._modules: dict[str, CompiledModule] = {}
        self._compiles = 0

    @property
    def compile_count(self) -> int:
        """How many NVRTC invocations have happened. Should plateau."""
        return self._compiles

    def compile(
        self,
        source_name: str,
        *,
        source: str | None = None,
        name_expressions: Iterable[str] | None = None,
        include_paths: Iterable[str] | None = None,
        extra_options: dict[str, Any] | None = None,
    ) -> CompiledModule:
        """Compile a named source from :mod:`.kernels` (or an explicit *source*).

        Repeat calls with the same *source_name* return the cached module.
        """
        if source_name in self._modules:
            return self._modules[source_name]

        src = source if source is not None else ALL_SOURCES.get(source_name)
        if src is None:
            raise CompilationError(
                source_name,
                f"unknown kernel source {source_name!r}; "
                f"known: {sorted(ALL_SOURCES)}",
            )

        names = tuple(name_expressions
                      or TEMPLATE_INSTANTIATIONS.get(source_name, ()))
        incs = tuple(include_paths) if include_paths else resolve_include_paths()

        opts: dict[str, Any] = {"std": self.std, "arch": self.arch}
        if incs:
            opts["include_path"] = list(incs)
        if extra_options:
            opts.update(extra_options)

        try:
            program = Program(src, code_type="c++", options=ProgramOptions(**opts))
            module = (program.compile("cubin", name_expressions=names)
                      if names else program.compile("cubin"))
        except Exception as exc:
            hint = ""
            if "cuda/std" in str(exc) or "cooperative_groups" in str(exc):
                hint = (
                    "\n\nHINT: this kernel needs libcu++ headers as well as the "
                    "CUDA include dir. Install cuda-cccl:\n"
                    "    pip install 'cuda-cccl[cu13]>=1.0.0'\n"
                    f"Include paths tried: {list(incs)}"
                )
            raise CompilationError(source_name, f"{exc}{hint}", source=src) from exc

        self._compiles += 1
        mod = CompiledModule(name=source_name, module=module)
        # Pre-bind template instantiations so callers use plain names.
        for n in names:
            try:
                mod.kernels[n] = module.get_kernel(n)
            except Exception:  # pragma: no cover
                pass
        self._modules[source_name] = mod
        return mod

    def kernel(self, source_name: str, kernel_name: str, **kw: Any) -> Any:
        """Convenience: compile (or reuse) then fetch one kernel."""
        return self.compile(source_name, **kw).get(kernel_name)

    def clear(self) -> None:
        self._modules.clear()
