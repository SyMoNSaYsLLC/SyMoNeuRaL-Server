# ops/manifests/ — build and model manifests

```
gateway-build.json    what the gateway binary was built from
llm-engine.json       the chat engine: upstream revision, build flags, artefact hash
llm-chat-model.json   which weights the chat surface loads
artifact.sh           hash one artefact, the same way every time
regenerate.sh         rebuild every manifest here
```

## What a manifest is for

Answering *"does this CVE affect us"* in one lookup. An artefact carrying a `symoneural-*`
name is a runtime identity, not a claim of authorship — the manifest is what maps it back to
the upstream revision it was built from. A rename without that map makes the question
unanswerable.

```bash
ops/manifests/regenerate.sh
git diff --exit-code        # a change here means an artefact changed. Say which, and why
```

Weights are manifested separately, in `models/PROVENANCE.json`, because they are fetched
rather than built and the obligations that travel with them are different.
