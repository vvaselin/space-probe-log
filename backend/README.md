# Backend

FastAPI + SQLAlchemy 2 + Pydantic 2 のバックエンドです。DBが状態の正本で、LLMは行動提案とログ文生成のみに使います。

## Commands

```bash
pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main:app --reload
pytest
```

## Environment

`.env.example` を `.env` にコピーして設定します。`OPENAI_API_KEY` が空なら `MockLLMClient` を使用します。
プロンプトは `app/prompts/*.md` に分離されています。

- `app/prompts/probe_profile.md`: 機体とOVISの設定
- `app/prompts/action_policy.md`: 行動提案の方針
- `app/prompts/log_writer_style.md`: ログ本文の文体

## API

- `GET /api/health`
- `GET /api/probe`
- `GET /api/logs`
- `GET /api/logs/{log_id}`
- `GET /api/world/systems`
- `GET /api/world/systems/{system_id}`
- `GET /api/world/map`
- `POST /api/simulation/step`
- `POST /api/simulation/reset`
