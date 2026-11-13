"""Shim de compatibilitat: `normalize_slot` viu ara a domain
(src/domain/slot_norm.py). Aquest re-export es manté perquè els
importadors existents no es trenquin."""

from src.domain.slot_norm import normalize_slot

__all__ = ["normalize_slot"]
