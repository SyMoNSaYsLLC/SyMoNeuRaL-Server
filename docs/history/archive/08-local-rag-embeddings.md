# Playbook 08 — Local RAG & Embeddings
### Giving small models knowledge without retraining: vector search, chunking, and retrieval that actually works, all on your own machine

Fine-tuning (P04) changes behavior; RAG supplies facts. A 3B model with good retrieval beats a 70B reciting from memory on *your* documents. This lab builds the whole pipeline locally and — the part everyone skips — teaches you to measure retrieval quality.

---

## Stage 1 — Embeddings from first principles (1 hour)

```bash
pip install sentence-transformers
```
```python
from sentence_transformers import SentenceTransformer
import numpy as np

# Strong small local embedders (2026-era): bge family, gte family, nomic-embed,
# e5 family. Start ~100-400M params; embedding models are tiny vs LLMs.
model = SentenceTransformer("BAAI/bge-small-en-v1.5")

docs = ["QEMU presents disks via virtio, IDE, or USB passthrough.",
        "Ternary quantization stores weights as -1, 0, +1.",
        "The Panama schedule is a 2-2-3 rotating shift pattern."]
q = "how do virtual machines expose storage devices"

D = model.encode(docs, normalize_embeddings=True)
Q = model.encode([q], normalize_embeddings=True)
print((D @ Q.T).ravel())   # cosine similarities — highest should be doc 0
```

Play: try queries that share NO words with the target doc (semantic match), then queries with shared words but wrong meaning. This calibrates what embeddings can and can't do.

**Deliverable:** 10 query→expected-doc pairs from your own notes; report how many rank #1.

---

## Stage 2 — Chunking: where RAG is won or lost (1 evening)

Documents must be split before embedding. The trade: small chunks = precise retrieval but shattered context; big chunks = context intact but diluted embeddings.

```python
# Solid default: 300-800 token chunks, 10-15% overlap, split on structure first
def chunk(text, target=500, overlap=60):
    import re
    paras = re.split(r"\n\s*\n", text)          # respect paragraph boundaries
    chunks, cur = [], ""
    for p in paras:
        if len((cur + p).split()) > target and cur:
            chunks.append(cur.strip())
            cur = " ".join(cur.split()[-overlap:]) + "\n" + p   # overlap tail
        else:
            cur += "\n\n" + p
    if cur.strip(): chunks.append(cur.strip())
    return chunks
```

Upgrades that matter, in order of value:
1. **Prepend context to every chunk**: `"[{doc_title} > {section}] {chunk}"` — cheap, big retrieval gains
2. **Respect structure**: never split mid-code-block or mid-table; markdown headers are gold
3. Semantic chunking (split at embedding-similarity dips) — marginal gains, try last

**Deliverable:** chunk your real corpus (your VM notes, project docs) two ways (300 vs 800 target), keep both for Stage 4's bake-off.

---

## Stage 3 — The full local stack (1 evening)

```bash
pip install chromadb   # simple local vector DB; alternatives: qdrant, sqlite-vec, faiss
```
```python
import chromadb
client = chromadb.PersistentClient(path="./ragdb")
col = client.create_collection("notes", metadata={"hnsw:space": "cosine"})

col.add(ids=[f"c{i}" for i in range(len(chunks))],
        documents=chunks,
        embeddings=model.encode(chunks, normalize_embeddings=True).tolist(),
        metadatas=[{"source": src} for src in sources])

def retrieve(query, k=5):
    qe = model.encode([query], normalize_embeddings=True).tolist()
    return col.query(query_embeddings=qe, n_results=k)

# Generation: stable prompt order for cache friendliness (Playbook 06!)
PROMPT = """You answer strictly from the provided context. If the context is
insufficient, say so and name what's missing. Cite chunk ids like [c3].

Context:
{context}

Question: {question}"""
```

Two upgrades that separate toy RAG from real RAG:
- **Hybrid search**: dense vectors miss exact identifiers (error codes, function names). Add BM25 keyword search (`pip install rank-bm25`) and merge result lists (reciprocal rank fusion, ~10 lines).
- **Reranking**: retrieve 20 with fast search, rerank to top-5 with a cross-encoder (`sentence_transformers.CrossEncoder`, e.g. bge-reranker). Biggest single quality jump available.

**Deliverable:** working `ask.py` over your own documents with hybrid retrieval + reranker.

---

## Stage 4 — Measure retrieval before blaming the LLM (the discipline)

Most "RAG is bad" is retrieval failure, invisible unless measured separately.

```python
# Gold set: 20-30 (question, ids_of_chunks_that_answer_it) pairs from YOUR corpus
def recall_at_k(gold, k=5):
    hits = sum(any(g in retrieve(q, k)["ids"][0] for g in gold_ids)
               for q, gold_ids in gold)
    return hits / len(gold)
```

Run the bake-off across your variants: small vs large chunks × dense vs hybrid × rerank on/off. Pick the winner on recall@5, THEN judge end-to-end answers.

Triage table when answers are bad:
| Symptom | Layer | Fix |
|---|---|---|
| Right chunk not in top-5 | retrieval | hybrid, rerank, better chunk context |
| Chunk retrieved, answer ignores it | generation | stronger grounding prompt, smaller k, better model |
| Answer invents beyond context | generation | "insufficient context" instruction, cite-required prompt |
| Chunk truncates the needed fact | chunking | bigger chunks or structure-aware splitting |

**Deliverable:** recall@5 table for 4+ configs, and your chosen production config.

## Iron laws
1. RAG quality is decided at chunking and retrieval; the LLM mostly reveals it.
2. Hybrid (dense+keyword) is the default; pure vector search fails on identifiers.
3. Rerankers are the cheapest large quality win in the stack.
4. Measure recall@k with a gold set before touching generation prompts.
5. Stable-prefix prompt layout makes RAG fast (P06) — design for the cache.
