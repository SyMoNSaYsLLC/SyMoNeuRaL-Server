# `ops/gateway/artifacts/` — built output

What `build.mjs` emits. **Not source** — do not edit anything here; the next build discards
it, silently.

```bash
node ops/gateway/build.mjs
```

`ops/manifests/gateway-build.json` records what each artefact was built from: revision,
flags, hash. That is the file that answers "does this CVE affect us" in one lookup, and it is
the reason a built binary here is traceable rather than mysterious.
