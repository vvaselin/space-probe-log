# Space Probe Log

INSOMNIA-07 の探査ログ閲覧・航行シミュレーションサイトです。FastAPI が世界データ、探査機状態、シミュレーション時計、航行状態の正本を管理し、Nuxt 3 + Three.js がダッシュボード、ログ、3D宇宙マップを表示します。

## Features

- INSOMNIA-07 の状態、航行、観測、資源採取、ログ閲覧
- REST API と Nuxt 画面 `/`, `/logs`, `/logs/[id]`, `/map`, `/probe`, `/settings`
- Three.js による星、惑星、信号、探査機、航路表示
- LLM は行動提案とログ文生成だけを担当し、距離・速度・ETAなどの物理量はPython側で確定します。

## INSOMNIA-07

- 探査機名: INSOMNIA-07
- 内部ID: `probe-insomnia-07`
- 種別: 長寿命恒星間無人探査船
- 本体: 全長18 m、幅6 m、高さ5 m
- アンテナ・放熱板展開時最大幅: 28 m
- 出発時質量: 42,000 kg
- 乾燥質量: 30,000 kg
- 推進剤質量: 4,000 kg
- 修理・資源加工用原料: 8,000 kg
- 通常恒星間巡航速度: 0.08c、約23,983 km/s
- 最大巡航速度: 0.12c、約35,975 km/s
- 想定運用期間: 500年以上
- 恒星系内航行: 通常推進
- 恒星間航行: ピアノドライブ
- 防御: 前方多層シールド
- 機能: 自己修復、資源採取、資源加工、長期休眠

物理仕様の正本はバックエンドの `ProbeSpecification` です。Markdownやプロンプトは説明用で、APIやログに渡す物理量はPython側で計算します。

## Simulation Clock

シミュレーション時計はバックエンドDBが正本です。

- `simulation_datetime`: 現在のシミュレーション日時
- `time_scale`: 現実時間に対する倍率
- `clock_state`: `running` または `paused`
- `last_real_datetime`: 最後に時計を確定した現実日時

時計更新時は、前回更新からの現実経過秒に `time_scale` を掛けてシミュレーション日時へ反映します。ページを閉じている間も、設定に応じて時間が進みます。

デフォルト倍率は `360x` です。

- `PAUSE`: 一時停止
- `360x`: 現実の1分 = シミュレーション内の6時間
- `1,440x`: 現実の1分 = シミュレーション内の1日
- `10,080x`: 現実の1分 = シミュレーション内の1週間
- `525,600x`: 現実の1分 = シミュレーション内の1年

開発中の意図しない大幅進行を避けるため、オフライン進行のON/OFFと反映上限を `/settings` から変更できます。初期上限は現実時間24時間です。

## Coordinates And Scale

物理座標と表示座標は分離しています。

- 恒星系間の物理位置: `StarSystem.x/y/z` をpc相当として扱います。
- 恒星系内の物理位置: `CelestialBody.orbit_radius_km` やAU/km系の値を使います。
- 探査機の物理航行状態: `ProbeNavigationState` に距離、速度、ETA、フェーズを保存します。
- Three.js表示座標: `display_x/display_y/display_z`
- Three.js表示半径: `display_radius`

表示座標上の距離や半径は描画専用です。航行距離や所要時間の計算には使用しません。

## Development

```bash
docker compose up --build
```

- Frontend: http://localhost:3000
- Backend: http://localhost:8000/api/health

Backend:

```bash
cd backend
pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main:app --reload
pytest
```

Frontend:

```bash
cd frontend
npm.cmd install
npm.cmd run dev
npm.cmd run typecheck
```

## Clock Operations

- 現在時計: `GET /api/simulation/clock`
- 一時停止/再開/倍率変更: `PATCH /api/simulation/clock`
- 開発用時計リセット: `POST /api/simulation/clock/reset`
- 全ワールド初期化: `POST /api/simulation/reset`
- シミュレーション設定: `GET/PATCH /api/settings/simulation`

`POST /api/simulation/reset` は世界、探査機、ログ、航行状態、時計を初期化します。時計だけを初期化したい場合は `POST /api/simulation/clock/reset` を使います。
