import os
import requests
import yfinance as yf
import pandas as pd
import urllib3
from datetime import datetime
import pytz
from bs4 import BeautifulSoup  # 新增 BeautifulSoup

# 關閉略過 SSL 驗證警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def get_stock_list():
    """取得上市與上櫃股票清單"""
    stock_dict = {}
    print("正在取得上市與上櫃股票清單...")
    
    twse_url = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
    tpex_url = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes"
    
    try:
        res_twse = requests.get(twse_url, verify=False, timeout=10)
        if res_twse.status_code == 200:
            for item in res_twse.json():
                code, name = str(item.get('Code', '')), str(item.get('Name', ''))
                if len(code) == 4: stock_dict[f"{code}.TW"] = name
        
        res_tpex = requests.get(tpex_url, verify=False, timeout=10)
        if res_tpex.status_code == 200:
            for item in res_tpex.json():
                code = str(item.get('SecuritiesCompanyCode', ''))
                name = str(item.get('CompanyName', ''))
                if len(code) == 4: stock_dict[f"{code}.TWO"] = name
    except Exception as e:
        print(f"取得清單失敗: {e}")
    return stock_dict

def get_yahoo_pe(stock_code):
    """直接爬取台灣奇摩股市網頁上的本益比"""
    url = f"https://tw.stock.yahoo.com/quote/{stock_code}/technical-analysis"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        res = requests.get(url, headers=headers, timeout=5, verify=False)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, 'html.parser')
            # 根據截圖中的特徵：尋找包含「本益比 (同業平均)」的 span
            pe_label = soup.find("span", string=lambda t: t and "本益比" in t)
            if pe_label:
                # 找到它的兄弟節點或父節點底下的數值 span (字體為 Fz(16px))
                pe_value_span = pe_label.find_parent().find("span", class_=lambda c: c and "Fz(16px)" in c)
                if pe_value_span:
                    # 取得內容 (例如 "23.40 (22.95)")，並只切出前面的本益比數字
                    full_text = pe_value_span.get_text(strip=True)
                    pe_num = full_text.split("(")[0].strip()
                    return pe_num
    except Exception as e:
        print(f"爬取 {stock_code} 本益比失敗: {e}")
    # 失敗或找不到時回傳「不清楚」以保持一致性
    return "不清楚"

def send_discord_message(content):
    """發送至 Discord"""
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        print(content)
        return
    chunks = [content[i:i+1900] for i in range(0, len(content), 1900)]
    for chunk in chunks:
        requests.post(webhook_url, json={"content": chunk})

def find_ath_close_stocks():
    stock_dict = get_stock_list()
    tickers = list(stock_dict.keys())
    
    print(f"開始分析 {len(tickers)} 檔股票的歷史收盤價 (此步驟較慢)...")
    # yf.download 會同時取得 Open, High, Low, Close, Volume
    data = yf.download(" ".join(tickers), period="max", group_by='ticker', threads=True, progress=False)
    
    ath_stocks = []
    tw_tz = pytz.timezone('Asia/Taipei')
    now = datetime.now(tw_tz)
    
    # 標題用的日期格式
    today_str = now.strftime('%Y-%m-%d')
    # 內文用的日期格式
    today_slash_str = now.strftime('%Y/%m/%d')
    
    for ticker in tickers:
        try:
            # 確保有收盤價資料
            df = data[ticker].dropna(subset=['Close'])
            if df.empty or len(df) < 20: 
                continue
            
            # --- 計算掛牌後創歷史新高的次數 ---
            previous_max = df['Close'].shift(1).cummax()
            ath_count = (df['Close'] > previous_max).sum()
            
            # 取得歷史最高「收盤價」 (排除今天)
            historical_max_close = df['Close'].iloc[:-1].max()
            # 取得今天「收盤價」與「成交量(股)」
            today_close = df['Close'].iloc[-1]
            today_volume = df['Volume'].iloc[-1]
            
            # 判斷今日收盤價是否創歷史新高
            if pd.notna(today_close) and pd.notna(historical_max_close):
                if today_close >= historical_max_close:
                    clean_code = ticker.split('.')[0]
                    name = stock_dict[ticker]
                    
                    # 換算成交量為「張數」
                    volume_lots = int(today_volume / 1000) if pd.notna(today_volume) else "不清楚"
                    
                    # 改用爬蟲函式取得奇摩股市的本益比
                    pe_ratio = get_yahoo_pe(clean_code)

                    yahoo_link = f"<https://tw.stock.yahoo.com/quote/{clean_code}/technical-analysis>"
                    
                    # 組合 Discord 訊息，加入成交量與本益比
                    msg = (f"🚀 **{clean_code} {name}** | {today_slash_str} 歷史新高收盤價: `{today_close:.2f}` (第 {ath_count} 次創高)\n"
                           f"📊 成交量: `{volume_lots}` 張 | 本益比: `{pe_ratio}`\n"
                           f"🔗 {yahoo_link}")
                    ath_stocks.append(msg)
        except Exception:
            continue

    message = f"🏆 **台股 {today_str} 收盤價創歷史新高清單**\n" + "="*30 + "\n"
    if ath_stocks:
        message += "\n\n".join(ath_stocks)
    else:
        message += "今天沒有股票的收盤價創歷史新高。"
    
    send_discord_message(message)

if __name__ == "__main__":
    find_ath_close_stocks()
