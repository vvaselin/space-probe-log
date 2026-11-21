# Frontend

Nuxt 3 + TypeScript + Pinia + Three.js のフロントエンドです。全体の説明はリポジトリ直下の `README.md` にあります。

## コマンド

```bash
npm.cmd install
npm.cmd run dev
npm.cmd run typecheck
npm.cmd test
```

`npm test` は Node の組み込みのテスト（`node --test --experimental-strip-types`）で、追加の依存はありません。

## 画面

| パス | 内容 |
| --- | --- |
| `/` | ダッシュボード（地図、今の航行の様子、最新のログ、管理者の操作） |
| `/map` | 航行マップ（デバッグ表示つき） |
| `/logs` | ログの一覧 |
| `/logs/[番号]` | ログの詳細 |
| `/admin/login` | 管理者ログイン |

## 主なファイル

| ファイル | 内容 |
| --- | --- |
| `stores/voyage.ts` | 同期の材料（区間の式、時刻表、軌道要素、時計）とログを、画面全体で1つだけ持つ。サーバーとの時計の差を測り、数秒かけて寄せる |
| `utils/voyage/` | バックエンドと同じ式（軌道、区間、時刻表の補間）と、物理座標から表示座標への変換 |
| `components/VoyageMap.vue` | 地図。位置は毎フレーム計算し、式の更新でずれた時は 1.5 秒かけて寄せる |
| `composables/useVoyageHud.ts` | 表示用の値（シミュレーション時刻、区間、速度、距離、次の場面） |
| `components/VoyageAdminPanel.vue` | 管理者の操作（次の場面へ進める、一時停止・再開、モード、公開の間隔） |
| `tests/voyage.test.ts`、`tests/golden/voyage.json` | バックエンドの答えとの照らし合わせ。答えは backend の `python -m app.voyage.golden` で書き出す |

`utils/voyage/` のファイルは、Node のテストからも読めるよう、`.ts` の拡張子つきで import し合っています（`tsconfig.json` の `allowImportingTsExtensions`）。

## 古い仕組み

`components/SpaceMap.vue`、`composables/useProbeMotion.ts`、`stores/mission.ts` の古い部分、`/probe` と `/settings` の画面は、再設計の前のシミュレーション用です。ナビからは外していますが、コードは残っています。
