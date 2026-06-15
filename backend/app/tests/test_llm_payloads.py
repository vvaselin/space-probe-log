from app.llm.openai_compatible import normalize_generated_log_payload
from app.schemas.domain import GeneratedLog


def test_openai_log_payload_accepts_body_alias() -> None:
    payload = normalize_generated_log_payload(
        {
            "title": "INSOMNIA-07 航行記",
            "summary": "summary",
            "body": "## 確認済みの事実\n- test\n\n## OVISの解釈\n- test",
            "reliability": 0.82,
        },
        "fallback",
    )
    log = GeneratedLog.model_validate(payload)
    assert log.body_markdown.startswith("## 確認済みの事実")
