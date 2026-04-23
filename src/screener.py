import os
import time
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


def fetch_fin_summary_window(client, end_dt, days=30):
    """指定期間のfin_summaryをレート制限に配慮して順次取得"""
    frames = []
    for i in range(days, -1, -1):
        dt = end_dt - timedelta(days=i)
        if dt.weekday() >= 5:
            continue
        try:
            df = client.get_fin_summary(date_yyyymmdd=dt.strftime("%Y%m%d"))
            if df is not None and not df.empty:
                frames.append(df)
        except Exception:
            pass
        time.sleep(0.5)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def screen(client):
    # 無料プランは約90日遅延
    end_dt = datetime.now() - timedelta(days=90)
    year_ago_end = end_dt - timedelta(days=365)

    fins_now = fetch_fin_summary_window(client, end_dt, days=30)
    fins_prev = fetch_fin_summary_window(client, year_ago_end, days=30)

    if fins_now.empty:
        raise RuntimeError("財務サマリーを取得できませんでした")

    # V2カラム名: DiscDate, Sales, OP, EPS, BPS
    fins_now = fins_now.sort_values("DiscDate").groupby("Code").last().reset_index()
    fins_prev = fins_prev.sort_values("DiscDate").groupby("Code").last().reset_index()

    fins_now = fins_now.rename(columns={"Sales": "Sales_now", "OP": "OP_now"})
    fins_prev = fins_prev.rename(columns={"Sales": "Sales_prev", "OP": "OP_prev"})

    df = fins_now.merge(
        fins_prev[["Code", "Sales_prev", "OP_prev"]],
        on="Code", how="left"
    )

    df["Sales_growth"] = (df["Sales_now"] - df["Sales_prev"]) / df["Sales_prev"].abs() * 100
    df["OP_growth"] = (df["OP_now"] - df["OP_prev"]) / df["OP_prev"].abs() * 100

    # 株価取得（直近7日）
    prices = client.get_eq_bars_daily_range(
        start_dt=end_dt - timedelta(days=7), end_dt=end_dt
    )
    prices_latest = prices.sort_values("Date").groupby("Code").last().reset_index()
    prices_latest = prices_latest[["Code", "C"]].rename(columns={"C": "Price"})

    df = df.merge(prices_latest, on="Code", how="left")

    # PER = 株価/EPS, PBR = 株価/BPS, ROE = EPS/BPS * 100
    df["PER"] = df["Price"] / df["EPS"]
    df["PBR"] = df["Price"] / df["BPS"]
    df["ROE"] = df["EPS"] / df["BPS"] * 100

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
