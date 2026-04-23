import os
from datetime import datetime, timedelta
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
    end_dt = datetime.now()
    year_ago = end_dt - timedelta(days=365)

    # 最新と1年前の財務サマリーを各1回取得（429対策）
    fins_now = client.get_fin_summary(date_yyyymmdd=end_dt.strftime("%Y%m%d"))
    fins_prev = client.get_fin_summary(date_yyyymmdd=year_ago.strftime("%Y%m%d"))

    fins_now = fins_now.rename(columns={
        "NetSales": "NetSales_now",
        "OperatingProfit": "OperatingProfit_now",
    })
    fins_prev = fins_prev.rename(columns={
        "NetSales": "NetSales_prev",
        "OperatingProfit": "OperatingProfit_prev",
    })

    df = fins_now.merge(
        fins_prev[["Code", "NetSales_prev", "OperatingProfit_prev"]],
        on="Code", how="left"
    )

    df["NetSales_growth"] = (
        (df["NetSales_now"] - df["NetSales_prev"]) / df["NetSales_prev"].abs() * 100
    )
    df["OperatingProfit_growth"] = (
        (df["OperatingProfit_now"] - df["OperatingProfit_prev"]) / df["OperatingProfit_prev"].abs() * 100
    )

    # 株価取得（直近7日で最新終値）
    prices = client.get_eq_bars_daily_range(
        start_dt=end_dt - timedelta(days=7), end_dt=end_dt
    )
    prices_latest = prices.sort_values("Date").groupby("Code").last().reset_index()
    prices_latest = prices_latest[["Code", "C"]].rename(columns={"C": "Price"})

    df = df.merge(prices_latest, on="Code", how="left")

    # PER = 株価/EPS, PBR = 株価/BPS, ROE = EPS/BPS * 100
    df["PER_calc"] = df["Price"] / df["EarningsPerShare"]
    df["PBR_calc"] = df["Price"] / df["BookValuePerShare"]
    df["ROE_calc"] = df["EarningsPerShare"] / df["BookValuePerShare"] * 100

    result = df[
        (df["PER_calc"].notna()) & (df["PER_calc"] > 0) & (df["PER_calc"] <= PER_MAX) &
        (df["PBR_calc"].notna()) & (df["PBR_calc"] > 0) & (df["PBR_calc"] <= PBR_MAX) &
        (df["ROE_calc"].notna()) & (df["ROE_calc"] >= ROE_MIN) &
        (df["NetSales_growth"].notna()) & (df["NetSales_growth"] >= SALES_GROWTH_MIN) &
        (df["OperatingProfit_growth"].notna()) & (df["OperatingProfit_growth"] >= OP_PROFIT_GROWTH_MIN)
    ]

    return result[["Code", "CompanyName", "PER_calc", "PBR_calc", "ROE_calc",
                    "NetSales_growth", "OperatingProfit_growth"]].reset_index(drop=True)


def notify(df):
    if df.empty:
        body = "本日の該当銘柄なし"
    else:
        lines = [f"【割安成長株スクリーニング】{len(df)}銘柄\n"]
        for _, row in df.iterrows():
            lines.append(
                f"{row['Code']} {row['CompanyName']}\n"
                f"  PER:{row['PER_calc']:.1f} PBR:{row['PBR_calc']:.2f} "
                f"ROE:{row['ROE_calc']:.1f}% "
                f"売上成長:{row['NetSales_growth']:.1f}% "
                f"営業利益成長:{row['OperatingProfit_growth']:.1f}%"
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
