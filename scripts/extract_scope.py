#!/usr/bin/env python3
"""Batch-extract scope for every row via the claude_cli backend; cache to parquet.

Indexed by the full-dataset row position so features.build_features can reindex onto any subset.
Resumable: skips rows already present in the cache. Falls back to deterministic on failures.
"""
import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import pandas as pd
from houseprice.data_load import load_dataset
from houseprice.scope import ScopeExtractor, SCHEMA_KEYS, deterministic_scope

OUT = os.path.join("data", "processed", "scope.parquet")
BATCH = 35


def main():
    backend = os.environ.get("SCOPE_BACKEND", "claude_cli")
    df = load_dataset()
    ex = ScopeExtractor(backend=backend)
    if os.path.exists(OUT):
        cache = pd.read_parquet(OUT)
    else:
        cache = pd.DataFrame(index=df.index, columns=SCHEMA_KEYS, dtype=float)
    todo = [i for i in df.index if pd.isna(cache.loc[i, SCHEMA_KEYS[0]]) if i in cache.index] \
        if len(cache) == len(df) else list(df.index)
    if len(cache) != len(df):
        cache = pd.DataFrame(index=df.index, columns=SCHEMA_KEYS, dtype=float)
        todo = list(df.index)
    print(f"[scope] backend={backend} rows_to_do={len(todo)}", flush=True)
    done = 0
    for s in range(0, len(todo), BATCH):
        idxs = todo[s:s + BATCH]
        descs = [df.loc[i, "job_description"] for i in idxs]
        t0 = time.time()
        if backend == "claude_cli":
            res = ex.extract_batch(descs)
        else:
            res = [deterministic_scope(d) for d in descs]
        for i, r in zip(idxs, res):
            for k in SCHEMA_KEYS:
                cache.loc[i, k] = r[k]
        done += len(idxs)
        cache.to_parquet(OUT)  # checkpoint each batch
        print(f"[scope] {done}/{len(todo)}  (+{len(idxs)} in {time.time()-t0:.1f}s)", flush=True)
    print(f"[scope] DONE -> {OUT}", flush=True)


if __name__ == "__main__":
    main()
