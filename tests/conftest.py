import pytest


@pytest.fixture(autouse=True)
def _no_live_hook_calls(monkeypatch):
    """Saving a new draft asks the model for hook options; tests that save
    drafts must never reach a real model, so that step is a no-op there.
    Hook tests call content_agent.apply_hook_options directly with a mock."""
    from scripts import main, review_ui

    monkeypatch.setattr(main, "apply_hook_options", lambda record: record)
    monkeypatch.setattr(review_ui, "apply_hook_options", lambda record: record)
