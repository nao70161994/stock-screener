import os
from datetime import datetime, timedelta
import pandas as pd
import requests
import jquantsapi

NTFY_TOPIC = os.environ["NTFY_TOPIC"]
API_KEY = os.environ["JQUANTS_API_KEY"]

PER_MAX = 20.0
PBR_MAX = 3.0
ROE_MIN = 10.0
SALES_GROWTH_MIN = 10.0
OP_PROFIT_GROWTH_MIN = 10.0


def get_client():
    return jquantsapi.ClientV2(api_key=API_KEY)


def screen(client):
    # パラメータなしで全銘柄の最新財務サマリーを取得（1回のAPI呼び出し）
    fins = client.get_fin_summary()
    print(f"取得件数: {len(fins)}, カラム: {fins.columns.tolist()[:10]}")

    if fins.empty:
        raise RuntimeError("財務サマリーを取得できませんでした")

    # 銘柄ごとの最新レコード
    fins = fins.sort_values("DiscDate").groupby("Code").last().reset_index()

    # 株価取得（直近7日）
    end_dt = datetime.now() - timedelta(days=90)  # 無料プランの遅延を考慮
    prices = client.get_eq_bars_daily_range(
        start_dt=end_dt - timedelta(days=7), end_dt=end_dt
    )
    prices_latest = prices.sort_values("Date").groupby("Code").last().reset_index()
    prices_latest = prices_latest[["Code", "C"]].rename(columns={"C": "Price"})

    df = fins.merge(prices_latest, on="Code", how="left")

    # PER = 株価/EPS, PBR = 株価/BPS, ROE = EPS/BPS * 100
    df["PER"] = df["Price"] / df["EPS"]
    df["PBR"] = df["Price"] / df["BPS"]
    df["ROE"] = df["EPS"] / df["BPS"] * 100

    # 成長率はFSales/FOP（会社予想）で代替（無料プランでは前年実績が取りにくいため）
    df["Sales_growth"] = (df["FSales"] - df["Sales"]) / df["Sales"].abs() * 100
    df["OP_growth"] = (df["FOP"] - df["OP"]) / df["OP"].abs() * 100

    result = df[
        (df["PER"].notna()) & (df["PER"] > 0) & (df["PER"] <= PER_MAX) &
        (df["PBR"].notna()) & (df["PBR"] > 0) & (df["PBR"] <= PBR_MAX) &
        (df["ROE"].notna()) & (df["ROE"] >= ROE_MIN) &
        (df["Sales_growth"].notna()) & (df["Sales_growth"] >= SALES_GROWTH_MIN) &
        (df["OP_growth"].notna()) & (df["OP_growth"] >= OP_PROFIT_GROWTH_MIN)
    ]

    return result[["Code", "PER", "PBR", "ROE", "Sales_growth", "OP_growth"]].reset_index(drop=True)


def notify(df):
    if df.empty:
        body = "本日の該当銘柄なし"
    else:
        lines = [f"【割安成長株スクリーニング】{len(df)}銘柄\n"]
        for _, row in df.iterrows():
            lines.append(
                f"{row['Code']}\n"
                f"  PER:{row['PER']:.1f} PBR:{row['PBR']:.2f} "
                f"ROE:{row['ROE']:.1f}% "
                f"売上成長:{row['Sales_growth']:.1f}% "
                f"営業利益成長:{row['OP_growth']:.1f}%"
            )
        body = "\n".join(lines)

    requests.post(
        f"https://ntfy.sh/{NTFY_TOPIC}",
        data=body.encode("utf-8"),
        headers={"Title": "株スクリーニング結果", "Priority": "default"},
    )


def main():
    client = get_client()
    result = screen(client)
    notify(result)
    print(f"該当銘柄数: {len(result)}")
    print(result.to_string())


if __name__ == "__main__":
    main()
