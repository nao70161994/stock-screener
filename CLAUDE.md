# stock-screener

## プロジェクト概要
日本株のファンダメンタル指標（PER・PBR・ROE・配当利回りなど）でスクリーニングし、
買い候補銘柄をAndroidに通知するアプリ。自動売買はしない。

## 技術スタック
- **言語**: Python
- **データソース**: J-Quants API（JPX公式、無料プランあり） ※メイン
- **補助データ**: EDINET API（金融庁、完全無料）
- **実行基盤**: GitHub Actions（定期実行）
- **通知**: ntfy.sh → Androidアプリ

## ユーザー環境
- Android ユーザー、PC なし
- GitHub アカウント: nao70161994
- 常時起動サーバーなし → GitHub Actions で代替

## ディレクトリ構成
```
stock-screener/
├── .github/workflows/   # GitHub Actions ワークフロー
├── src/
│   └── screener.py      # メインスクリーニングスクリプト
├── requirements.txt
├── CLAUDE.md
└── README.md
```

## データソース比較

| サービス | 料金 | 取得できる主なデータ |
|---|---|---|
| **J-Quants API** | 無料プランあり | PER・PBR・ROE・配当利回り・株価 |
| **EDINET API** | 完全無料 | 有価証券報告書・決算短信・四半期報告書（XBRL形式） |
| 四季報AI API | 要問い合わせ（企業向け・高額） | 来期予想・アナリストコメント |
| 四季報オンライン | 月5,500円 | 手動閲覧のみ（API不可） |

### J-QuantsとEDINETの使い分け
- **指標スクリーニング** → J-Quants（PER・PBR等がすぐ使える）
- **詳細財務諸表の深掘り** → EDINET（XBRL解析が必要）

### EDINETで取得できる書類
- 有価証券報告書（年1回）：売上・利益・総資産・純資産・CF等
- 決算短信（四半期）：売上・利益・EPS・業績予想
- 大量保有報告書：5%超株主の動向
- 内部者取引報告：役員売買

## GitHub Secrets（要設定）
| キー | 内容 |
|---|---|
| `JQUANTS_EMAIL` | J-Quantsアカウントのメールアドレス |
| `JQUANTS_PASSWORD` | J-Quantsアカウントのパスワード |
| `NTFY_TOPIC` | ntfy.shのトピック名 |

## スクリーニング条件
- PER: 20倍以下
- PBR: 3倍以下
- ROE: 10%以上
- 売上成長率（前年比）: 10%以上
- 営業利益成長率（前年比）: 10%以上
- 時価総額フィルター: なし
- 配当利回り: 条件なし（割安成長株のため除外）

## 方針
- まずJ-Quants（無料）で指標スクリーニングを実装
- 四季報データは高額のため当面使わない
- 必要に応じてEDINETで財務詳細を補完

## 関連プロジェクト
- 5ch-monitor（同じGitHub Actions + ntfy構成の参考）
