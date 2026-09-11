# backend/output/ — rendered images

Where `symoneural-diffuse` writes. Served at `/api/gen/{name}`.

**Not in git and not backed up.** This is a cache of recent renders, not storage. The gallery
is pruned to `GALLERY_KEEP` (`backend/core/config.py`); anything worth keeping gets copied
out.

Deleting everything here is safe. The next render recreates what it needs, and the gallery
simply reports fewer images.
