# `frontend/site/assets/` — images, icons and brand

```
art/     generated and commissioned artwork
brand/   the marks. See business/IDENTITY.md before adding or altering one
icons/   UI icons
```

Served at `/assets/...`, cache-stamped by `build_cachebust.py` like everything else.

## What does not belong here

**Anything nothing references.** Nineteen unreferenced PNGs accumulated in the webroot before
the backend restructure, and `deploy.sh` copies but never deletes — so every one of them is
still being served somewhere until a person removes it. Its orphan report runs every deploy;
act on it.

An 11.6 MB browser "save page as" capture once sat in the staging directory and would have
gone straight into the public webroot. The staging directory is a working directory; the
webroot is not, and `deploy.sh` publishes only real web asset extensions for that reason.
