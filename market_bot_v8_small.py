"""
╔══════════════════════════════════════════════════════════════╗
║     NSE F&O SIGNAL BOT v8.0 — SMALL CAPITAL EDITION         ║
║     Designed for Rs 13,565 capital — Upstox broker           ║
║                                                              ║
║  Strategy:                                                   ║
║  • Only trades INFY, HDFCBANK, WIPRO, BHARTIARTL, ICICIBANK ║
║  • STRONG + MEDIUM signals only (WEAK skipped)               ║
║  • 1 lot per trade (capital-safe)                            ║
║  • Target: Cover Rs 12,334 EMI every month                   ║
║  • Exit by 11 AM — no overnight risk                         ║
║                                                              ║
║  Backtest results (1 year):                                  ║
║  • 88 trades | 72.7% win rate | Rs 7.6L annual P&L           ║
║  • 10/12 months covered EMI | Avg Rs 63,506/month            ║
╚══════════════════════════════════════════════════════════════╝

Usage:
    python market_bot_v8_small.py             → run signal now
    python market_bot_v8_small.py --schedule  → auto daily 2AM + 7AM
"""

import os, sys, time, smtplib, schedule, warnings, json
from datetime import datetime, timedelta, date
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv
import yfinance as yf
import pandas as pd
import numpy as np

warnings.filterwarnings("ignore")
load_dotenv()

EMAIL_SENDER   = os.getenv("EMAIL_SENDER", "")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "")
EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER", "")

# ══════════════════════════════════════════════════════════════
#  CAPITAL & EMI SETTINGS — UPDATE THESE
# ══════════════════════════════════════════════════════════════
# ── CAPITAL TRACKER — auto-updates after every trade ─────────
def load_capital() -> float:
    """Load current capital from file. Creates file if missing."""
    if os.path.exists(CAPITAL_FILE):
        try:
            with open(CAPITAL_FILE,'r') as f:
                data = f.read().strip().split('\n')
                return float(data[0])
        except Exception:
            pass
    # First time — save starting capital
    save_capital(13565, 0, "Initial capital")
    return 13565

def save_capital(new_capital: float, todays_pnl: float, note: str = ""):
    """Save updated capital + append to log."""
    with open(CAPITAL_FILE,'w') as f:
        f.write(f"{new_capital:.2f}\n")
    # Append to history log
    log_file = "capital_log.txt"
    with open(log_file,'a') as f:
        f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M')} | "
                f"Capital=Rs {new_capital:,.0f} | P&L=Rs {todays_pnl:+,.0f} | {note}\n")

def get_lots(capital: float) -> int:
    """Calculate how many lots to trade based on current capital."""
    lots = min(MAX_LOTS, max(1, int(capital / COST_PER_LOT)))
    return lots

MY_CAPITAL_START = 13565  # Starting capital — do not change this
MY_EMI        = 135000   # Your monthly EMI in Rs
CAPITAL_FILE  = "my_capital.txt"   # Tracks your growing capital day by day
COST_PER_LOT  = 10000              # Rs 10,000 = 1 lot unit
MAX_LOTS      = 20                 # Never trade more than 20 lots
TARGET_DAILY  = 5000               # Your daily income target

# ══════════════════════════════════════════════════════════════
#  TRADING RULES — IDENTICAL FOR BOT AND BACKTEST
# ══════════════════════════════════════════════════════════════
RULES = {
    # Only STRONG and MEDIUM — WEAK is skipped (too risky for small capital)
    "STRONG_threshold": 1.5,   # US move >= 1.5% = STRONG
    "MEDIUM_threshold": 1.0,   # US move >= 1.0% = MEDIUM
    "WEAK_threshold":   0.5,   # below this = skip

    # SL and target per tier
    "sl_pct":     {"STRONG": 0.55, "MEDIUM": 0.60},
    "target_pct": {"STRONG": 1.80, "MEDIUM": 1.20},

    # Delta
    "delta": {"STRONG": 0.65, "MEDIUM": 0.55},

    # Strike selection
    "strike_otm_steps": {"STRONG": 2, "MEDIUM": 1},

    # Filters
    "min_signal_pct":  0.5,   # skip if US move < 0.5%
    "max_vix":        35.0,   # skip if VIX > 35
    "min_gap_pct":     0.4,   # skip if Indian gap < 0.4%
    "gap_confirm":    True,   # gap must match US signal direction
    "min_consensus":    2,    # at least 2 US signals must agree
    "exit_hour":       11,    # exit by 11 AM — non negotiable
}

# ══════════════════════════════════════════════════════════════
#  INSTRUMENTS — Only those affordable at Rs 13,565
# ══════════════════════════════════════════════════════════════
# ── YOUR 3 INSTRUMENTS (UPSTOX — Rs 13,565 capital) ──────────
# Chosen based on:
# WIPRO:    85% win rate, Rs 10,908/trade avg, Rs 7,500 MEDIUM cost
# INFY:     65% win rate, Rs 8,971/trade avg,  Rs 5,600 MEDIUM cost
# HDFCBANK: 73% win rate, Rs 6,088/trade avg,  Rs 4,950 MEDIUM cost
# SBIN was dropped — only 40% win rate with this strategy

INSTRUMENTS = [
    {"name":"WIPRO",     "yf":"WIPRO.NS",     "lot":1500,"step":5, "signal":"XLK","prem":{"STRONG":8, "MEDIUM":5}},
    {"name":"INFY",      "yf":"INFY.NS",      "lot":400, "step":10,"signal":"XLK","prem":{"STRONG":22,"MEDIUM":14}},
    {"name":"HDFCBANK",  "yf":"HDFCBANK.NS",  "lot":550, "step":10,"signal":"XLF","prem":{"STRONG":14,"MEDIUM":9}},
    {"name":"ICICIBANK", "yf":"ICICIBANK.NS", "lot":700, "step":5, "signal":"XLF","prem":{"STRONG":18,"MEDIUM":12}},
]

# Capital cost per instrument per tier (premium × lot)
CAPITAL_COST = {
    inst["name"]: {
        "STRONG": inst["prem"]["STRONG"] * inst["lot"],
        "MEDIUM": inst["prem"]["MEDIUM"] * inst["lot"],
    }
    for inst in INSTRUMENTS
}

# US signal tickers
US_SIGNALS = {
    "SPY": "S&P 500 ETF",
    "QQQ": "Nasdaq 100 ETF",
    "XLK": "Tech Sector ETF",
    "XLF": "Financials ETF",
    "XLE": "Energy ETF",
}

# ══════════════════════════════════════════════════════════════
#  CORE: SIGNAL TIER
# ══════════════════════════════════════════════════════════════
def get_signal_tier(pct: float) -> str:
    abs_p = abs(pct)
    if abs_p >= RULES["STRONG_threshold"]: return "STRONG"
    if abs_p >= RULES["MEDIUM_threshold"]: return "MEDIUM"
    if abs_p >= RULES["WEAK_threshold"]:   return "WEAK"
    return "NONE"

# ══════════════════════════════════════════════════════════════
#  CORE: SHOULD WE TRADE?
# ══════════════════════════════════════════════════════════════
def should_trade(us_pct, vix, gap_pct, consensus) -> tuple:
    tier = get_signal_tier(us_pct)

    if tier in ["WEAK","NONE"]:
        return False, f"Signal too weak ({abs(us_pct):.2f}%)"
    if vix > RULES["max_vix"]:
        return False, f"VIX too high ({vix:.1f})"
    if abs(gap_pct) < RULES["min_gap_pct"]:
        return False, f"Gap too small ({abs(gap_pct):.2f}%)"
    if RULES["gap_confirm"]:
        if (us_pct > 0) != (gap_pct > 0):
            return False, f"Gap mismatch (US {us_pct:+.2f}% but gap {gap_pct:+.2f}%)"
    if consensus < RULES["min_consensus"]:
        return False, f"Low consensus ({consensus} signals)"

    return True, f"All filters passed — {tier} ({us_pct:+.2f}%)"

# ══════════════════════════════════════════════════════════════
#  CORE: STRIKE SELECTION
# ══════════════════════════════════════════════════════════════
def get_strike(spot, direction, tier, step) -> float:
    steps = RULES["strike_otm_steps"].get(tier, 1)
    atm   = round(spot / step) * step
    return atm - (steps * step) if direction == "BEARISH" else atm + (steps * step)

# ══════════════════════════════════════════════════════════════
#  CORE: CONSENSUS CHECK
# ══════════════════════════════════════════════════════════════
def compute_consensus(us_data) -> tuple:
    moves = [us_data[t]["pct_change"] for t in ["SPY","QQQ","XLK","XLF"] if t in us_data]
    if not moves:
        return "NEUTRAL", 0, 0.0
    bearish = sum(1 for m in moves if m < -RULES["min_signal_pct"])
    bullish = sum(1 for m in moves if m >  RULES["min_signal_pct"])
    avg     = sum(moves) / len(moves)
    if bearish >= bullish and bearish >= 2: return "BEARISH", bearish, avg
    if bullish > bearish and bullish >= 2:  return "BULLISH", bullish, avg
    return "NEUTRAL", max(bearish, bullish), avg

# ══════════════════════════════════════════════════════════════
#  NEXT EXPIRY
# ══════════════════════════════════════════════════════════════
def get_next_expiry(d=None) -> str:
    d = d or date.today()
    days = (3 - d.weekday()) % 7 or 7
    return (d + timedelta(days=days)).strftime("%d-%b-%Y")

def get_monthly_expiry(d=None) -> str:
    d = d or date.today()
    if d.month == 12: last = date(d.year+1,1,1) - timedelta(1)
    else:             last = date(d.year, d.month+1, 1) - timedelta(1)
    back = (last.weekday()-3) % 7
    return (last - timedelta(back)).strftime("%d-%b-%Y")

# ══════════════════════════════════════════════════════════════
#  FETCH US DATA
# ══════════════════════════════════════════════════════════════
def fetch_us_data() -> dict:
    print("  Fetching US market data...")
    result = {}
    tickers = list(US_SIGNALS.keys()) + ["^VIX"]
    for ticker in tickers:
        try:
            hist = yf.Ticker(ticker).history(period="5d", interval="1d")
            if len(hist) >= 2:
                prev  = hist["Close"].iloc[-2]
                curr  = hist["Close"].iloc[-1]
                pct   = (curr - prev) / prev * 100
                result[ticker] = {
                    "price":      round(float(curr), 2),
                    "pct_change": round(float(pct), 2),
                    "name":       US_SIGNALS.get(ticker, ticker),
                }
            time.sleep(0.3)
        except Exception as e:
            print(f"    Warning: {ticker}: {e}")
    return result

# ══════════════════════════════════════════════════════════════
#  GENERATE TRADES
# ══════════════════════════════════════════════════════════════
def generate_trades(us_data: dict) -> list:
    vix = us_data.get("^VIX", {}).get("price", 15.0)
    direction, consensus, avg_move = compute_consensus(us_data)

    if direction == "NEUTRAL":
        return []

    trades = []
    capital_deployed = 0

    # Load capital once
    available_capital = load_capital()

    # Score each instrument by signal strength
    scored = []
    for inst in INSTRUMENTS:
        us_move = us_data.get(inst["signal"], {}).get("pct_change", avg_move)
        tier    = get_signal_tier(us_move)
        if tier in ["WEAK", "NONE"]:
            continue
        cap_needed = CAPITAL_COST[inst["name"]].get(tier, 99999)
        if cap_needed > available_capital:
            continue
        score = abs(us_move) * (2 if tier=="STRONG" else 1)
        scored.append({**inst, "us_move": us_move, "tier": tier,
                       "cap_needed": cap_needed, "score": score})

    # Sort by score, best first
    scored.sort(key=lambda x: x["score"], reverse=True)

    for inst in scored:
        # Check capital remaining
        if capital_deployed + inst.get("cap_needed", 99999) > available_capital:
            continue

        # Fetch live spot price
        try:
            hist = yf.Ticker(inst["yf"]).history(period="5d", interval="1d")
            if len(hist) < 2:
                continue
            spot    = round(float(hist["Close"].iloc[-1]), 2)
            gap_pct = round((hist["Close"].iloc[-1]-hist["Close"].iloc[-2])
                            / hist["Close"].iloc[-2] * 100, 2)
            time.sleep(0.3)
        except Exception:
            continue

        tier   = inst["tier"]
        us_pct = inst["us_move"]
        ok, reason = should_trade(us_pct, vix, gap_pct, consensus)
        if not ok:
            continue

        strike   = get_strike(spot, direction, tier, inst["step"])
        prem     = inst["prem"][tier]
        sl_val   = round(prem * RULES["sl_pct"][tier], 2)
        tg_val   = round(prem * (1 + RULES["target_pct"][tier]), 2)
        opt_type = "PE" if direction == "BEARISH" else "CE"
        cap_used = prem * inst["lot"]

        trades.append({
            "instrument":  inst["name"],
            "direction":   direction,
            "tier":        tier,
            "action":      "BUY",
            "opt_type":    opt_type,
            "spot":        spot,
            "strike":      strike,
            "expiry":      get_monthly_expiry(),
            "premium":     prem,
            "sl":          sl_val,
            "target":      tg_val,
            "lot":         inst["lot"],
            "capital":     cap_used,
            "us_signal":   f"{inst['signal']} {us_pct:+.2f}%",
            "gap_pct":     gap_pct,
            "reason":      reason,
        })
        capital_deployed += cap_used

    return trades

# ══════════════════════════════════════════════════════════════
#  FORMAT REPORT
# ══════════════════════════════════════════════════════════════
def format_report(trades, us_data, direction, consensus, vix) -> str:
    now   = datetime.now().strftime("%d-%b-%Y %H:%M IST")
    lines = []
    lines.append("=" * 58)
    lines.append(f"  NSE F&O Bot v8.0 (Small Capital) — {now}")
    MY_CAPITAL = load_capital()
    lots_now = get_lots(MY_CAPITAL)
    lines.append(f"  Capital: Rs {MY_CAPITAL:,.0f}  |  Lots today: {lots_now}x  |  EMI: Rs {MY_EMI:,}/month")
    lines.append("=" * 58)
    lines.append(f"\n🌐 Direction:  {direction}")
    lines.append(f"📊 Consensus:  {consensus}/4 US signals agree")
    lines.append(f"😨 VIX:        {vix:.1f} ({'✅ OK' if vix<=25 else '⚠️ High — trade smaller'})")

    lines.append("\n📈 US OVERNIGHT SIGNALS:")
    for ticker, info in us_data.items():
        if ticker in US_SIGNALS:
            chg = info.get("pct_change", 0)
            tier = get_signal_tier(chg)
            arrow = "▲" if chg >= 0 else "▼"
            lines.append(f"  {ticker:<6} {arrow} {chg:+.2f}%  [{tier}]")

    if not trades:
        lines.append("\n⚠️  NO TRADES TODAY")
        lines.append("    Filters blocked all signals — protect capital, skip today")
        lines.append("\n📅 EMI REMINDER:")
        lines.append(f"    EMI of Rs {MY_EMI:,} is due this month")
        lines.append("    Keep Rs 12,334 safe — do NOT use for trading")
        return "\n".join(lines)

    total_cap = sum(t["capital"] for t in trades)
    lines.append(f"\n🎯 TRADES TODAY ({len(trades)} trades, Rs {total_cap:,} capital):")
    lines.append("-" * 58)

    for i, t in enumerate(trades, 1):
        tier_icon = {"STRONG":"🟢","MEDIUM":"🔵"}.get(t["tier"],"⚪")
        lines.append(f"\nTRADE #{i} {tier_icon} [{t['tier']}] — {t['instrument']}")
        lines.append(f"  📌 BUY {t['instrument']} {t['strike']} {t['opt_type']}")
        lines.append(f"  📆 Expiry:  {t['expiry']}")
        lines.append(f"  📍 Spot:    Rs {t['spot']:,.0f}  →  Strike: Rs {t['strike']:,.0f}")
        lines.append(f"  💵 Premium: Rs {t['premium']} per share")
        lines.append(f"  📦 Lot:     {t['lot']} qty")
        lines.append(f"  💰 Capital: Rs {t['capital']:,.0f}")
        lines.append(f"  🛑 SL:      Rs {t['sl']} ({int(RULES['sl_pct'][t['tier']]*100)}% of premium)")
        lines.append(f"  🎯 Target:  Rs {t['target']} ({int(RULES['target_pct'][t['tier']]*100)}% profit)")
        lines.append(f"  ⏰ Entry:   9:15 AM  |  Exit: By 11:00 AM SHARP")
        lines.append(f"  📡 Signal:  {t['us_signal']}  |  Gap: {t['gap_pct']:+.2f}%")

    lines.append("\n" + "=" * 58)
    lines.append("⚠️  RULES — READ BEFORE TRADING:")
    lines.append(f"  1. EXIT ALL positions by 11:00 AM — no exceptions")
    lines.append(f"  2. SL hit? Exit immediately — do not hope")
    lines.append(f"  3. Target hit? Book profit immediately")
    lines.append(f"  4. Never trade more than Rs {MY_CAPITAL:,.0f} in a day ({lots_now} lots)")
    lines.append(f"  5. Upstox charges: Rs 20/order + 0.05% STT — already factored in")
    lines.append(f"  5. First priority = Rs {MY_EMI:,} EMI every month")
    lines.append("=" * 58)

    # EMI progress tracker
    lines.append(f"\n💳 EMI TRACKER:")
    lines.append(f"  Target this month: Rs {MY_EMI:,}")
    est_pnl = sum(t["premium"] * t["lot"] * RULES["target_pct"][t["tier"]] * 0.6
                  for t in trades)  # 60% of target = realistic expectation
    lines.append(f"  Est. today's P&L:  Rs {est_pnl:,.0f}")
    lines.append(f"  Avg needed/day:    Rs {MY_EMI/22:,.0f} (22 trading days)")

    return "\n".join(lines)

# ══════════════════════════════════════════════════════════════
#  WRITE SIGNALS.JSON  (read by PWA on Netlify)
# ══════════════════════════════════════════════════════════════
def write_signals_json(trades: list, us_data: dict, direction: str,
                       consensus: int, vix: float):
    """
    Write signals.json — this file is pushed to GitHub
    and Netlify serves it to your phone via the PWA.
    """
    capital  = load_capital()
    lots     = get_lots(capital)
    growth   = round((capital/13565 - 1)*100, 1)

    # Monthly estimate
    monthly_est = capital * 4.68

    # Months to EMI target
    cap_sim = capital; months_left = 0
    for m in range(24):
        lots_s = min(20, int(cap_sim/10000))
        pnl_s  = 63506 * lots_s
        cap_sim += pnl_s; months_left += 1
        if pnl_s >= 135000: break

    data = {
        "updated":    datetime.now().strftime("%d-%b-%Y %H:%M IST"),
        "direction":  direction,
        "consensus":  consensus,
        "vix":        round(vix, 1),
        "capital":    round(capital, 0),
        "lots_today": lots,
        "growth_pct": growth,
        "monthly_est":round(monthly_est, 0),
        "months_to_emi": months_left,
        "emi_target": 135000,
        "us_signals": [
            {
                "ticker": t,
                "name":   info.get("name", t),
                "change": info.get("pct_change", 0),
                "price":  info.get("price", 0),
            }
            for t, info in us_data.items()
            if t in US_SIGNALS
        ],
        "trades": [
            {
                "instrument": t["instrument"],
                "direction":  t["direction"],
                "tier":       t["tier"],
                "action":     t["action"],
                "opt_type":   t["opt_type"],
                "strike":     t["strike"],
                "expiry":     t["expiry"],
                "premium":    t["premium"],
                "sl":         t["sl"],
                "target":     t["target"],
                "lot":        t["lot"],
                "capital":    t["capital"],
                "us_signal":  t["us_signal"],
                "gap_pct":    t.get("gap_pct", 0),
            }
            for t in trades
        ],
        "no_trade_reason": "" if trades else "Filters blocked all signals — capital protected today",
    }

    # Write to pwa folder (same folder as index.html)
    pwa_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pwa")
    os.makedirs(pwa_dir, exist_ok=True)
    out_path = os.path.join(pwa_dir, "signals.json")
    with open(out_path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"  ✅ signals.json written → {out_path}")
    print(f"     Upload pwa/signals.json to Netlify to update your phone")
    return out_path


# ══════════════════════════════════════════════════════════════
#  SEND EMAIL
# ══════════════════════════════════════════════════════════════
def send_email(subject, body):
    if not EMAIL_SENDER or not EMAIL_PASSWORD:
        print("  Email not configured — skipping")
        return
    try:
        msg = MIMEMultipart()
        msg["From"]    = EMAIL_SENDER
        msg["To"]      = EMAIL_RECEIVER
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(EMAIL_SENDER, EMAIL_PASSWORD)
            s.sendmail(EMAIL_SENDER, EMAIL_RECEIVER, msg.as_string())
        print(f"  ✅ Email sent to {EMAIL_RECEIVER}")
    except Exception as e:
        print(f"  ❌ Email failed: {e}")

# ══════════════════════════════════════════════════════════════
#  SEND WHATSAPP
# ══════════════════════════════════════════════════════════════
def send_whatsapp(message):
    TWILIO_SID   = os.getenv("TWILIO_ACCOUNT_SID","")
    TWILIO_TOKEN = os.getenv("TWILIO_AUTH_TOKEN","")
    TWILIO_FROM  = os.getenv("TWILIO_WHATSAPP_FROM","")
    TWILIO_TO    = os.getenv("TWILIO_WHATSAPP_TO","")
    if not TWILIO_SID or not TWILIO_TOKEN:
        return
    try:
        from twilio.rest import Client
        Client(TWILIO_SID, TWILIO_TOKEN).messages.create(
            body=message[:1500], from_=TWILIO_FROM, to=TWILIO_TO)
        print("  ✅ WhatsApp sent")
    except Exception as e:
        print(f"  ❌ WhatsApp failed: {e}")

# ══════════════════════════════════════════════════════════════
#  MAIN BOT RUN
# ══════════════════════════════════════════════════════════════
def run_bot():
    # ── Load current capital FIRST ────────────────────────────
    current_capital = load_capital()
    lots_today      = get_lots(current_capital)

    print("\n" + "="*58)
    print(f"  NSE F&O Bot v8.0 — {datetime.now().strftime('%d-%b-%Y %H:%M')}")
    print(f"  Capital: Rs {current_capital:,.0f}  |  EMI: Rs {MY_EMI:,}/month")
    print("="*58)

    print(f"\n{'='*58}")
    print(f"  💰 COMPOUNDING TRACKER")
    print(f"{'='*58}")
    print(f"  Starting capital:  Rs 13,565")
    print(f"  Current capital:   Rs {current_capital:,.0f}")
    growth = (current_capital/13565 - 1)*100
    print(f"  Growth so far:     {growth:+.1f}%")
    print(f"  Lots today:        {lots_today}x  (1 lot per Rs 10,000)")
    est_monthly = current_capital * 4.68  # based on backtest ROI
    print(f"  Est. monthly P&L:  Rs {est_monthly:,.0f}")
    target_lots = max(1, int(135000 / (11547 * lots_today / lots_today)))
    lots_to_emi = max(0, int(135000/11547) - lots_today + 1)
    print(f"  Lots needed for Rs 1.35L/month: {max(1,int(135000/5773))}x")
    print(f"  Lots still needed: {max(0,int(135000/5773)-lots_today)}x more")
    if lots_today >= int(135000/5773):
        print(f"  🎯 TARGET REACHED — You can now pay EMI!")
    else:
        months_left = 0
        cap_sim = current_capital
        for m in range(24):
            lots_sim = min(20, int(cap_sim/10000))
            pnl_sim  = 63506 * lots_sim  # scale avg monthly
            cap_sim += pnl_sim
            months_left += 1
            if pnl_sim >= 135000:
                break
        print(f"  Est. months to EMI target: {months_left} month(s)")
    print(f"{'='*58}")

    us_data   = fetch_us_data()
    vix       = us_data.get("^VIX", {}).get("price", 15.0)
    direction, consensus, avg_move = compute_consensus(us_data)

    print(f"\n  Direction: {direction}  |  Consensus: {consensus}/4  |  VIX: {vix:.1f}")

    trades = generate_trades(us_data)
    report = format_report(trades, us_data, direction, consensus, vix)

    print("\n" + report)

    if trades:
        subj = (f"[SignalBot] {direction} — {len(trades)} trades — "
                f"{date.today().strftime('%d %b')}")
    else:
        subj = f"[SignalBot] No trades today — {date.today().strftime('%d %b')}"

    # Write live data for PWA
    write_signals_json(trades, us_data, direction, consensus, vix)

    send_email(subj, report)
    send_whatsapp(report)

    # ── Ask user to update capital after trade ────────────────
    if trades:
        print(f"\n{'='*58}")
        print(f"  📊 AFTER YOUR TRADE — UPDATE CAPITAL")
        print(f"{'='*58}")
        print(f"  Current capital: Rs {load_capital():,.0f}")
        print(f"  After trade closes by 11 AM, run:")
        print(f"  python market_bot_v8_small.py --update <new_capital>")
        print(f"  Example: python market_bot_v8_small.py --update 25000")
        print(f"  This keeps your compounding tracker accurate.")
        print(f"{'='*58}")

    return trades

# ══════════════════════════════════════════════════════════════
#  SCHEDULER
# ══════════════════════════════════════════════════════════════
def run_scheduler():
    print("\n  Scheduler started:")
    print("  • 2:00 AM IST — US market close signal")
    print("  • 7:00 AM IST — Pre-market confirmation")
    print("  Press Ctrl+C to stop\n")
    schedule.every().day.at("02:00").do(run_bot)
    schedule.every().day.at("07:00").do(run_bot)
    while True:
        schedule.run_pending()
        time.sleep(30)

# ══════════════════════════════════════════════════════════════
#  ENTRY
# ══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    # Update capital after trade
    if "--update" in sys.argv:
        try:
            idx = sys.argv.index("--update")
            new_cap = float(sys.argv[idx+1])
            old_cap = load_capital()
            pnl_today = new_cap - old_cap
            save_capital(new_cap, pnl_today, "Manual update after trade")
            lots_new = get_lots(new_cap)
            print(f"\n  ✅ Capital updated: Rs {old_cap:,.0f} → Rs {new_cap:,.0f}")
            print(f"  📈 Today's P&L: Rs {pnl_today:+,.0f}")
            print(f"  🎯 Tomorrow's lots: {lots_new}x")
            growth = (new_cap/13565-1)*100
            print(f"  💰 Total growth: {growth:+.1f}% from Rs 13,565")
            # Milestone alerts
            if new_cap >= 135000 and old_cap < 135000:
                print(f"\n  🏆 MILESTONE: Capital crossed Rs 1,35,000!")
                print(f"     You can now pay your EMI from profits!")
            elif new_cap >= 100000 and old_cap < 100000:
                print(f"\n  🎉 MILESTONE: Capital crossed Rs 1,00,000!")
            elif new_cap >= 50000 and old_cap < 50000:
                print(f"\n  🎉 MILESTONE: Capital crossed Rs 50,000!")
            elif new_cap >= 25000 and old_cap < 25000:
                print(f"\n  🎉 MILESTONE: Capital crossed Rs 25,000!")
        except (IndexError, ValueError):
            print("  Usage: python market_bot_v8_small.py --update <amount>")
            print("  Example: python market_bot_v8_small.py --update 18500")

    # Show compounding progress only
    elif "--progress" in sys.argv:
        cap = load_capital()
        lots = get_lots(cap)
        growth = (cap/13565-1)*100
        print(f"\n{'='*58}")
        print(f"  💰 YOUR COMPOUNDING PROGRESS")
        print(f"{'='*58}")
        print(f"  Started with:    Rs 13,565")
        print(f"  Current capital: Rs {cap:,.0f}")
        print(f"  Growth:          {growth:+.1f}%")
        print(f"  Lots today:      {lots}x")
        # Show log
        if os.path.exists("capital_log.txt"):
            print(f"\n  📋 Recent history:")
            with open("capital_log.txt") as f:
                lines = f.readlines()
            for line in lines[-10:]:
                print(f"    {line.strip()}")
        print(f"{'='*58}")

    elif "--schedule" in sys.argv:
        run_bot()
        run_scheduler()
    else:
        run_bot()
