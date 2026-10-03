import os
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import pandas as pd
import requests

BASE_URL = "https://api.jquants.com/v2"


def required_env(name):
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Required environment variable is missing: {name}")
    return value


PER_MAX = 20.0
PBR_MAX = 3.0
ROE_MIN = 10.0
SALES_GROWTH_MIN = 10.0
OP_PROFIT_GROWTH_MIN = 10.0

RATE_LIMIT_SLEEP = 13  # 5 req/min = 12s間隔、余裕を持って13s


# A single limiter covers pages, endpoints and retries.
_last_request_at = None
MAX_ATTEMPTS = 3


def jquants_get(path, params=None):
    """Fetch complete V2 data; never treat an API failure as an empty day."""
    global _last_request_at
    headers = {"x-api-key": required_env("JQUANTS_API_KEY")}
    params = dict(params or {})
    frames, seen_keys = [], set()
    while True:
        for attempt in range(MAX_ATTEMPTS):
            if _last_request_at is not None:
                time.sleep(max(0, RATE_LIMIT_SLEEP - (time.monotonic() - _last_request_at)))
            _last_request_at = time.monotonic()
            try:
                resp = requests.get(f"{BASE_URL}{path}", headers=headers, params=params, timeout=30)
            except (requests.Timeout, requests.ConnectionError):
                if attempt == MAX_ATTEMPTS - 1:
                    raise RuntimeError(f"J-Quants transport failure: {path}") from None
                time.sleep(2 ** attempt)
                continue
            if resp.status_code == 429 or 500 <= resp.status_code < 600:
                if attempt < MAX_ATTEMPTS - 1:
                    # Official 429 guidance: wait at least one minute, two to be certain.
                    time.sleep(120 if resp.status_code == 429 else 2 ** attempt)
                    continue
            if resp.status_code >= 400:
                # Do not include response bodies or credentials in Actions logs.
                raise RuntimeError(f"J-Quants HTTP {resp.status_code}: {path}")
            break
        try:
            data = resp.json()
        except ValueError:
            raise RuntimeError(f"Invalid J-Quants JSON: {path}") from None
        if not isinstance(data, dict) or not isinstance(data.get("data"), list):
            raise RuntimeError(f"Invalid J-Quants data envelope: {path}")
        if any(not isinstance(row, dict) for row in data["data"]):
            raise RuntimeError(f"Invalid J-Quants record: {path}")
        frames.append(pd.DataFrame(data["data"]))
        pagination_key = data.get("pagination_key")
        if not pagination_key:
            break
        if not isinstance(pagination_key, str) or pagination_key in seen_keys:
            raise RuntimeError(f"Invalid J-Quants pagination: {path}")
        seen_keys.add(pagination_key)
        params["pagination_key"] = pagination_key
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def require_columns(df, columns, source):
    missing = set(columns) - set(df.columns)
    if missing:
        raise RuntimeError(f"{source}: missing columns {sorted(missing)}")


def latest_financials(df):
    columns = ["Code", "DiscDate", "Sales", "OP", "EPS", "BPS"]
    if df.empty:
        return pd.DataFrame(columns=columns)
    require_columns(df, columns, "financial summary")
    df = df.copy()
    for col in ["Sales", "OP", "EPS", "BPS"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    order = [c for c in ["DiscDate", "DiscTime", "DiscNo"] if c in df.columns]
    # Keep a whole disclosure, rather than combining non-null values from different documents.
    return df.sort_values(order, kind="stable").drop_duplicates("Code", keep="last")


def fetch_fin_summary_window(end_dt, days=30):
    """指定期間のfin_summaryを取得（レート制限準拠）"""
    frames = []
    for i in range(days, 0, -1):
        dt = end_dt - timedelta(days=i)
        if dt.weekday() >= 5:
            continue
        df = jquants_get("/fins/summary", {"date": dt.strftime("%Y%m%d")})
        if not df.empty:
            frames.append(df)
            print(f"  {dt.strftime('%Y%m%d')}: {len(df)}件")
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def screen():
    # 無料プランは約90日遅延
    end_dt = datetime.now(ZoneInfo("Asia/Tokyo")) - timedelta(days=90)
    year_ago_end = end_dt - timedelta(days=365)

    print("=== 現在期間の財務サマリー取得 ===")
    fins_now = fetch_fin_summary_window(end_dt, days=30)
    print(f"現在期間: {len(fins_now)}件")

    print("=== 前年同期の財務サマリー取得 ===")
    fins_prev = fetch_fin_summary_window(year_ago_end, days=30)
    print(f"前年同期: {len(fins_prev)}件")

    if fins_now.empty:
        raise RuntimeError("財務サマリーを取得できませんでした")

    if fins_prev.empty:
        raise RuntimeError("前年同期データが空のため成長率を判定できません")
    fins_now = latest_financials(fins_now)
    fins_prev = latest_financials(fins_prev)

    fins_now = fins_now.rename(columns={"Sales": "Sales_now", "OP": "OP_now"})
    fins_prev = fins_prev.rename(columns={"Sales": "Sales_prev", "OP": "OP_prev"})

    df = fins_now.merge(
        fins_prev[["Code", "Sales_prev", "OP_prev"]],
        on="Code", how="left"
    )

    df["Sales_growth"] = (df["Sales_now"] - df["Sales_prev"]) / df["Sales_prev"].abs().where(df["Sales_prev"] != 0) * 100
    df["OP_growth"] = (df["OP_now"] - df["OP_prev"]) / df["OP_prev"].abs().where(df["OP_prev"] != 0) * 100

    # 株価取得：最後に成功した日付から直近の営業日を探す
    print("=== 株価取得 ===")
    prices_df = pd.DataFrame()
    for i in range(0, 30):
        dt = end_dt - timedelta(days=i)
        if dt.weekday() >= 5:
            continue
        tmp = jquants_get("/equities/bars/daily", {"date": dt.strftime("%Y%m%d")})
        if not tmp.empty:
            prices_df = tmp
            price_date = dt.strftime("%Y%m%d")
            print(f"  株価取得日: {price_date} ({len(prices_df)}件)")
            break
        print(f"  {dt.strftime('%Y%m%d')}: 空レスポンス")
    if prices_df.empty:
        raise RuntimeError("株価データを取得できませんでした")

    require_columns(prices_df, ["Code", "C"], "daily prices")
    prices_df = prices_df.rename(columns={"C": "Price"})
    prices_df["Price"] = pd.to_numeric(prices_df["Price"], errors="coerce")

    df = df.merge(prices_df[["Code", "Price"]], on="Code", how="left")

    # 会社名取得
    print("=== 会社情報取得 ===")
    info_df = jquants_get("/equities/master", {"date": price_date})
    if info_df.empty:
        raise RuntimeError("会社情報データを取得できませんでした")
    require_columns(info_df, ["Code", "CoName"], "listed issue master")
    df = df.merge(info_df[["Code", "CoName"]].rename(columns={"CoName": "CompanyName"}), on="Code", how="left")
    df["CompanyName"] = df["CompanyName"].fillna("")

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

    return result[["Code", "CompanyName", "Price", "PER", "PBR", "ROE", "Sales_growth", "OP_growth"]].reset_index(drop=True)


def notify(df):
    if df.empty:
        body = "本日の該当銘柄なし"
    else:
        lines = [f"【割安成長株スクリーニング】{len(df)}銘柄\n"]
        for _, row in df.iterrows():
            lines.append(
                f"{row['Code']} {row['CompanyName']} ¥{row['Price']:,.0f}\n"
                f"  PER:{row['PER']:.1f} PBR:{row['PBR']:.2f} "
                f"ROE:{row['ROE']:.1f}% "
                f"売上成長:{row['Sales_growth']:.1f}% "
                f"営業利益成長:{row['OP_growth']:.1f}%"
            )
        body = "\n".join(lines)

    response = requests.post(
        f"https://ntfy.sh/{required_env('NTFY_TOPIC')}",
        data=body.encode("utf-8"),
        headers={"Title": "Stock Screener", "Priority": "default"},
        timeout=30,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"ntfy HTTP {response.status_code}")


def main():
    required_env("JQUANTS_API_KEY")
    required_env("NTFY_TOPIC")
    result = screen()
    notify(result)
    print(f"該当銘柄数: {len(result)}")
    print(result.to_string())


if __name__ == "__main__":
    main()
