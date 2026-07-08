def normalize_slot(slot_id: str) -> str:
    return str(slot_id).strip().replace(" ", "_").replace("-", "_").upper()
