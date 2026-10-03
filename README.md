# stock-screener

日本株のファンダメンタル指標（PER・PBR・ROE・成長率）でスクリーニングし、買い候補銘柄をAndroidに通知するアプリ。

## 動作概要

1. GitHub Actions が平日 10:17 JST に自動実行
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
| 売上成長率（実績比較） | 10%以上 |
| 営業利益成長率（実績比較） | 10%以上 |

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
- **実行基盤**: GitHub Actions（平日 10:17 JST 自動実行）
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

- J-Quants 無料プランの公式遅延は12週間。境界日の誤差を避けるため、このコードは90日前を取得基準日にする
- 成長率は現在期間と365日前の各30日窓にある最新開示の実績（Sales/OP）を比較する。会社予想（FSales/FOP）は使っていない
- 全エンドポイント・ページ・再試行を通して13秒以上のリクエスト間隔を確保。通常約10〜15分、再試行時は延びる（ジョブ上限45分）
- データ取得量が少ない月（1月・7月など）は候補銘柄が出にくい場合あり

## 修理・検証記録（2026-10-03）

調査対象のmain: `8cd160811100d5afbb49d93165c1a1a1ef9bc3e8`。

- 直近8件のschedule実行はすべてfailure。最後は2026-06-24、Run [28076140738](https://github.com/nao70161994/stock-screener/actions/runs/28076140738)。依存インストールは成功し、Run screenerステップで失敗していた。
- 保存期限切れのジョブログ取得はHTTP 410。当時の例外や、連続失敗がすべて同じ原因だったかは確認できない。
- 最新コードでもV2に対してV1の`/listed/info`を使用。公式V2の`/equities/master`、日本語会社名`CoName`へ変更し、株価と同じ過去日付を指定する。
- 前年データが空のとき、sortのガードだけでは列選択によるKeyErrorが残っていた。現在/前年の窓全体が空なら判定不能として明示的に失敗させ、通常の「該当銘柄なし」と区別する。個別銘柄の前年欠損・ゼロ分母は候補から除外する。
- API例外の握りつぶしを廃止。不完全な窓のデータで結果通知しない。429/5xx/Timeout/ConnectionErrorは最大3試行、429は120秒待機。400/401/403/404や不正JSONは即失敗。
- V2の`data`と`pagination_key`を検証。認証情報・レスポンス本文はエラーログへ出さない。
- 最新開示は行ごと選択する。従来のgroupby.lastによる異なる開示の数値混在を避ける。
- ntfyにタイムアウトとHTTPステータス検査を追加。
- secretsや外部API不要のCIをpush/PR時に実施（Python 3.11/3.12）。定期ジョブも実API呼び出し前に同じ回帰テストを実行する。

### 定期実行の再開

schedule定義自体はmainに残っているが、6月24日以降の実行履歴はない。公開リポジトリでは60日間活動がないとscheduleが自動無効化されるため、4月24日の最終コミットとの時間関係からはその可能性が高い。ただしworkflowのstateは取得できず、停止理由は断定できない。

PRは未マージの間、mainの定期処理を変更しない。マージ後、Actions → Stock Screenerで無効化表示があればEnable workflowを実施し、Run workflowで実APIを確認する。cron変更（平日10:17 JST）は再有効化の助けになるが、次回定期実行の成功まで復旧確認は完了していない。CIは実APIを呼ばず、Android通知も送らない。

### 検証コマンド

```sh
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python -m compileall -q src tests
```

### 確認できていないこと・指標の制約

- ローカルにJ-Quants実APIキーとntfyトピックはない。secret値は取得しない。認証・契約プラン・実データ取得・Androidへの通知は未検証。
- 30日窓同士の最新開示比較は、会計期間や開示種別が一致する保証がない。開示遅延・修正開示・四半期のずれで成長率が不適切になる可能性がある。
- EPS/BPSと終値を使った従来の指標計算を維持している。四半期EPSを年率換算せず、EPS/BPSによるROEは近似値。株式分割の補正もしていない。指標設計の改善は別途必要。

### 照合した公式仕様

- [上場銘柄一覧 /equities/master](https://jpx-jquants.com/en/spec/eq-master)
- [決算サマリー /fins/summary](https://jpx-jquants.com/en/spec/fin-summary)
- [プラン別データ期間・12週間遅延](https://jpx-jquants.com/en/spec/data-spec)
- [レート制限・429待機](https://jpx-jquants.com/en/spec/rate-limits)
- [GitHub scheduleの無活動による停止](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)
