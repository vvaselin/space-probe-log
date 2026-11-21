# Backend

FastAPI + SQLAlchemy 2 + Pydantic 2 のバックエンドです。航路・物理・見え方・時計はコードが決め、LLM は行き先の選択とログ本文だけを担います。全体の説明はリポジトリ直下の `README.md`、設計は `docs/redesign.md` にあります。

## コマンド

```bash
uv venv .venv
uv pip install --python .venv -r pyproject.toml --extra dev
.venv/Scripts/python -m uvicorn app.main:app --reload
.venv/Scripts/python -m pytest
```

`pip install -e ".[dev]"` でも入ります。macOS や Linux では `.venv/bin/python` を使ってください。

DB のテーブルは `create_all` で作ります。アプリ本体の DB（`DATABASE_URL`）はアプリの起動時、航行の DB（`VOYAGE_DATABASE_URL`）は起動時と CLI の実行時です。

- アプリ本体の DB は `alembic/` でも作れます（`.venv/Scripts/python -m alembic upgrade head`）。アプリの起動ですでにテーブルができている DB では、`alembic stamp head` で今の版を記録してから使ってください。
- 航行の DB には移行の仕組みがありません。既存のテーブルの列を変える時は、移行の仕組みを足してください。

## 設定

`.env.example` を `.env` にコピーして設定します。項目の一覧は `README.md` の「設定」にあります。

管理者パスワードは平文ではなく、Argon2 のハッシュを設定します。

```bash
python -c "from getpass import getpass; from pwdlib import PasswordHash; print(PasswordHash.recommended().hash(getpass()))"
```

出力を `ADMIN_PASSWORD_HASH` に設定してください。本番では HTTPS を使い、`ADMIN_COOKIE_SECURE=true` にします。

## 航行のパッケージ（`app/voyage/`）

| ファイル | 内容 |
| --- | --- |
| `orbits.py`、`world.py`、`data/solar_system.json` | 天体のデータと、時刻ごとの位置（ケプラー方程式、JPL の近似式、衛星の円軌道） |
| `visibility.py` | 見え方の計算（見かけの大きさ、方向、欠け方、明るさ、色と模様、前回との差、段階） |
| `motion.py` | 区間の式（加速・巡航・減速）と速度の表 |
| `route.py` | 航路計画（候補、点数、寄り道、衛星の巡回、動く目標を狙う到着時刻の計算） |
| `scenes.py` | 場面の時刻表 |
| `llm.py`、`prompts/*.md` | LLM への入力、出力の検証、1回のやり直し、定型文。プロンプト（NOCTUA-7） |
| `service.py` | 1場面進めてログを書く、ログの書き直し |
| `clock.py`、`scheduler.py` | 時計（モード、間隔、一時停止）と、自動モードの公開 |
| `sync.py` | 時刻表（現実の時刻とシミュレーション内の時刻の対応）と、現実の時刻からの位置 |
| `store.py` | 航行のテーブル（航海、区間、ログ、時計） |
| `cli.py`、`golden.py` | CLI と、フロントと照らし合わせる答えの書き出し |

API は `app/api/voyage.py` にあります（一覧は `README.md`）。LLM の接続先は `app/llm/factory.py` の `get_voyage_llm` が、用途（`route`、`log`）ごとに `mock` か `openai_compatible` を選びます。

## テスト

- 航行のテストは `app/tests/test_voyage_*.py` です。
- `app/tests/conftest.py` が、`.env` の設定に関係なく、すべてのテストでスケジューラを止め、LLM をモックにし、航行の DB をメモリ上に置きます。
- `test_admin_auth.py` はアプリ全体を起動するので、起動時の処理が `DATABASE_URL` の DB にテーブルを作ります（足りないテーブルを作るだけで、データは消しません）。気になる時は、`DATABASE_URL` を一時的な DB に向けて流してください。

```bash
DATABASE_URL=sqlite:///./tmp_test.db .venv/Scripts/python -m pytest
```

## 古いデータ

再設計の前のシミュレーションのコードは消しました。`app/models/entities.py` には、管理者のセッション（`AdminSession`）のほかに、当時のテーブルの定義が残っています。アプリ本体の DB の古いデータ（古いログなど）を消さずに読めるようにするためと、`alembic/` の移行がこれらを使うためです。
