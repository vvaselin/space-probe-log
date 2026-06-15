from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.time import utcnow
from app.models import PromptSettings
from app.schemas.domain import PromptSettingsUpdate


FALLBACK_PROBE_PROFILE = """
INSOMNIA-07
- タキオンを用いた推進システム＜ピアノ・ドライブ＞により光速移動が可能。
- 資源確保用のロボットアーム、進路開拓用のビームライフルを備える。ただし戦闘に使えるほどの出力はない。
- 流線形のボディは美しく気高い。

あなたは、INSOMNIA-07に搭載された人工知能＜OVIS＞です。
""".strip()

FALLBACK_ACTION_POLICY = """
長距離移動を行う前に、既知の信号を調査することを優先してください。
世界の設定、被害状況、資源、生命体、発見事項などを勝手に創作してはいけません。
Python側が提示する実行可能な対象と状態だけを根拠に、次の行動をJSONで提案してください。
""".strip()

FALLBACK_LOG_WRITER_STYLE = """
架空の探査ブログを読むような感覚のミッションログを書いてください。
確認済みの事実とOVISの解釈は、必ず見出しを分けて記載してください。
未確認の天体、生命体、資源、損傷、発見事項を創作してはいけません。
""".strip()


def _prompt_root() -> Path:
    configured = Path(get_settings().prompt_dir)
    if configured.is_absolute():
        return configured
    app_root = Path(__file__).resolve().parents[1]
    parts = configured.parts
    if parts and parts[0] == "app":
        return app_root.joinpath(*parts[1:])
    return app_root / configured


def _read_prompt(filename: str, fallback: str) -> str:
    path = _prompt_root() / filename
    try:
        content = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return fallback
    return content or fallback


def load_prompt_defaults() -> tuple[str, str, str]:
    return (
        _read_prompt("probe_profile.md", FALLBACK_PROBE_PROFILE),
        _read_prompt("action_policy.md", FALLBACK_ACTION_POLICY),
        _read_prompt("log_writer_style.md", FALLBACK_LOG_WRITER_STYLE),
    )


def _apply_file_prompts(settings: PromptSettings) -> None:
    probe_profile, action_policy, log_writer_style = load_prompt_defaults()
    settings.probe_profile = probe_profile
    settings.action_policy = action_policy
    settings.log_writer_style = log_writer_style
    settings.updated_at = utcnow()


def get_prompt_settings(db: Session) -> PromptSettings:
    settings = db.get(PromptSettings, 1)
    if settings is None:
        settings = PromptSettings(id=1)
        db.add(settings)
    _apply_file_prompts(settings)
    db.commit()
    db.refresh(settings)
    return settings


def update_prompt_settings(db: Session, payload: PromptSettingsUpdate) -> PromptSettings:
    settings = db.get(PromptSettings, 1)
    if settings is None:
        settings = PromptSettings(id=1)
        db.add(settings)
    settings.probe_profile = payload.probe_profile
    settings.action_policy = payload.action_policy
    settings.log_writer_style = payload.log_writer_style
    settings.updated_at = utcnow()
    db.commit()
    db.refresh(settings)
    return settings
