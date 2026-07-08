def save_pending_input_drafts(scope_key: str) -> None:
    """Persist drafts that the editors don't autosave yet.

    Currently a no-op: eligibility per professional autosaves at
    eligibility_editor.py via autosave_draft_if_changed, and the weekday
    editors autosave too. Kept as a hook for the weekday planning tab.
    """
    return None
