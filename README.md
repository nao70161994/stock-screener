# stock-screener

日本株のファンダメンタル指標（PER・PBR・ROE・成長率）でスクリーニングし、買い候補銘柄をAndroidに通知するアプリ。

## 動作概要

1. GitHub Actions が平日 10:00 JST に自動実行
2. J-Quants API V2 から財務サマリー・株価・会社情報を取得
3. スクリーニング条件に合致した銘柄を ntfy.sh 経由で Android に通知

## 通知サンプル

```
【割安成長株スクリーニング】3銘柄

1234 ○○商事 ¥1,500
  PER:12.3 PBR:1.50 ROE:15.2% 売上成長:18.5% 営業利益成長:22.1%

5678 △△テック ¥3,200
  PER:18.7 PBR:2.10 ROE:11.8% 売上成長:24.3% 営業利益成長:31.0%
```

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

[J-Quants マイページ](https://jpx-jquants.com/) でアカウント登録し、APIキーを取得（無料プランあり）。

### 2. GitHub Secrets に登録

リポジトリの Settings → Secrets and variables → Actions から以下を追加：

| キー | 内容 |
|---|---|
| `JQUANTS_API_KEY` | J-Quants の API キー |
| `NTFY_TOPIC` | ntfy.sh のトピック名（任意の文字列） |

### 3. Android で通知を受け取る

[ntfy アプリ](https://ntfy.sh/) をインストールし、設定した `NTFY_TOPIC` を購読。

## 技術スタック

- **言語**: Python 3.11
- **データソース**: J-Quants API V2（無料プラン）
- **実行基盤**: GitHub Actions（平日 10:00 JST 自動実行）
- **通知**: ntfy.sh → Android

## ディレクトリ構成

```
stock-screener/
├── .github/workflows/
│   └── screen.yml       # GitHub Actions ワークフロー
├── src/
│   └── screener.py      # メインスクリーニングスクリプト
├── requirements.txt
└── README.md
```

## 注意事項

- J-Quants 無料プランはデータが約 90 日遅延
- 成長率は会社予想（今期予想 vs 前期実績）を使用
- レート制限（5 req/分）に対応するため、実行に約 15 分かかる
- データ取得量が少ない月（1月・7月など）は候補銘柄が出にくい場合あり
