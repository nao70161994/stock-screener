import os
import time
from datetime import datetime, timedelta
import pandas as pd
import requests

NTFY_TOPIC = os.environ["NTFY_TOPIC"]
API_KEY = os.environ["JQUANTS_API_KEY"]
BASE_URL = "https://api.jquants.com/v2"
HEADERS = {"x-api-key": API_KEY}

PER_MAX = 20.0
PBR_MAX = 3.0
ROE_MIN = 10.0
SALES_GROWTH_MIN = 10.0
OP_PROFIT_GROWTH_MIN = 10.0

RATE_LIMIT_SLEEP = 13  # 5 req/min = 12s間隔、余裕を持って13s


def jquants_get(path, params=None):
    """J-Quants API へのGETリクエスト（ページネーション対応）"""
    frames = []
    while True:
        resp = requests.get(f"{BASE_URL}{path}", headers=HEADERS, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        key = next((k for k in data if isinstance(data[k], list)), None)
        if key is None:
            break
        frames.append(pd.DataFrame(data[key]))

        pagination_key = data.get("pagination_key")
        if not pagination_key:
            break
        params = {**(params or {}), "pagination_key": pagination_key}
        time.sleep(RATE_LIMIT_SLEEP)

    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def fetch_fin_summary_window(end_dt, days=30):
    """指定期間のfin_summaryを取得（レート制限準拠）"""
    frames = []
    for i in range(days, -1, -1):
        dt = end_dt - timedelta(days=i)
        if dt.weekday() >= 5:
            continue
        try:
            df = jquants_get("/fins/summary", {"date": dt.strftime("%Y%m%d")})
            if not df.empty:
                frames.append(df)
                print(f"  {dt.strftime('%Y%m%d')}: {len(df)}件")
        except requests.HTTPError as e:
            print(f"  {dt.strftime('%Y%m%d')}: {e}")
        time.sleep(RATE_LIMIT_SLEEP)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def screen():
    # 無料プランは約90日遅延
    end_dt = datetime.now() - timedelta(days=90)
    year_ago_end = end_dt - timedelta(days=365)

    print("=== 現在期間の財務サマリー取得 ===")
    fins_now = fetch_fin_summary_window(end_dt, days=30)
    print(f"現在期間: {len(fins_now)}件")

    print("=== 前年同期の財務サマリー取得 ===")
    fins_prev = fetch_fin_summary_window(year_ago_end, days=30)
    print(f"前年同期: {len(fins_prev)}件")

    if fins_now.empty:
        raise RuntimeError("財務サマリーを取得できませんでした")

    for col in ["Sales", "OP", "EPS", "BPS"]:
        fins_now[col] = pd.to_numeric(fins_now[col], errors="coerce")
        fins_prev[col] = pd.to_numeric(fins_prev[col], errors="coerce")

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

    # 株価取得：最後に成功した日付から直近の営業日を探す
    print("=== 株価取得 ===")
    prices_df = pd.DataFrame()
    for i in range(0, 30):
        dt = end_dt - timedelta(days=i)
        if dt.weekday() >= 5:
            continue
        try:
            tmp = jquants_get("/equities/bars/daily", {"date": dt.strftime("%Y%m%d")})
            if not tmp.empty:
                prices_df = tmp
                print(f"  株価取得日: {dt.strftime('%Y%m%d')} ({len(prices_df)}件)")
                break
            print(f"  {dt.strftime('%Y%m%d')}: 空レスポンス")
        except Exception as e:
            print(f"  {dt.strftime('%Y%m%d')}: {e}")
        time.sleep(RATE_LIMIT_SLEEP)
    if prices_df.empty:
        raise RuntimeError("株価データを取得できませんでした")

    prices_df = prices_df.rename(columns={"C": "Price"})
    prices_df["Price"] = pd.to_numeric(prices_df["Price"], errors="coerce")

    df = df.merge(prices_df[["Code", "Price"]], on="Code", how="left")

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
    result = screen()
    notify(result)
    print(f"該当銘柄数: {len(result)}")
    print(result.to_string())


if __name__ == "__main__":
    main()
