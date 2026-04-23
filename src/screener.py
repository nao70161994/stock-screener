import os
import requests
import jquantsapi

NTFY_TOPIC = os.environ["NTFY_TOPIC"]
EMAIL = os.environ["JQUANTS_EMAIL"]
PASSWORD = os.environ["JQUANTS_PASSWORD"]

PER_MAX = 20.0
PBR_MAX = 3.0
ROE_MIN = 10.0
SALES_GROWTH_MIN = 10.0
OP_PROFIT_GROWTH_MIN = 10.0


def get_client():
    return jquantsapi.Client(mail_address=EMAIL, password=PASSWORD)


def fetch_indicators(client):
    """全銘柄の財務指標を取得"""
    df = client.get_fins_statements_all()
    return df


def calc_growth(df, col):
    """前年同期比成長率(%)を計算してカラム追加"""
    df = df.sort_values(["Code", "DisclosedDate"])
    df[f"{col}_prev"] = df.groupby("Code")[col].shift(4)  # 四半期ベースで1年前
    df[f"{col}_growth"] = (df[col] - df[f"{col}_prev"]) / df[f"{col}_prev"].abs() * 100
    return df


def screen(client):
    # 財務サマリー（PER・PBR・ROE）
    fins = client.get_fins_statements_all()
    fins = fins.sort_values(["Code", "DisclosedDate"])
    latest = fins.groupby("Code").last().reset_index()

    # 売上・営業利益の成長率計算
    fins = calc_growth(fins, "NetSales")
    fins = calc_growth(fins, "OperatingProfit")
    growth = fins.groupby("Code").last()[["NetSales_growth", "OperatingProfit_growth"]].reset_index()

    df = latest.merge(growth, on="Code", how="left")

    # 株価指標（PER・PBR・ROE）はfins_statementsには含まれないためprices_daily_quotesから取得
    prices = client.get_prices_daily_quotes_all()
    prices_latest = prices.sort_values("Date").groupby("Code").last().reset_index()
    prices_latest = prices_latest[["Code", "PER", "PBR"]]

    df = df.merge(prices_latest, on="Code", how="left")

    # ROEはfinsから計算（純利益/純資産）
    df["ROE_calc"] = df["NetIncome"] / df["NetAssets"] * 100

    # スクリーニング
    result = df[
        (df["PER"].notna()) & (df["PER"] <= PER_MAX) &
        (df["PBR"].notna()) & (df["PBR"] <= PBR_MAX) &
        (df["ROE_calc"].notna()) & (df["ROE_calc"] >= ROE_MIN) &
        (df["NetSales_growth"].notna()) & (df["NetSales_growth"] >= SALES_GROWTH_MIN) &
        (df["OperatingProfit_growth"].notna()) & (df["OperatingProfit_growth"] >= OP_PROFIT_GROWTH_MIN)
    ]

    return result[["Code", "CompanyName", "PER", "PBR", "ROE_calc",
                    "NetSales_growth", "OperatingProfit_growth"]].reset_index(drop=True)


def notify(df):
    if df.empty:
        body = "本日の該当銘柄なし"
    else:
        lines = [f"【割安成長株スクリーニング】{len(df)}銘柄\n"]
        for _, row in df.iterrows():
            lines.append(
                f"{row['Code']} {row['CompanyName']}\n"
                f"  PER:{row['PER']:.1f} PBR:{row['PBR']:.2f} "
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
