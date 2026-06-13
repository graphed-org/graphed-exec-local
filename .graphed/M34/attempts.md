# M34 attempts — graphed-exec-local (bounded shared cache, broadcast coverage, LocalResources dedup)

## Iteration 0 — 2026-06-13 (freeze-M34-0)

- Review findings: P0-2 the M31 _shared_objects cache never evicted (a persistent pool over many
  distinct plans accumulated every compiled-IR process per worker); P1-3 the broadcast loop
  marked a token primed even if coverage was not reached (latent KeyError on an unprimed
  worker) and reached into the private pool._max_workers; P3-6 LocalResources was duplicated
  (its own copy vs graphed_core's M33 bounded one).
- FIX: _shared_objects is a FIFO OrderedDict capped at _SHARED_CACHE_CAP=32, evicting oldest in
  BROADCAST order — identical across workers (every worker sees the same broadcast sequence), so
  it stays in lockstep with the driver's _broadcast_tokens (now also a FIFO OrderedDict, same
  cap, same eviction). Re-running an evicted plan re-broadcasts transparently. Broadcast now
  RAISES if it cannot prime all workers (never silently caches an under-primed token); a dead
  worker surfaces as BrokenProcessPool at f.result(). max_workers is resolved eagerly in
  __init__ (os.cpu_count() fallback) so the broadcast target needs no private pool attribute.
  resources.py deleted; LocalResources reused from graphed_core.execution (now bounded+closeable
  -> the open_once handle leak P0-1 is fixed for the executors too, for free).
- frozen m34 (4): LocalResources IS graphed_core's (dedup pin); cache stays <= cap across cap+6
  distinct plans AND demonstrably evicts (size >= cap-2, not merely never-filled); an evicted
  plan re-runs correctly after re-broadcast; broadcast covers every worker (40 tasks/4 workers).
  Non-vacuous (the size<=cap + dedup-identity assertions fail against the unbounded/duplicate
  pre-impl). m31 ship-once suite unaffected.
- Gates green via the precommit script.
