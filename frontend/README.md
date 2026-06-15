# Frontend

Nuxt 3 + TypeScript + Pinia + Three.js のフロントエンドです。

## Commands

```bash
npm.cmd install
npm.cmd run dev
npm.cmd run typecheck
```

## Pages

- `/`: 探査機ダッシュボード
- `/logs`: ブログ形式ログ一覧
- `/logs/[id]`: ログ詳細
- `/map`: Three.js宇宙マップ
- `/probe`: 探査機詳細状態

Three.jsは `SpaceMap.vue` で `onMounted` 後に動的importし、SSRでは実行しません。
