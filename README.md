# stock-screener

日本株のファンダメンタル指標（PER・PBR・ROE・成長率）でスクリーニングし、買い候補銘柄をAndroidに通知するアプリ。

## 動作概要

1. GitHub Actions が平日 10:00 JST に自動実行
2. J-Quants API から全銘柄の財務サマリーを取得
3. スクリーニング条件に合致した銘柄を ntfy.sh 経由で Android に通知

## スクリーニング条件

| 指標 | 条件 |
|---|---|
| PER | 20倍以下 |
| PBR | 3倍以下 |
| ROE | 10%以上 |
| 売上成長率（会社予想） | 10%以上 |
| 営業利益成長率（会社予想） | 10%以上 |

## セットアップ

### 1. J-Quants API キー取得

[J-Quants マイページ](https://jpx-jquants.com/) でアカウント登録し、APIキーを取得。

### 2. GitHub Secrets に登録

リポジトリの Settings → Secrets and variables → Actions から以下を追加：

| キー | 内容 |
|---|---|
| `JQUANTS_API_KEY` | J-Quants の API キー |
| `NTFY_TOPIC` | ntfy.sh のトピック名 |

### 3. Android で通知を受け取る

[ntfy アプリ](https://ntfy.sh/) をインストールし、設定した `NTFY_TOPIC` を購読。

## 技術スタック

- **言語**: Python 3.11
- **データソース**: J-Quants API V2（無料プラン）
- **実行基盤**: GitHub Actions
- **通知**: ntfy.sh

## 注意事項

- J-Quants 無料プランはデータが約 90 日遅延
- 成長率は会社予想（今期予想 vs 前期実績）を使用
