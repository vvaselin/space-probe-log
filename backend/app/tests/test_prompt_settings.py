from app.core.time import utcnow
from app.models import PromptSettings
from app.repositories.settings import get_prompt_settings


def test_get_existing_prompt_settings_does_not_write(db) -> None:
    updated_at = utcnow()
    expected = PromptSettings(
        id=1,
        probe_profile="custom profile",
        action_policy="custom policy",
        log_writer_style="custom style",
        updated_at=updated_at,
    )
    db.add(expected)
    db.commit()

    actual = get_prompt_settings(db)

    assert actual.probe_profile == "custom profile"
    assert actual.action_policy == "custom policy"
    assert actual.log_writer_style == "custom style"
    assert actual.updated_at == updated_at
    assert not db.dirty


def test_get_missing_prompt_settings_creates_defaults(db) -> None:
    actual = get_prompt_settings(db)

    assert actual.id == 1
    assert actual.probe_profile
    assert actual.action_policy
    assert actual.log_writer_style
    assert db.get(PromptSettings, 1) is actual
