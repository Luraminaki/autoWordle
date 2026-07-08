"""Application layer: session/app-state management, domain models, and cross-cutting utilities.

Neither a core algorithm (`autoWordle.modules`) nor FastAPI-specific
(`autoWordle.webapp`) - `models`/`display`/`schemas` are the session/app-state
domain (business logic, its data contracts, its display formatting);
`logging_utils`/`paths` are generic bootstrapping utilities used by
`autoWordle.main` and this package alike.
"""
