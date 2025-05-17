from fastapi import FastAPI, Request
import requests
import os
import uvicorn
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

# Kredencialet tuaja
BIRDEYE_API_KEY = os.getenv("BIRDEYE_API_KEY", "YOUR_BIRDEYE_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "YOUR_TELEGRAM_CHAT_ID")

# Fjalë kyçe që tregojnë scam ose meme tokens pa potencial
BANNED_KEYWORDS = ["test", "dev", "airdrop", "rug", "scam", "pump", "elon", "420", "rekt", "fuck"]

# Parametrat e strategjisë
BUY_THRESHOLD = 6
SELL_PROFIT_PERCENT = 30      # +30% fitim -> sugjerim mbaje pak
SELL_DROP_FROM_PROFIT = 10    # -10% nga maksimumi pas fitimit -> shit
SELL_LOSS_PERCENT = -25       # -25% nga blerja -> shit
SELL_DROP_FROM_PROFIT_THRESHOLD = SELL_PROFIT_PERCENT - SELL_DROP_FROM_PROFIT  # 20%

# Dictionary për tokenat që po ndjekim
tracked_tokens = {}  # token_address -> {buy_price, peak_price, score, last_checked, hold_alert_sent}

def get_token_info(token_address):
    url = f"https://public-api.birdeye.so/public/token/{token_address}"
    headers = {"X-API-KEY": BIRDEYE_API_KEY}
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        return response.json().get("data", {})
    return {}

def evaluate_token_simple(token):
    score = 0
    try:
        volume = float(token.get("volume_15m", 0))
        liquidity = float(token.get("liquidity", 0))
        holders = int(token.get("holders", 0))
        name = token.get("name", "").lower()

        if volume >= 3000:
            score += 2
        if liquidity >= 5000:
            score += 2
        if holders >= 100:
            score += 2
        if not any(bad in name for bad in BANNED_KEYWORDS):
            score += 1
    except Exception as e:
        print("Error evaluating token:", e)
    return score

def send_telegram_msg(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}
    try:
        requests.post(url, data=data)
    except Exception as e:
        print("Telegram message failed:", e)

def send_telegram_alert_buy(token, score):
    msg = (
        f"🟢 *Sugjerim Blerje*\n"
        f"Token: {token.get('symbol')} ({token.get('name')})\n"
        f"Score: {score}\n"
        f"Çmimi aktual: ${token.get('price_usd')}\n"
        f"🔗 [Birdeye Link](https://birdeye.so/token/{token.get('address')}?chain=solana)"
    )
    send_telegram_msg(msg)

def send_telegram_alert_hold(token, price, change_percent):
    msg = (
        f"🟡 *Mbaje Pak Akoma*\n"
        f"Token: {token.get('symbol')} ({token.get('name')})\n"
        f"Çmimi aktual: ${price}\n"
        f"Fitimi: {change_percent:.2f}%\n"
        f"Mbase vazhdoje mbajtjen."
    )
    send_telegram_msg(msg)

def send_telegram_alert_sell(token, price, change_percent, reason):
    reason_text = {
        "drop_after_profit": "Rënie -10% pas fitimit",
        "loss": "Humbje -25%",
    }.get(reason, "Shitje")

    msg = (
        f"🔴 *Sugjerim Shitje*\n"
        f"Token: {token.get('symbol')} ({token.get('name')})\n"
        f"Çmimi aktual: ${price}\n"
        f"Ndryshim: {change_percent:.2f}%\n"
        f"Arsye: {reason_text}"
    )
    send_telegram_msg(msg)

def check_buy_sell(token):
    address = token.get("address")
    price = float(token.get("price_usd", 0))
    score = evaluate_token_simple(token)
    
    if address not in tracked_tokens and score >= BUY_THRESHOLD:
        tracked_tokens[address] = {
            "buy_price": price,
            "peak_price": price,
            "score": score,
            "last_checked": datetime.utcnow(),
            "hold_alert_sent": False,
        }
        send_telegram_alert_buy(token, score)
        return
    
    if address in tracked_tokens:
        info = tracked_tokens[address]
        buy_price = info["buy_price"]
        peak_price = info["peak_price"]
        change_percent = ((price - buy_price) / buy_price) * 100
        
        # Përditëso peak_price nëse çmimi rritet
        if price > peak_price:
            info["peak_price"] = price
            peak_price = price
        
        # Nëse arrin +30% dhe nuk e kemi dërguar hold alert
        if change_percent >= SELL_PROFIT_PERCENT and not info["hold_alert_sent"]:
            send_telegram_alert_hold(token, price, change_percent)
            info["hold_alert_sent"] = True
        
        # Nëse bie nën +20% pas arritjes së +30% (pra bie 10% nga maxima), shit
        elif change_percent <= SELL_DROP_FROM_PROFIT_THRESHOLD and info["hold_alert_sent"]:
            send_telegram_alert_sell(token, price, change_percent, "drop_after_profit")
            del tracked_tokens[address]
        
        # Nëse bie nën -25% nga çmimi i blerjes, shit
        elif change_percent <= SELL_LOSS_PERCENT:
            send_telegram_alert_sell(token, price, change_percent, "loss")
            del tracked_tokens[address]

@app.get("/")
async def root():
    return {"message": "Bot is running. Send POST requests to /webhook/token_created"}

@app.post("/webhook/token_created")
async def token_created(request: Request):
    data = await request.json()
    token_address = data.get("account")
    print(f"Marrë token të ri: {token_address}")

    token_data = get_token_info(token_address)
    token_data["address"] = token_address

    check_buy_sell(token_data)

    return {"status": "received"}

@app.on_event("startup")
async def startup_event():
    try:
        send_telegram_msg("✅ Bot-i u startua me sukses! Filloi kërkimi për token-at me potencial 🚀")
    except Exception as e:
        print("Nuk u dërgua mesazhi i nisjes:", e)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app:app", host="0.0.0.0", port=port, log_level="info")
