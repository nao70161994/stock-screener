# stock-screener

日本株のファンダメンタル指標（PER・PBR・ROE・成長率）でスクリーニングし、買い候補銘柄をAndroidに通知するアプリ。

## 動作概要

1. GitHub Actions が平日 10:17 JST に自動実行
2. J-Quants API V2 から財務サマリー・株価・会社情報・公式バリュエーションを取得
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
- 成長率は現在期間と暦年で1年前の各30日窓にある実績決算（Sales/OP）を比較する。会計期間・決算種別・会計基準・連結区分が一致しないデータは除外する。会社予想（FSales/FOP）は使っていない
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
- 30日窓で取得できない前年決算は比較できず、候補から除外する。開示日のずれにより候補を取りこぼす可能性は残る。決算期変更・会計基準変更・連結区分変更も保守的に除外する。
- PER/PBR/ROEは `/equities/valuation` の実績指標を使用する。PERの利益はTTM、ROEはTTM利益と期首期末の平均自己資本を基準とする。ROEはAPIの小数を100倍してパーセントにする。欠損値・無限大やAPI取得失敗を独自近似で補完しない。

### 照合した公式仕様

- [上場銘柄一覧 /equities/master](https://jpx-jquants.com/en/spec/eq-master)
- [決算サマリー /fins/summary](https://jpx-jquants.com/en/spec/fin-summary)
- [プラン別データ期間・12週間遅延](https://jpx-jquants.com/en/spec/data-spec)
- [レート制限・429待機](https://jpx-jquants.com/en/spec/rate-limits)
- [GitHub scheduleの無活動による停止](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)

## マージ後レビューへの対応（2026-10-03）

- 配当修正・業績予想修正を実績決算の選択対象から除外。`DocType`に`FinancialStatements`を含む開示のみを使う。訂正決算は同じ会計期間の最新行を採用し、空欄を古い開示で埋めない。
- `Code`・`DocType`・`CurPerType`と期間開始/終了・年度開始/終了の4日付を照合。前年の日付は暦年オフセットで計算し、閏日も扱う。前年窓には比較可能な期間を複数保持し、無関係な最新期間による上書きを避ける。
- 公式 `/equities/valuation` のPER/PBR/ROEを、終値と同じ日付で取得。四半期EPSを使ったPER、EPS/BPSによるROE近似は廃止。既存の閾値は維持するが、指標の定義が変わるため候補は変わりうる。
- 38件の回帰テストで配当/予想修正、決算期間・基準の不一致、訂正決算、閏年、公式ROEの単位変換、四半期EPS非依存、valuation欠損・API失敗を検証する。
- マージ後CIで検証する。実APIの契約権限・取得結果とAndroid通知は依然未検証。公式valuationはFreeでも12週間遅延で利用可能だが、実アカウントの応答確認は別途必要。

公式仕様: [バリュエーション指標](https://jpx-jquants.com/en/spec/eq-valuation)、[決算サマリー](https://jpx-jquants.com/en/spec/fin-summary)。
