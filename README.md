# stock-screener

日本株ファンダメンタル指標スクリーニング

## 構成
- J-Quants API で財務指標取得
- GitHub Actions で定期実行
- ntfy でAndroidに通知

## セットアップ
1. J-Quants アカウント登録: https://jpx-jquants.com/
2. GitHub Secrets に `JQUANTS_EMAIL` `JQUANTS_PASSWORD` `NTFY_TOPIC` を設定
