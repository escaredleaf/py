"""
QuantScalpBot - Telegram 기반 한국 단타 퀀트 봇
curl -fsSL https://raw.githubusercontent.com/escaredleaf/py/main/run.py | python3
"""

import os
import sys
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from urllib.parse import quote

import requests
import pandas as pd
from bs4 import BeautifulSoup
from telegram import Update
from telegram.ext import Application, ContextTypes, CommandHandler, MessageHandler, filters

# ── 설정 ──────────────────────────────────────────────────────────────

TOKEN = os.environ.get(
    "TELEGRAM_TOKEN",
    "8751027463:AAEt_Xg7nR0AAVJyXYkyUgkt6BXFbC_x28o",
)

DB_PATH = "quant_scalp.db"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 13; Pixel 7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Mobile Safari/537.36"
    )
}

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.WARNING,
)

# ── DB ────────────────────────────────────────────────────────────────

def init_db():
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tracked_stocks (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                name      TEXT NOT NULL,
                code      TEXT,
                buy_price REAL NOT NULL,
                buy_time  TEXT NOT NULL,
                status    TEXT DEFAULT 'active'
            )
        """)
        conn.commit()


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def set_setting(key: str, value: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (key, value)
        )
        conn.commit()


def get_setting(key: str) -> str | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else None


def add_tracked_stock(name: str, code: str, buy_price: float):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO tracked_stocks (name, code, buy_price, buy_time) VALUES (?, ?, ?, ?)",
            (name, code, buy_price, datetime.now().isoformat())
        )
        conn.commit()


def get_active_stocks() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM tracked_stocks WHERE status = 'active'"
        ).fetchall()
        return [dict(r) for r in rows]


def close_stock(code: str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE tracked_stocks SET status = 'closed' WHERE code = ? AND status = 'active'",
            (code,)
        )
        conn.commit()


def get_stock_record(code: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM tracked_stocks WHERE code = ? ORDER BY id DESC LIMIT 1",
            (code,)
        ).fetchone()
        return dict(row) if row else None


# ── 데이터 수집 ───────────────────────────────────────────────────────

def scrape_top_stocks(limit: int = 40) -> list[dict]:
    """거래대금 상위 종목 스크래핑 (KOSPI + KOSDAQ)"""
    stocks = []
    for sosok in [0, 1]:
        url = f"https://finance.naver.com/sise/sise_quant.nhn?sosok={sosok}"
        try:
            res = requests.get(url, headers=HEADERS, timeout=10)
            res.encoding = "euc-kr"
            soup = BeautifulSoup(res.text, "lxml")
            table = soup.select_one("table.type_2")
            if not table:
                continue
            for row in table.select("tr"):
                cols = row.select("td")
                if len(cols) < 7:
                    continue
                try:
                    name_tag = cols[1].select_one("a")
                    if not name_tag:
                        continue
                    name = name_tag.text.strip()
                    href = name_tag.get("href", "")
                    code = href.split("code=")[-1] if "code=" in href else ""

                    price_text = cols[2].text.strip().replace(",", "")
                    rate_text  = cols[4].text.strip().replace("%", "").replace("+", "").strip()
                    vol_text   = cols[5].text.strip().replace(",", "")

                    if not price_text.lstrip("-").isdigit():
                        continue

                    price = int(price_text)
                    if not (2_000 <= price <= 30_000):
                        continue

                    stocks.append({
                        "name": name,
                        "code": code,
                        "price": price,
                        "change_rate": float(rate_text) if rate_text else 0.0,
                        "volume": int(vol_text) if vol_text.isdigit() else 0,
                        "market": "KOSPI" if sosok == 0 else "KOSDAQ",
                    })
                except (ValueError, IndexError):
                    continue
        except Exception as e:
            print(f"[collector] scrape_top_stocks error: {e}")
    return stocks[:limit]


def get_stock_info(code: str) -> dict | None:
    """네이버 모바일 API로 현재가 조회"""
    url = f"https://m.stock.naver.com/api/stock/{code}/basic"
    try:
        d = requests.get(url, headers=HEADERS, timeout=8).json()
        def _int(v): return int(str(v).replace(",", "")) if v else 0
        return {
            "code":   code,
            "price":  _int(d.get("closePrice")),
            "volume": _int(d.get("accumulatedTradingVolume")),
            "high":   _int(d.get("highPrice")),
            "low":    _int(d.get("lowPrice")),
            "open":   _int(d.get("openPrice")),
        }
    except Exception as e:
        print(f"[collector] get_stock_info error ({code}): {e}")
        return None


def get_candles(code: str, count: int = 80) -> list[dict]:
    """네이버 fchart API로 1분봉 조회"""
    url = (
        f"https://fchart.stock.naver.com/sise.nhn"
        f"?symbol={code}&timeframe=minute&count={count}&requestType=0"
    )
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(res.text, "lxml-xml")
        candles = []
        for item in soup.select("item"):
            parts = item.get("data", "").split("|")
            if len(parts) < 6:
                continue
            try:
                candles.append({
                    "time":   parts[0],
                    "open":   int(parts[1]),
                    "high":   int(parts[2]),
                    "low":    int(parts[3]),
                    "close":  int(parts[4]),
                    "volume": int(parts[5]),
                })
            except ValueError:
                continue
        return candles
    except Exception as e:
        print(f"[collector] get_candles error ({code}): {e}")
        return []


def get_name_by_code(code: str) -> str:
    """종목코드로 종목명 조회"""
    url = f"https://m.stock.naver.com/api/stock/{code}/basic"
    try:
        d = requests.get(url, headers=HEADERS, timeout=8).json()
        return d.get("stockName", code)
    except Exception:
        return code


# ── 매수 점수 계산 ────────────────────────────────────────────────────

def calculate_buy_score(stock: dict, candles: list) -> dict:
    """
    매수 추천 점수 (0~100)
      1. 거래량 급증   (20점)
      2. 가격 가속도   (20점)
      3. 거래량 가속도 (20점)
      4. 눌림목 돌파   (20점)
      5. 등락률 적정   (20점)
    """
    score = 0
    reasons: list[str] = []

    if len(candles) < 15:
        return {"score": 0, "reasons": ["데이터 부족"]}

    price = stock.get("price", 0)
    if not (2_000 <= price <= 30_000):
        return {"score": 0, "reasons": ["가격 범위 제외"]}

    df = pd.DataFrame(candles)

    # 1. 거래량 급증
    recent_vol = df["volume"].iloc[-5:].mean()
    prev_vol   = df["volume"].iloc[-15:-5].mean()
    if prev_vol > 0:
        ratio = recent_vol / prev_vol
        if ratio >= 3.0:
            score += 20; reasons.append(f"거래량 {ratio:.1f}배 급증")
        elif ratio >= 2.0:
            score += 12; reasons.append(f"거래량 {ratio:.1f}배 증가")
        elif ratio >= 1.5:
            score += 6

    # 2. 가격 가속도
    if len(df) >= 6:
        c0, c3, c6 = df["close"].iloc[-6], df["close"].iloc[-3], df["close"].iloc[-1]
        mom_now  = (c6 - c3) / c3 * 100 if c3 > 0 else 0
        mom_prev = (c3 - c0) / c0 * 100 if c0 > 0 else 0
        if mom_now > mom_prev and mom_now > 0.5:
            score += 20; reasons.append(f"가격 가속 +{mom_now:.1f}%")
        elif mom_now > 0.3:
            score += 10; reasons.append(f"상승 중 +{mom_now:.1f}%")

    # 3. 거래량 가속도 (3봉 연속)
    if len(df) >= 3:
        v = df["volume"].iloc[-3:].tolist()
        if v[2] > v[1] > v[0]:
            score += 20; reasons.append("거래량 3봉 연속 증가")
        elif v[2] > v[1]:
            score += 8

    # 4. 눌림목 후 돌파
    if len(df) >= 10:
        recent_high = df["high"].iloc[-10:-3].max()
        current     = df["close"].iloc[-1]
        if recent_high > 0:
            if current >= recent_high * 0.998:
                score += 20; reasons.append("전고점 돌파")
            elif current >= recent_high * 0.990:
                score += 10; reasons.append("전고점 근접")

    # 5. 당일 등락률 2~8%
    rate = stock.get("change_rate", 0)
    if 2.0 <= rate <= 8.0:
        score += 20; reasons.append(f"등락 +{rate:.1f}%")
    elif 1.0 <= rate < 2.0:
        score += 8
    elif rate > 8.0:
        score -= 10; reasons.append("과열 주의")

    return {"score": min(100, max(0, score)), "reasons": reasons}


# ── 매도 점수 계산 ────────────────────────────────────────────────────

def _vwap(candles: list) -> float:
    tv  = sum(c["close"] * c["volume"] for c in candles)
    vol = sum(c["volume"] for c in candles)
    return tv / vol if vol > 0 else 0.0


def calculate_sell_score(stock_info: dict, candles: list, buy_price: float) -> dict:
    """
    매도 신호 점수 (0~100)
      - 손절 -2% / 목표 +5% → 즉시 100점
      1. 연속 고점 하락 (25점)
      2. 거래량 감소    (25점)
      3. VWAP 하회     (25점)
      4. 모멘텀 둔화    (25점)
    """
    score = 0
    reasons: list[str] = []

    if len(candles) < 5:
        return {"score": 0, "reasons": ["데이터 부족"], "pnl": 0.0}

    current = stock_info.get("price", 0)
    if current == 0:
        return {"score": 0, "reasons": ["가격 정보 없음"], "pnl": 0.0}

    pnl = round((current - buy_price) / buy_price * 100, 2)

    if pnl <= -2.0:
        return {"score": 100, "reasons": [f"손절 기준 도달 ({pnl:.1f}%)"], "pnl": pnl}
    if pnl >= 5.0:
        return {"score": 100, "reasons": [f"목표 수익 달성 ({pnl:.1f}%)"], "pnl": pnl}

    df = pd.DataFrame(candles)

    # 1. 연속 고점 하락
    if len(df) >= 3:
        h = df["high"].iloc[-3:].tolist()
        if h[2] < h[1] < h[0]:
            score += 25; reasons.append("3봉 연속 고점 하락")
        elif h[2] < h[1]:
            score += 10

    # 2. 거래량 감소
    if len(df) >= 6:
        peak_vol   = df["volume"].iloc[-6:].max()
        recent_avg = df["volume"].iloc[-3:].mean()
        if peak_vol > 0:
            decay = (peak_vol - recent_avg) / peak_vol
            if decay >= 0.5:
                score += 25; reasons.append(f"거래량 {decay*100:.0f}% 급감")
            elif decay >= 0.3:
                score += 12

    # 3. VWAP 하회
    vwap = _vwap(candles[-30:] if len(candles) >= 30 else candles)
    if vwap > 0 and current < vwap:
        score += 25; reasons.append(f"VWAP({vwap:,.0f}) 하회")

    # 4. 모멘텀 둔화
    if len(df) >= 6:
        c = df["close"]
        mom_now  = (c.iloc[-1] - c.iloc[-3]) / c.iloc[-3] * 100 if c.iloc[-3] > 0 else 0
        mom_prev = (c.iloc[-3] - c.iloc[-6]) / c.iloc[-6] * 100 if c.iloc[-6] > 0 else 0
        if mom_now < 0 and mom_prev > 0:
            score += 25; reasons.append("모멘텀 반전")
        elif mom_now < mom_prev:
            score += 10; reasons.append("모멘텀 둔화")

    return {
        "score": min(100, max(0, score)),
        "reasons": reasons,
        "pnl": pnl,
        "vwap": round(vwap),
    }


# ── 텔레그램 명령어 ───────────────────────────────────────────────────

HELP_TEXT = (
    "📈 *QuantScalpBot* 명령어\n"
    "─────────────────────\n"
    "텍스트로 입력하세요 (/ 없이):\n\n"
    "`추천` - 매수 추천 종목 TOP 5\n"
    "`매수 종목코드 매수가` - 매수 등록 및 모니터링\n"
    "`상태` - 전체 추적 종목 현황\n"
    "`상태 종목코드` - 특정 종목 상세 현황\n"
    "`종료 종목코드` - 종목 추적 중단\n"
    "`도움말` - 이 메시지\n\n"
    "예시: `매수 005930 71200`  (삼성전자)"
)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    set_setting("chat_id", str(update.effective_chat.id))
    await update.message.reply_text(
        f"✅ QuantScalpBot 시작!\n\n{HELP_TEXT}", parse_mode="Markdown"
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_TEXT, parse_mode="Markdown")


async def cmd_recommend(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📊 종목 스캔 중... (20~30초 소요)")
    try:
        results = []
        for stock in scrape_top_stocks(limit=40):
            code = stock.get("code")
            if not code:
                continue
            sd = calculate_buy_score(stock, get_candles(code, count=80))
            if sd["score"] >= 80:
                results.append({**stock, **sd})

        results.sort(key=lambda x: x["score"], reverse=True)
        top5 = results[:5]

        if not top5:
            await update.message.reply_text("⚠️ 현재 조건(80점↑)을 만족하는 종목이 없습니다.")
            return

        lines = ["🔥 *매수 추천 TOP 5*\n" + "─" * 22]
        for i, s in enumerate(top5, 1):
            lines.append(
                f"{i}. *{s['name']}* ({s['market']})\n"
                f"   현재가 {s['price']:,}원  등락 {s['change_rate']:+.1f}%\n"
                f"   점수 {s['score']}점 | {', '.join(s['reasons'])}"
            )
        await update.message.reply_text("\n\n".join(lines), parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"오류: {e}")


async def cmd_buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("사용법: 매수 종목코드 매수가\n예: 매수 005930 71200")
        return
    code = args[0].strip()
    try:
        buy_price = float(args[1].replace(",", ""))
    except ValueError:
        await update.message.reply_text("매수가를 숫자로 입력해주세요.")
        return

    name = get_name_by_code(code)
    add_tracked_stock(name, code, buy_price)
    await update.message.reply_text(
        f"✅ *매수 등록 완료*\n"
        f"종목: {name} ({code})\n"
        f"매수가: {buy_price:,.0f}원\n"
        f"15초마다 매도 신호 모니터링 시작",
        parse_mode="Markdown",
    )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        stocks = get_active_stocks()
        if not stocks:
            await update.message.reply_text("현재 추적 중인 종목이 없습니다.")
            return
        lines = ["📋 *추적 중인 종목*\n" + "─" * 20]
        for s in stocks:
            lines.append(f"• {s['name']}  매수가 {s['buy_price']:,.0f}원")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
        return

    code = args[0].strip()
    record = get_stock_record(code)
    if not record:
        await update.message.reply_text(f"'{code}' 을(를) 찾을 수 없습니다.")
        return

    name = record.get("name", code)

    info = get_stock_info(code)
    if not info:
        await update.message.reply_text(f"{name}: 현재가 조회 실패")
        return

    sd  = calculate_sell_score(info, get_candles(code, count=80), record["buy_price"])
    pnl = sd["pnl"]
    await update.message.reply_text(
        f"📌 *{name}* 상태\n"
        f"매수가: {record['buy_price']:,.0f}원\n"
        f"현재가: {info['price']:,.0f}원\n"
        f"{'📈' if pnl >= 0 else '📉'} 수익률: {pnl:+.2f}%\n"
        f"VWAP: {sd.get('vwap', 0):,.0f}원\n"
        f"매도 점수: {sd['score']}점\n"
        f"신호: {', '.join(sd['reasons']) or '없음'}",
        parse_mode="Markdown",
    )


async def cmd_close(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text("사용법: 종료 종목코드\n예: 종료 005930")
        return
    code = args[0].strip()
    name = get_name_by_code(code)
    close_stock(code)
    await update.message.reply_text(f"🛑 {name} ({code}) 추적을 종료했습니다.")


async def message_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """한글 텍스트 메시지를 명령어로 라우팅"""
    text = update.message.text.strip()
    parts = text.split()
    keyword = parts[0] if parts else ""

    if keyword == "추천":
        await cmd_recommend(update, context)
    elif keyword == "매수":
        context.args = parts[1:]
        await cmd_buy(update, context)
    elif keyword == "상태":
        context.args = parts[1:]
        await cmd_status(update, context)
    elif keyword == "종료":
        context.args = parts[1:]
        await cmd_close(update, context)
    elif keyword == "도움말":
        await cmd_help(update, context)
    else:
        await update.message.reply_text(HELP_TEXT, parse_mode="Markdown")


# ── 주기 작업 (15초) ──────────────────────────────────────────────────

async def track_job(context: ContextTypes.DEFAULT_TYPE):
    """보유 종목 매도 신호 감시"""
    chat_id = get_setting("chat_id")
    if not chat_id:
        return
    for stock in get_active_stocks():
        code = stock.get("code")
        if not code:
            continue
        try:
            info = get_stock_info(code)
            if not info:
                continue
            sd = calculate_sell_score(info, get_candles(code, count=80), stock["buy_price"])
            if sd["score"] >= 60:
                await context.bot.send_message(
                    chat_id=int(chat_id),
                    text=(
                        f"⚠️ *매도 신호* {stock['name']}  (점수: {sd['score']})\n"
                        f"현재가: {info['price']:,.0f}원  수익률: {sd['pnl']:+.2f}%\n"
                        f"사유: {', '.join(sd['reasons'])}"
                    ),
                    parse_mode="Markdown",
                )
        except Exception as e:
            print(f"[track_job] {stock['name']} 오류: {e}")

async def health_job(context: ContextTypes.DEFAULT_TYPE):
    """5분마다 네이버 연동 상태 체크 - 이상 시에만 알림"""
    chat_id = get_setting("chat_id")
    if not chat_id:
        return

    errors = []

    # 네이버 금융 거래대금 페이지 연결 확인
    try:
        res = requests.get(
            "https://finance.naver.com/sise/sise_quant.nhn?sosok=0",
            headers=HEADERS, timeout=8
        )
        if res.status_code != 200:
            errors.append(f"네이버 금융: HTTP {res.status_code}")
    except Exception as e:
        errors.append(f"네이버 금융: 연결 실패 ({e})")

    # 네이버 모바일 API 확인 (삼성전자 005930)
    try:
        res = requests.get(
            "https://m.stock.naver.com/api/stock/005930/basic",
            headers=HEADERS, timeout=8
        )
        if res.status_code != 200:
            errors.append(f"네이버 API: HTTP {res.status_code}")
    except Exception as e:
        errors.append(f"네이버 API: 연결 실패 ({e})")

    # DB 확인
    try:
        get_active_stocks()
    except Exception as e:
        errors.append(f"DB: 오류 ({e})")

    if errors:
        await context.bot.send_message(
            chat_id=int(chat_id),
            text="🚨 *헬스체크 이상 감지*\n" + "\n".join(f"• {e}" for e in errors),
            parse_mode="Markdown",
        )



def main():
    init_db()
    print("✅ DB 초기화 완료")

    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help",  cmd_help))
    # 한글 명령어는 텍스트 메시지로 처리 (텔레그램은 영문 명령어만 허용)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_router))

    app.job_queue.run_repeating(track_job,  interval=15,  first=15)
    app.job_queue.run_repeating(health_job, interval=300, first=60)

    print("🚀 QuantScalpBot 가동 중 (Ctrl+C 로 종료)")
    app.run_polling(allowed_updates=["message"])


if __name__ == "__main__":
    main()
