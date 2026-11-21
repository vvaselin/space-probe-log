# Space Probe Log

データで作った太陽系の中を、探査機 INSOMNIA-07 が場面ごとに進み、搭載AI NOCTUA-7 が見えた景色を航行ログとして書いていくサイトです。FastAPI のバックエンドが航路・物理・見え方・時計を決め、Nuxt 3 + Three.js のフロントエンドが地図とログを表示します。

設計は [docs/redesign.md](docs/redesign.md) にあります。

## 仕組み

処理は「航路計画 → 区間の式と場面の時刻表 → 見え方の計算 → ログ生成」の一本道です。距離・速度・時刻・見え方はコードが計算し、LLM が担うのは次の2つだけです。

- 行き先の選択：コードが点数順に並べた上位3件から1つ選ぶ。答えが候補の外なら1位を使う（上書きはこの1か所だけ）
- ログ本文：渡された場面・位置・速度・見えている天体をもとに書く。ヘッダーの数値と「次の観測予定地点」はコードが付ける

### 世界

- 物理座標は太陽中心・J2000黄道座標、単位は AU です。表示座標はフロントだけが計算します。
- 太陽系の32天体（太陽、惑星、主な衛星、準惑星、小天体）を `backend/app/voyage/data/solar_system.json` に持ちます。
  - 惑星：JPL の近似軌道要素（表2a/2b、紀元前3000年〜西暦3000年）
  - 準惑星と小天体：JPL Horizons の軌道要素（2080年5月時点）
  - 衛星：母天体のまわりの円軌道
  - 見た目（色、模様、環、反射率、大気）は手で書いた値
- 出発は 2080-05-02 12:00 UTC、地球の夜側からです。

### 航路

- 次の行き先は、太陽からの距離が今の1.5〜3倍の天体です。0.8倍より内側には戻りません。
- 惑星（または準惑星）に着いたら、データにある衛星を巡ってから次へ進みます。
- 寄り道は「本線より手前にあり、本線の候補より早く行ける天体」です。
- 今は実在の天体だけを使うので、航路はセドナかエリスのあたり（約20区間）で終わります。恒星間と、空白を埋める架空の天体はまだありません。

巡航速度は、太陽からの距離に応じて変わります（間は対数で補間）。

| 太陽からの距離 | 巡航速度 |
| --- | --- |
| 1.5 AU まで | 毎秒 200 km |
| 5 AU | 毎秒 1,000 km |
| 30 AU | 毎秒 3,000 km |
| 120 AU | 光速の5% |
| 惑星系の中（衛星の巡回） | 毎秒 180 km |

### 場面とログ

ログは時間の区切りではなく、場面ごとに1本書きます。場面は、出発、接近、最接近・到着、離脱、すれ違い、節目（太陽が円盤に見えなくなる線、ヘリオポーズなど）です。どの場面の時刻も、区間が決まった時点で先に計算します。

ログを書く前に、船から見た各天体の見かけの大きさ（満月との比）、方向、欠け方、明るさ、色と模様、前回との差を計算します。それを「大きく見える／小さな円盤／点」の段階（広角と望遠の2つ）にして LLM に渡します。

LLM の出力は検証し、だめなら1回だけやり直します。それでもだめなら、行き先は1位を使い、ログは短い定型文で埋めます。LLM に渡した入力はログごとに保存するので、プロンプトを変えて同じ入力から書き直せます。

### 時計と公開

- シミュレーション内の時刻は場面ごとに進み、現実の時間は「ログを公開する間隔」だけを決めます（既定は24時間に1本）。
- 次の公開は「最後の公開＋間隔＋そのあと一時停止していた時間」です。
- 公開のモード
  - 手動：管理者の「次の場面へ進める」か、CLI の `step` で進める。新しい航海はこのモードで始まる
  - 自動：バックエンドのスケジューラが、予定を過ぎたら1本だけ書く。止まっていた分をまとめて書くことはしない
- 一時停止の間は、シミュレーション内の時間も地図も止まります。

### 地図

フロントは位置を受け取らず、バックから受け取った「区間の式」「時刻表」「天体の軌道要素」から毎フレーム位置を計算します。式は Python と TypeScript で同じ物を持ち、`npm test` で両者が 1 km 未満で一致することを確かめます。

## 画面

| パス | 内容 |
| --- | --- |
| `/` | ダッシュボード（地図、今の航行の様子、最新のログ、管理者の操作） |
| `/map` | 航行マップ（地図、フロントとバックの位置の差などのデバッグ表示、管理者の操作） |
| `/logs` | ログの一覧 |
| `/logs/[番号]` | ログの詳細（URL はログ番号。書き直しても最新の版を表示） |
| `/admin/login` | 管理者ログイン |

## 開発

### Docker

```bash
docker compose up --build
```

- フロントエンド：http://localhost:3000
- バックエンド：http://localhost:8000/api/health

バックエンドの DB は `backend-data` ボリュームの `/data` に置かれます（アプリ本体は `space_probe_log.db`、航行は `voyage.db`）。

### バックエンド

```bash
cd backend
uv venv .venv
uv pip install --python .venv -r pyproject.toml --extra dev
.venv/Scripts/python -m uvicorn app.main:app --reload
.venv/Scripts/python -m pytest
```

`pip install -e ".[dev]"` でも入ります。macOS や Linux では `.venv/bin/python` を使ってください。DB のテーブルは、アプリの起動時に作られます。

### フロントエンド

```bash
cd frontend
npm.cmd install
npm.cmd run dev
npm.cmd run typecheck
npm.cmd test
```

環境によっては、`localhost:3000` の IPv6 側が別の応答（`426 Upgrade Required`）を返すことがあります。その時は http://127.0.0.1:3000 で開いてください。

### 最初の航海と、自動の公開

アプリの起動時に航海が1つもなければ、手動モードの航海が自動で作られます。1日1本で公開するには、管理者でログインして「自動にする」を押すか、CLI で自動にします。

```bash
# ローカル（--db を付けないとデバッグ用DBを操作する）
.venv/Scripts/python -m app.voyage.cli clock --mode auto --db sqlite:///./voyage.db

# Docker
docker compose exec backend python -m app.voyage.cli clock --mode auto --db sqlite:////data/voyage.db
```

### 設定

`backend/.env.example` を `backend/.env` にコピーして設定します。主な項目は次のとおりです。

| 項目 | 既定値 | 内容 |
| --- | --- | --- |
| `VOYAGE_DATABASE_URL` | `sqlite:///./voyage.db` | 航行のDB（API とスケジューラが使う） |
| `VOYAGE_DEBUG_DATABASE_URL` | `sqlite:///./voyage_debug.db` | CLI が標準で使うデバッグ用DB |
| `VOYAGE_PUBLISH_INTERVAL_SECONDS` | `86400` | 公開の間隔の既定値（管理画面と CLI で航海ごとに変えられる） |
| `VOYAGE_SCHEDULER_ENABLED` | `true` | 自動モードの航海を進めるスケジューラを動かすか |
| `VOYAGE_SCHEDULER_POLL_SECONDS` | `5` | スケジューラが予定を確かめる間隔 |
| `VOYAGE_LLM_ROUTE_PROVIDER` | `mock` | 行き先の選択に使う LLM（`mock` か `openai_compatible`） |
| `VOYAGE_LLM_LOG_PROVIDER` | `mock` | ログ本文に使う LLM（`mock` か `openai_compatible`） |
| `VOYAGE_LLM_{ROUTE,LOG}_BASE_URL` / `_MODEL` / `_API_KEY` | 空 | 用途ごとの接続先、モデル名、キー。空なら `OPENAI_*` を使う |
| `VOYAGE_LLM_TIMEOUT_SECONDS` | `120` | LLM の応答を待つ時間 |
| `OPENAI_API_KEY` / `OPENAI_BASE_URL` / `OPENAI_MODEL` | 空 / OpenAI / `gpt-6-luna` | 用途ごとの設定がない時に使う接続先 |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD_HASH` | `admin` / 空 | 管理者ログイン（ハッシュの作り方は `backend/README.md`） |
| `ADMIN_COOKIE_SECURE` | `false` | 本番（HTTPS）では `true` にする |

- `VOYAGE_LLM_*_BASE_URL` を変えた用途には、`OPENAI_API_KEY` を送りません。Ollama、LM Studio、llama.cpp、LiteLLM など、OpenAI 互換の口を持つサーバーをつなげます。
- `.env` の設定とは別に、テストは常にスケジューラを止め、LLM をモックにし、航行のDBをメモリ上に置きます（`backend/app/tests/conftest.py`）。

### CLI

`backend/` で `python -m app.voyage.cli <コマンド>` を実行します。`--db` を付けなければ、デバッグ用DB（`voyage_debug.db`）を使います。

| コマンド | 内容 |
| --- | --- |
| `route-table --seed S --legs 100` | LLM を使わず（モック）に航路を計画して表に出す。DB は使わない |
| `new --seed S` | 航海を作る |
| `step --count N` | 次の場面へ進め、ログを書く（時計のモードや一時停止に関係なく進める） |
| `rewrite LOG_ID` | 保存した入力から、今のプロンプトでログだけを書き直す（新しい版として保存） |
| `clock --mode auto\|manual --interval 秒 --pause\|--resume` | 時計の状態を見る・変える |

`python -m app.voyage.golden` は、フロントの式と照らし合わせる答え（`frontend/tests/golden/voyage.json`）を書き出します。Python 側の式を変えたら実行してください。

### 管理者の操作（API）

書き換える操作には、管理者セッションの Cookie と `X-CSRF-Token` が必要です。

| API | 内容 |
| --- | --- |
| `GET /api/voyage/sync` | 区間の式、時刻表、サーバーの時刻、天体の軌道要素、時計（誰でも読める） |
| `GET /api/voyage/position?real_at=` | 指定した現実の時刻での、バックが計算した位置（デバッグ用） |
| `GET /api/voyage/logs`、`/api/voyage/logs/{番号}` | ログの一覧と詳細 |
| `GET /api/voyage/clock` | 時計の状態 |
| `PATCH /api/voyage/clock` | モードと公開の間隔を変える（管理者） |
| `POST /api/voyage/clock/pause`、`/resume` | 一時停止と再開（管理者） |
| `POST /api/voyage/step` | 次の場面へ進め、ログを1本書く（管理者） |

## 古い仕組み

再設計の前のシミュレーション（`backend/app/services/simulation.py` などの古い航行、`/api/simulation/*`・`/api/world/*`・`/api/probe`・`/api/logs` の API、`frontend/components/SpaceMap.vue`、`/probe` と `/settings` の画面）は、コードとテストが残っています。画面からはつながっておらず、古いスケジューラも既定で止めています（`SIMULATION_SCHEDULER_ENABLED=false`）。新しい仕組みを本番で確かめたあとに消す予定です。
