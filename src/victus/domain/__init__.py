"""Domain layer: entities, value objects and pure domain services.

Rules (enforced by review and by ``tests/unit/domain/test_purity.py``):

* no imports from ``victus.application``, ``victus.infrastructure``, ``victus.api``
* no SQLAlchemy, Pydantic, file or network I/O
* ``datetime`` values are always passed in, never read from the clock here
"""
