# Space Probe Log

架空の宇宙探査機 AURORA-7 の探査ログ閲覧サイトです。FastAPI が世界データと探査機状態の正本を管理し、Nuxt 3 + Three.js がダッシュボード、ログ、3D宇宙マップを表示します。

## 実装範囲

- 太陽系と3つのシード生成された架空恒星系
- 探査機状態、行動検証、イベント、状態履歴、観測事実、解釈、ログ保存
- `move`, `observe`, `investigate_signal`, `collect_resource`, `wait`
- LLM抽象化、モックLLM、OpenAI互換APIクライアント
- REST APIとNuxt画面 `/`, `/logs`, `/logs/[id]`, `/map`, `/probe`
- Three.jsによる星、惑星、信号、探査機、航路表示

発展機能は未実装です。遅延銀河生成、文明交流、自動実行、RAGなどはサービス層や座標分離を拡張して追加する想定です。

## 起動

```bash
docker compose up --build
```

- Frontend: http://localhost:3000
- Backend: http://localhost:8000/api/health

初回アクセス時に開発用テーブルが作成され、API呼び出し時に初期ワールドが生成されます。

## Backend

```bash
cd backend
pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main:app --reload
pytest
```

ローカルに Python 3.12+ がない場合は Docker を使ってください。

## Frontend

Windows PowerShell では `npm.cmd` を使います。

```bash
cd frontend
npm.cmd install
npm.cmd run dev
npm.cmd run typecheck
```

## 設計判断

- LLMの提案は `ProposedAction` として検証し、Python側で対象存在、燃料、エネルギー、センサー、推進系、ストレージを確認します。
- LLMはDB状態を直接変更できません。確定した観測事実と解釈は `Discovery` に保存されます。
- ログ本文はLLMまたはモックが生成しますが、失敗時はテンプレート文にフォールバックします。
- LLMへ渡すプロンプトは `backend/app/prompts/*.md` で編集できます。
- 物理データ、シミュレーション座標、表示座標、表示半径を分けています。
- SQLiteを既定にし、`DATABASE_URL` でPostgreSQLへ移行可能にしています。

## 既知の制限

- 最小構成のため認証、管理画面、自動実行、WebSocket/SSEは未実装です。
- Three.js表示は簡易スケールで、物理的な距離・半径の完全再現ではありません。
- OpenAI互換APIは汎用HTTP実装のみで、プロンプトは最小です。
