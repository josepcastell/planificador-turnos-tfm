"""Normalització canònica d'slot_ids (espais/guions → '_', MAJÚSCULES).

És la convenció de les claus internes del solver (sk[2]) i dels overrides
de display. Viu a DOMAIN (capa base): abans era a src/core/utils i creava
la única inversió de capes del projecte (domain → core → services)."""


def normalize_slot(slot_id: str) -> str:
    return str(slot_id).strip().replace(" ", "_").replace("-", "_").upper()
