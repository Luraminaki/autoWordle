"""FastAPI routes and HTTP request/response contracts.

The app factory (`autoWordle.main`) composes this package with the rest of the
app; it lives at the package root since it's the composition root, not a
route/webapp implementation detail. The core game/solver engine
(`autoWordle.modules`, `autoWordle.app.models`) has no dependency on this
package - `scripts/benchmarks/testouille_wordle.py` uses it standalone, with
no FastAPI involved at all.
"""
