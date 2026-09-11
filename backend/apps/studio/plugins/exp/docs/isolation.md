# Isolation: what this runtime does, what it does not, and what the difference would cost

`context.py`, `gate.py` and `loader.py` all point here, and they point here for one reason: this
package has a function called `isolate()` and a token on its write surface, and either one could
be mistaken for containment. Neither is. This document says what each actually does, why the
thing they are mistaken for is not achievable in-process, what it would take out-of-process, and
what was measured on this box rather than assumed.

## The one-sentence version

`isolate()` is a **composition** boundary: it decides *which object* a plugin sees under a
service name. It is not a **security** boundary: it does not decide *what a plugin may do*. A
plugin runs in the API process with the API process's privileges, and no arrangement of realms
changes that.

## What `isolate()` actually does

A service lives in the container under a key of the form `realm:name`. The root realm is the
empty string, so `bus` is `":bus"`. `ctx.isolate(["llm"])` returns a context view whose `llm`
resolves in a freshly minted realm — `"r3:llm"` — so a plugin mounted on that view which
provides `llm` writes into `r3` and a plugin on a sibling view writes into `r4`. Names not listed
still resolve in the root realm, which is the entire point: a session forks what it needs to fork
and shares the rest.

`presets/sessions.yaml` is the worked example. One `bus`, shared. Two groups, each isolating
`llm` and `memory`. `GET /api/exp/services` returns two rows named `llm` with different keys, and
the page shows them as two rows on purpose — collapsing them to one would hide the exact thing
isolation exists to make visible.

What that buys is real and worth having: two sessions cannot corrupt each other's state by
accident, a name collision becomes a mounted second copy instead of a race, and `provide()`
refuses a second live provider in one realm with an error that names `isolate()` as the fix. What
it does not buy is any restriction on what either plugin can *do*. Plugin A in realm `r3` can
still reach into `ctx.runtime.services` and read every service in every realm, because
`ctx.runtime` is right there, and Python has no way to take it away.

## Why in-process isolation of Python from Python is not achievable

Not "hard". Not achievable, in the sense that every published attempt has been withdrawn.

The membrane does not exist. Given any object, Python hands you the graph: `__class__`,
`__bases__`, `__subclasses__`, `__globals__` on any function, `__self__` on any bound method,
`gc.get_referrers` on anything at all, and `sys._getframe().f_back` to walk out of your own call
stack into your caller's locals. Remove the names and the objects are still reachable through
another path; there are dozens of paths and they are load-bearing for the interpreter itself. On
top of that sits `ctypes`, which can call `mmap` and `mprotect` and write to arbitrary addresses
in the process. A restriction that `ctypes` can lift is not a restriction.

Two prior attempts are worth naming because they are the ones people reach for:

* **`vm2`** (Node, not Python, but the closest thing to a working design) tried to build exactly
  this membrane for JavaScript — a proxy layer between host and guest objects. It was archived by
  its author after a run of sandbox-escape reports that could not be fixed without abandoning the
  design; the author's own conclusion was that the approach was unsound, not that a patch was
  pending. That is the strongest available evidence about this class of solution, and it comes
  from the project that tried hardest.
* **`RestrictedPython`** is sometimes cited as the Python answer. It is not the same thing: it
  restricts what *source text* is allowed to compile to, which is useful for a spreadsheet
  formula and useless here, because a plugin is an imported module and the import is where the
  interesting behaviour is. It also does not attempt to stop a plugin that gets hold of a real
  object.

So the honest statement, which `context.py` makes and this document repeats: **there is no
in-process isolation here and there could not be.** The seam for real isolation is
out-of-process.

## What out-of-process would actually cost

Three mechanisms, in ascending order of what they buy and what they take away. Everything marked
*measured* was checked on this machine on 2026-08-19; everything else is design.

### 1. A child process and a protocol

Run the plugin in a subprocess, marshal calls across a pipe. This is the only one of the three
that does not need the kernel's help, and it is where the seam already is: `registry.resolve()`
returns a `Runner` whose `call` is the single thing that touches the plugin object, so a remote
runner is a `Runner` whose `call` marshals instead of invoking.

The cost is not the subprocess. The cost is `Context`. Today a service is *the object itself* —
`ctx.bus` is the bus, and `bus.publish(...)` is a method call with no serialisation anywhere. A
plugin in another process cannot be handed an object; it has to be handed a proxy, and then every
service in the container needs a proxy protocol, every return value needs to be serialisable, and
`/call`'s honest `repr()` fallback stops being a nicety and becomes the wire format. That is a
different runtime, not a flag on this one. It is worth building the day a plugin arrives that
was not written in this repository. None has.

### 2. Landlock, seccomp, namespaces — on that child

*Measured on this machine, 2026-08-19.* Every figure below has its command beside it, because a
number labelled "measured" with no way to re-take the reading is indistinguishable from a number
someone remembered:

```console
$ cat /sys/kernel/security/lsm
lockdown,capability,landlock,yama,apparmor,tomoyo,bpf,ipe,ima,evm

$ python3 -c "import ctypes; print(ctypes.CDLL('libc.so.6').syscall(444, None, 0, 1))"
6

$ cat /proc/sys/user/max_user_namespaces
384841

$ cat /proc/sys/kernel/unprivileged_userns_clone
1

$ unshare --user --map-root-user id -u
0

$ command -v bwrap systemd-run wasmtime firejail nsjail
/usr/bin/bwrap
/usr/bin/systemd-run
```

Syscall 444 is `landlock_create_ruleset` on x86-64, and `(NULL, 0,
LANDLOCK_CREATE_RULESET_VERSION)` is the documented way to ask for the ABI version rather than to
create anything. So `landlock` is in the enabled LSM list and ABI version **6** is available:
across v1–v6 that covers filesystem paths, TCP bind and connect, `ioctl` on device files, and
scoping of signals and abstract UNIX sockets.

Unprivileged user namespaces are available, and the `unshare` line is the one that actually
proves it: it succeeded and reported uid **0** inside the namespace, as this user, with no `sudo`.
The two sysctls above it are why it is allowed to work — a non-zero `max_user_namespaces` ceiling
and `unprivileged_userns_clone = 1`. An earlier revision of this
paragraph said Debian 13 ships no `unprivileged_userns_clone` toggle; it does, at
`/proc/sys/kernel/unprivileged_userns_clone`, and on 13.6 / kernel 6.12.101+deb13-amd64 it reads
1. `bwrap` and `systemd-run` are installed; `wasmtime`, `firejail` and `nsjail` printed nothing,
which is `command -v` saying they are absent.

So the tools are here. The reason none of them is used is a property of Landlock that matters
more than its coverage: **it is per-process and irreversible.** A process that restricts itself
cannot unrestrict itself, and it passes the restriction to its children. Applying a ruleset
inside the API process would therefore restrict the API — every future `llama-server` launch,
every governor call, every static file read — for the life of the process. It is only sensible on
a child, which means it is strictly step 2 of mechanism 1 and buys nothing on its own.

There is one consequence worth writing down because it cuts the other way. A child denied `ioctl`
on `/dev/nvidiactl` cannot take the GPU. On a box with one 15.92 GiB card behind a mutex, that is
arguably the single most valuable restriction available — not for security, but because a plugin
that takes the card without a lease is the failure mode this repository is most exposed to. If
any of this is ever built, that is the first rule to write, and the reason will be resource
discipline rather than containment.

### 3. WASI

Real isolation, by construction: a wasm module has no syscalls it was not handed. It is also the
wrong shape for this box, and not marginally. A Python plugin compiled to wasm means shipping a
CPython build per plugin, and that interpreter cannot import `torch`, cannot open `/dev/nvidia*`
and cannot talk to CUDA — which is what the plugins here exist to do. `plugins/gpu.py` reads the
real machine; under WASI it would read nothing. The honest summary is that WASI isolates plugins
by removing the capability that made them worth mounting.

## What the token is, and what it is not

`gate.py` requires `SYMONEURAL_EXP_ENABLED=1` **and** a non-empty `SYMONEURAL_EXP_TOKEN`, and the token gates
every write plus one read (an entry's `config`). That is a switch on an HTTP surface. It decides
whether a request from the network can ask this process to mount a plugin. It says nothing about
what a mounted plugin may then do, and describing it as containment would be the one dishonest
sentence in this package.

The division is deliberate and narrower than the Studio's: **reads are open, writes and config
are not.** The whole argument for this runtime is that its state is inspectable, and a plugin
table nobody can see without a secret is a plugin table nobody looks at. `config` is the single
exception because that is where a plugin's credentials would live, and `Entry.snapshot` omits the
key entirely rather than emitting `config: {}` — an empty dict reads as "this plugin has no
config", which is a different and false statement.

Two more honest edges:

* `POST /call` implements no method allow-list as of 2026-08-20. Any public method on any mounted
  service, with whatever arguments are posted: the token is the line, and past it there is
  nothing. A deliberate pre-launch state, not a cleared posture — request ledger R-98, held.
* The trace redacts nothing a plugin puts in it. A plugin that traces a secret has traced a
  secret, into the ring and into `run/exp-events.jsonl` if a file sink is configured. The runtime
  does not inspect what it is given, and a filter there would be worse than none because it would
  be believed.

  The one exception is not a filter but a leak that was closed: `registry.check_config` used to
  quote the offending **value** into its failure message, and that message goes to the fiber, the
  trace and `GET /api/exp/events`, which is an open read. A manifest with
  `config: {interval: "sk-live-…"}` therefore published the credential to any visitor the moment
  it failed validation. The message now names the key and both types and not the value. That is a
  redaction of something the runtime itself wrote, which is a different act from inspecting what
  a plugin handed it.

## What a plugin can do to this process, said plainly

It can read every service in every realm. It can read and write any file this user can. It can
start processes, open sockets, take the GPU without a lease, and call `os._exit`. It can raise in
a way that leaves the API answering — that part the runtime does handle, and `plugins/explode.py`
is the worked example — but it can equally segfault the interpreter through a native extension,
and then there is no fiber state to look at because there is no process.

Everything in this repository was written in this repository. That is the actual reason this is
acceptable today, and it is a fact about the current contents of the directory rather than a
property of the design. The day it stops being true, mechanism 1 is the answer, and the seam is
`Runner.call`.
