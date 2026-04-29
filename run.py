"""
QuantScalpBot - Telegram 기반 한국 단타 퀀트 봇
curl -fsSL https://raw.githubusercontent.com/escaredleaf/py/main/run.py | python3
"""

import os
import sys
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))

def now_kst() -> datetime:
    return datetime.now(KST)
from urllib.parse import quote

import asyncio

import requests
import pandas as pd
from bs4 import BeautifulSoup
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, ContextTypes, CommandHandler, MessageHandler, filters

# ── 설정 ──────────────────────────────────────────────────────────────

TOKEN = os.environ.get(
    "TELEGRAM_TOKEN",
    "8751027463:AAEt_Xg7nR0AAVJyXYkyUgkt6BXFbC_x28o",
)

LLM_URL   = "https://api.platform.a15t.com/v1/chat/completions"
LLM_MODEL = "openai/gpt-5-mini-2025-08-07"
LLM_KEY   = os.environ.get("LLM_KEY", "sk-gapk-6z3jLdHWOoztTgupT9OgLA3fU-QcKSY1")

DB_PATH = "quant_scalp.db"
LLM_TIMEOUT_SECONDS = 90
LLM_MAX_ATTEMPTS = 2
DEFAULT_MONITOR_INTERVAL_SECONDS = 15
MIN_MONITOR_INTERVAL_SECONDS = 5
MAX_MONITOR_INTERVAL_SECONDS = 24 * 60 * 60
MONITOR_INTERVAL_SETTING_KEY = "monitor_interval_seconds"
NOTIFICATION_ENABLED_SETTING_KEY = "notification_enabled"
TRACK_JOB_NAME = "track_job"
NOTIFICATION_JOB_NAME = "health_job"
SELL_SCAN_INTERVAL_SECONDS = 15

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

# ── LLM ──────────────────────────────────────────────────────────────

def _llm_call(system: str, user: str, max_tokens: int = 1000) -> str:
    """동기 LLM 호출 (requests)"""
    payload = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "user", "content": f"{system}\n\n{user}"},
        ],
        "max_completion_tokens": max_tokens,
    }

    last_error = None
    for attempt in range(1, LLM_MAX_ATTEMPTS + 1):
        try:
            res = requests.post(
                LLM_URL,
                headers={"Authorization": f"Bearer {LLM_KEY}", "Content-Type": "application/json"},
                json=payload,
                timeout=(10, LLM_TIMEOUT_SECONDS),
            )
            data = res.json()
            if "choices" not in data:
                err = data.get("error", {})
                msg = err.get("message", str(data))
                print(f"[LLM] 오류 응답: {msg}")
                return f"⚠️ LLM 오류\n{msg}"
            choice = data["choices"][0]
            content = choice.get("message", {}).get("content") or ""
            refusal = choice.get("message", {}).get("refusal") or ""
            if not content and refusal:
                print(f"[LLM] 거부 응답: {refusal}")
                return f"⚠️ {refusal}"
            if not content:
                print(f"[LLM] 빈 응답. finish_reason={choice.get('finish_reason')} full={data}")
            return content.strip()
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            last_error = e
            print(f"[LLM] 네트워크 오류 {attempt}/{LLM_MAX_ATTEMPTS}: {e}")
            continue
        except Exception as e:
            print(f"[LLM] 오류: {e}")
            return f"⚠️ LLM 오류\n{e}"

    return "⚠️ LLM 응답이 지연되고 있습니다. 잠시 후 다시 시도해주세요."


async def llm(system: str, user: str, max_tokens: int = 1000) -> str:
    """비동기 래퍼 - 이벤트 루프 블로킹 방지"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _llm_call, system, user, max_tokens)


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
            (name, code, buy_price, now_kst().isoformat())
        )
        conn.commit()


def get_active_stocks() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM tracked_stocks WHERE status = 'active' ORDER BY id"
        ).fetchall()
        return [dict(r) for r in rows]


def close_stock(code: str) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE tracked_stocks SET status = 'closed' WHERE code = ? AND status = 'active'",
            (code,)
        )
        conn.commit()
        return cur.rowcount


def close_stock_by_id(stock_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM tracked_stocks WHERE id = ? AND status = 'active'",
            (stock_id,),
        ).fetchone()
        if not row:
            return None
        conn.execute(
            "UPDATE tracked_stocks SET status = 'closed' WHERE id = ? AND status = 'active'",
            (stock_id,),
        )
        conn.commit()
        return dict(row)


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
                    if price < 500:  # 너무 낮은 동전주만 제외
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


def is_market_open() -> bool:
    """한국 주식 장중 여부 (평일 09:00~15:30)"""
    now = now_kst()
    if now.weekday() >= 5:
        return False
    minutes = now.hour * 60 + now.minute
    return 9 * 60 <= minutes <= 15 * 60 + 30


def _parse_candles(xml_text: str) -> list[dict]:
    """fchart API XML → 캔들 리스트"""
    soup = BeautifulSoup(xml_text, "lxml-xml")
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


def get_candles(code: str, count: int = 80) -> list[dict]:
    """네이버 fchart API로 1분봉 조회"""
    url = (
        f"https://fchart.stock.naver.com/sise.nhn"
        f"?symbol={code}&timeframe=minute&count={count}&requestType=0"
    )
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        return _parse_candles(res.text)
    except Exception as e:
        print(f"[collector] get_candles error ({code}): {e}")
        return []


def get_daily_candles(code: str, count: int = 30) -> list[dict]:
    """네이버 fchart API로 일봉 조회 (장 외 시간용)"""
    url = (
        f"https://fchart.stock.naver.com/sise.nhn"
        f"?symbol={code}&timeframe=day&count={count}&requestType=0"
    )
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        return _parse_candles(res.text)
    except Exception as e:
        print(f"[collector] get_daily_candles error ({code}): {e}")
        return []


def normalize_stock_code(code: str) -> str | None:
    """6자리 숫자 종목코드만 허용"""
    code = code.strip()
    return code if code.isdigit() and len(code) == 6 else None


def lookup_stock_by_code(code: str) -> dict | None:
    """종목코드 유효성 확인 후 종목명 반환"""
    code = normalize_stock_code(code)
    if not code:
        return None

    url = f"https://m.stock.naver.com/api/stock/{code}/basic"
    try:
        d = requests.get(url, headers=HEADERS, timeout=8).json()
        name = (d.get("stockName") or "").strip()
        if not name or name == code:
            return None
        return {"code": code, "name": name}
    except Exception as e:
        print(f"[collector] lookup_stock_by_code error ({code}): {e}")
        return None


def get_name_by_code(code: str) -> str:
    """종목코드로 종목명 조회"""
    stock = lookup_stock_by_code(code)
    return stock["name"] if stock else code


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

    if len(candles) < 10:
        return {"score": 0, "reasons": ["데이터 부족"]}

    price = stock.get("price", 0)
    if price < 500:
        return {"score": 0, "reasons": ["동전주 제외"]}

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

def calculate_new_score(stock: dict, candles: list) -> dict:
    """
    신규 모멘텀 점수 (0~100) - 방금 막 움직이기 시작한 종목 탐색
      1. 직전까지 거래량 평탄 → 최근 3봉 폭발 (35점)
      2. 최근 3봉 연속 양봉    (35점)
      3. 등락률 0.5~5% 초기 구간 (30점)
    """
    score = 0
    reasons: list[str] = []

    if len(candles) < 10:
        return {"score": 0, "reasons": ["데이터 부족"]}

    price = stock.get("price", 0)
    if price < 500:
        return {"score": 0, "reasons": ["동전주 제외"]}

    df = pd.DataFrame(candles)

    # 1. 직전 평탄 → 최근 폭발 (신규성 핵심)
    flat_vol  = df["volume"].iloc[-20:-3].mean()
    burst_vol = df["volume"].iloc[-3:].mean()
    if flat_vol > 0:
        ratio = burst_vol / flat_vol
        if ratio >= 5.0:
            score += 35; reasons.append(f"거래량 {ratio:.0f}배 폭발 신규")
        elif ratio >= 3.0:
            score += 20; reasons.append(f"거래량 {ratio:.0f}배 급등 신규")
        elif ratio >= 2.0:
            score += 10

    # 2. 최근 3봉 연속 양봉 (시작 신호)
    if len(df) >= 3:
        last3 = df.iloc[-3:]
        if all(last3["close"].values[i] > last3["open"].values[i] for i in range(3)):
            score += 35; reasons.append("3봉 연속 양봉")
        elif last3["close"].iloc[-1] > last3["open"].iloc[-1]:
            score += 15

    # 3. 등락률 초기 구간 0.5~5% (과열 전)
    rate = stock.get("change_rate", 0)
    if 0.5 <= rate <= 5.0:
        score += 30; reasons.append(f"초기 상승 +{rate:.1f}%")
    elif rate > 5.0:
        score -= 10; reasons.append("이미 급등")

    return {"score": min(100, max(0, score)), "reasons": reasons}


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


# ── 텔레그램 UI ───────────────────────────────────────────────────────

# 인자가 필요한 명령어 대기 상태 (chat_id -> {"action": ..., ...})
_pending: dict[str, dict] = {}

MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [
        [KeyboardButton("AI추천"),   KeyboardButton("종목등록")],
        [KeyboardButton("현재상황"), KeyboardButton("종목분석")],
        [KeyboardButton("종목삭제"), KeyboardButton("설정")],
        [KeyboardButton("메시지 알림받기"), KeyboardButton("메시지 알림중지")],
        [KeyboardButton("도움말")],
    ],
    resize_keyboard=True,
)

CONFIRM_KEYBOARD = ReplyKeyboardMarkup(
    [[KeyboardButton("등록확인"), KeyboardButton("취소")]],
    resize_keyboard=True,
    one_time_keyboard=True,
)

HELP_TEXT = (
    "📈 *QuantScalpBot* 명령어\n"
    "─────────────────────\n"
    "텍스트로 입력하세요 (/ 없이):\n\n"
    "`AI추천` - 모멘텀 강한 종목 + 신규 모멘텀 종목 TOP 5\n"
    "`종목등록` - 종목코드와 매수금액을 단계별 입력 후 등록\n"
    "`현재상황` - 전체 추적 종목 현황\n"
    "`현재상황 종목코드` - 특정 종목 상세 현황\n"
    "`종목삭제 종목코드` - 종목 추적 중단\n"
    "`종목분석 종목명또는코드` - IB 스타일 심층 분석\n"
    "`설정` - 메시지 알림간격 변경\n"
    "`메시지 알림받기` - 자동 헬스체크/보유종목 메시지 시작\n"
    "`메시지 알림중지` - 자동 헬스체크/보유종목 메시지 중지\n"
    "`도움말` - 이 메시지\n\n"
    "예시: `종목등록 005930 71200`  (삼성전자)\n"
    "예시: `종목분석 삼성전자`\n"
    "예시: `설정` → `30초` 또는 `5분`"
)

LEGACY_BUTTONS = {"추천", "매수", "상태", "종료"}
BUTTON_KEYWORDS = {
    "AI추천",
    "추천",
    "신규추천",
    "종목등록",
    "매수",
    "현재상황",
    "상태",
    "종목삭제",
    "종료",
    "종목분석",
    "도움말",
    "설정",
    "메시지 알림받기",
    "메시지 알림중지",
}


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    set_setting("chat_id", str(update.effective_chat.id))
    await update.message.reply_text(
        "✅ *QuantScalpBot 시작!*\n아래 버튼을 눌러 사용하세요.",
        parse_mode="Markdown",
        reply_markup=MAIN_KEYBOARD,
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        HELP_TEXT, parse_mode="Markdown", reply_markup=MAIN_KEYBOARD
    )


async def cmd_recommend(update: Update, context: ContextTypes.DEFAULT_TYPE):
    market_open = is_market_open()
    label_time  = "장중" if market_open else "장 외(전일 일봉 기준)"
    await update.message.reply_text(f"📊 종목 스캔 중... [{label_time}]")
    try:
        threshold = 80 if market_open else 55
        results = []
        for stock in scrape_top_stocks(limit=40):
            code = stock.get("code")
            if not code:
                continue
            candles = get_candles(code, count=80) if market_open else get_daily_candles(code, count=30)
            sd = calculate_buy_score(stock, candles)
            if sd["score"] >= threshold:
                results.append({**stock, **sd})

        results.sort(key=lambda x: x["score"], reverse=True)
        top5 = results[:5]

        if not top5:
            await update.message.reply_text(f"⚠️ 현재 조건({threshold}점↑)을 만족하는 종목이 없습니다.")
            return

        lines = ["🔥 *매수 추천 TOP 5*\n" + "─" * 22]
        for i, s in enumerate(top5, 1):
            lines.append(
                f"{i}. *{s['name']}* ({s['market']})\n"
                f"   현재가 {s['price']:,}원  등락 {s['change_rate']:+.1f}%\n"
                f"   점수 {s['score']}점 | {', '.join(s['reasons'])}"
            )
        await update.message.reply_text("\n\n".join(lines), parse_mode="Markdown")

        # LLM 종합 분석
        stock_summary = "\n".join(
            f"- {s['name']}({s['market']}): 현재가 {s['price']:,}원, "
            f"등락 {s['change_rate']:+.1f}%, 사유: {', '.join(s['reasons'])}"
            for s in top5
        )
        commentary = await llm(
            "당신은 한국 주식 단타 전문가입니다. 간결하고 핵심만 답하세요.",
            f"다음 종목들이 단타 추천됐습니다. 시장 맥락과 주의사항을 2~3문장으로 분석해주세요:\n{stock_summary}",
            max_tokens=800,
        )
        if commentary:
            await update.message.reply_text(f"🤖 *AI 분석*\n{commentary}", parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"오류: {e}")


async def cmd_buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 2:
        await start_stock_registration(update)
        return

    stock = lookup_stock_by_code(args[0])
    if not stock:
        await update.message.reply_text(
            "❌ 유효한 종목코드를 찾을 수 없어 입력 내용을 삭제했습니다.\n"
            "`종목등록`을 다시 눌러 6자리 종목코드를 입력해주세요.",
            parse_mode="Markdown",
            reply_markup=MAIN_KEYBOARD,
        )
        return

    try:
        buy_price = float(args[1].replace(",", ""))
    except ValueError:
        await update.message.reply_text("매수가를 숫자로 입력해주세요.")
        return
    if buy_price <= 0:
        await update.message.reply_text("매수금액은 0보다 큰 숫자로 입력해주세요.")
        return

    await ask_stock_registration_confirm(
        update,
        str(update.effective_chat.id),
        stock["code"],
        stock["name"],
        buy_price,
    )


async def start_stock_registration(update: Update):
    cid = str(update.effective_chat.id)
    _pending[cid] = {"action": "buy_code"}
    await update.message.reply_text(
        "📌 등록할 *종목코드*를 입력하세요.\n예: `005930`",
        parse_mode="Markdown",
    )


async def ask_stock_registration_confirm(
    update: Update,
    cid: str,
    code: str,
    name: str,
    buy_price: float,
):
    _pending[cid] = {
        "action": "buy_confirm",
        "code": code,
        "name": name,
        "buy_price": buy_price,
    }
    await update.message.reply_text(
        "✅ 종목코드가 확인되었습니다.\n\n"
        f"종목명: *{name}*\n"
        f"종목코드: `{code}`\n"
        f"매수금액: `{buy_price:,.0f}원`\n\n"
        "위 내용으로 등록할까요?",
        parse_mode="Markdown",
        reply_markup=CONFIRM_KEYBOARD,
    )


async def complete_stock_registration(update: Update, pending: dict):
    code = pending["code"]
    name = pending["name"]
    buy_price = pending["buy_price"]
    add_tracked_stock(name, code, buy_price)
    await update.message.reply_text(
        f"✅ *매수 등록 완료*\n"
        f"종목: {name} ({code})\n"
        f"매수가: {buy_price:,.0f}원\n"
        f"{format_interval(get_monitor_interval_seconds())}마다 매도 신호 모니터링 시작",
        parse_mode="Markdown",
        reply_markup=MAIN_KEYBOARD,
    )


async def handle_pending_stock_registration(
    update: Update,
    text: str,
    parts: list[str],
    pending: dict,
):
    cid = str(update.effective_chat.id)
    action = pending.get("action")

    if action == "buy_code":
        stock = lookup_stock_by_code(text)
        if not stock:
            _pending.pop(cid, None)
            await update.message.reply_text(
                "❌ 유효한 종목코드 또는 종목명을 찾을 수 없어 입력 내용을 삭제했습니다.\n"
                "`종목등록`을 다시 눌러 6자리 종목코드를 입력해주세요.",
                parse_mode="Markdown",
                reply_markup=MAIN_KEYBOARD,
            )
            return
        _pending[cid] = {
            "action": "buy_price",
            "code": stock["code"],
            "name": stock["name"],
        }
        await update.message.reply_text(
            "✅ 종목코드가 확인되었습니다.\n\n"
            f"종목명: *{stock['name']}*\n"
            f"종목코드: `{stock['code']}`\n\n"
            "매수금액을 입력하세요.\n예: `71200`",
            parse_mode="Markdown",
        )
        return

    if action == "buy_price":
        try:
            buy_price = float(parts[0].replace(",", ""))
        except (IndexError, ValueError):
            _pending[cid] = pending
            await update.message.reply_text("매수금액을 숫자로 입력해주세요.\n예: `71200`", parse_mode="Markdown")
            return
        if buy_price <= 0:
            _pending[cid] = pending
            await update.message.reply_text("매수금액은 0보다 큰 숫자로 입력해주세요.")
            return
        await ask_stock_registration_confirm(
            update,
            cid,
            pending["code"],
            pending["name"],
            buy_price,
        )
        return

    if action == "buy_confirm":
        if text in {"등록확인", "확인", "예", "네", "yes", "y", "Y"}:
            await complete_stock_registration(update, pending)
            return
        if text in {"취소", "아니오", "아니요", "no", "n", "N"}:
            await update.message.reply_text("등록을 취소하고 입력 내용을 삭제했습니다.", reply_markup=MAIN_KEYBOARD)
            return
        _pending[cid] = pending
        await update.message.reply_text(
            "`등록확인` 또는 `취소`를 선택해주세요.",
            parse_mode="Markdown",
            reply_markup=CONFIRM_KEYBOARD,
        )


def parse_monitor_interval(text: str) -> int | None:
    value = text.strip().lower().replace(" ", "")
    if not value:
        return None

    multiplier = 1
    for suffix, unit_multiplier in (
        ("seconds", 1),
        ("second", 1),
        ("secs", 1),
        ("sec", 1),
        ("s", 1),
        ("초", 1),
        ("minutes", 60),
        ("minute", 60),
        ("mins", 60),
        ("min", 60),
        ("m", 60),
        ("분", 60),
        ("hours", 3600),
        ("hour", 3600),
        ("hrs", 3600),
        ("hr", 3600),
        ("h", 3600),
        ("시간", 3600),
    ):
        if value.endswith(suffix):
            value = value[:-len(suffix)]
            multiplier = unit_multiplier
            break

    try:
        seconds = int(float(value) * multiplier)
    except ValueError:
        return None

    if not (MIN_MONITOR_INTERVAL_SECONDS <= seconds <= MAX_MONITOR_INTERVAL_SECONDS):
        return None
    return seconds


def get_monitor_interval_seconds() -> int:
    raw = get_setting(MONITOR_INTERVAL_SETTING_KEY)
    if not raw:
        return DEFAULT_MONITOR_INTERVAL_SECONDS
    try:
        seconds = int(raw)
    except ValueError:
        return DEFAULT_MONITOR_INTERVAL_SECONDS
    if not (MIN_MONITOR_INTERVAL_SECONDS <= seconds <= MAX_MONITOR_INTERVAL_SECONDS):
        return DEFAULT_MONITOR_INTERVAL_SECONDS
    return seconds


def format_interval(seconds: int) -> str:
    if seconds % 3600 == 0:
        return f"{seconds // 3600}시간"
    if seconds % 60 == 0:
        return f"{seconds // 60}분"
    return f"{seconds}초"


def is_notification_enabled() -> bool:
    return get_setting(NOTIFICATION_ENABLED_SETTING_KEY) != "0"


def set_notification_enabled(enabled: bool):
    set_setting(NOTIFICATION_ENABLED_SETTING_KEY, "1" if enabled else "0")


def schedule_named_job(
    job_queue,
    name: str,
    callback,
    interval: int,
    job_kwargs: dict | None = None,
    first: int | None = None,
):
    for job in job_queue.get_jobs_by_name(name):
        job.schedule_removal()
    job_queue.run_repeating(
        callback,
        interval=interval,
        first=first if first is not None else interval,
        name=name,
        job_kwargs=job_kwargs,
    )


def schedule_track_job(job_queue, job_kwargs: dict | None = None, first: int | None = None):
    schedule_named_job(
        job_queue,
        TRACK_JOB_NAME,
        track_job,
        SELL_SCAN_INTERVAL_SECONDS,
        job_kwargs,
        first=first,
    )


def schedule_notification_job(job_queue, job_kwargs: dict | None = None, first: int | None = None):
    if not is_notification_enabled():
        for job in job_queue.get_jobs_by_name(NOTIFICATION_JOB_NAME):
            job.schedule_removal()
        return
    interval = get_monitor_interval_seconds()
    schedule_named_job(
        job_queue,
        NOTIFICATION_JOB_NAME,
        health_job,
        interval,
        job_kwargs,
        first=first,
    )


async def cmd_settings(update: Update):
    cid = str(update.effective_chat.id)
    current = get_monitor_interval_seconds()
    notification_status = "ON" if is_notification_enabled() else "OFF"
    _pending[cid] = {"action": "settings_monitor_interval"}
    await update.message.reply_text(
        "⚙️ *설정*\n\n"
        f"현재 메시지 알림: *{notification_status}*\n"
        f"현재 메시지 알림간격: *{format_interval(current)}*\n\n"
        "새 알림간격을 입력하세요.\n"
        "예: `15초`, `1분`, `5m`, `3600`\n"
        f"허용 범위: {format_interval(MIN_MONITOR_INTERVAL_SECONDS)} ~ "
        f"{format_interval(MAX_MONITOR_INTERVAL_SECONDS)}",
        parse_mode="Markdown",
    )


async def handle_monitor_interval_input(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    seconds = parse_monitor_interval(text)
    if seconds is None:
        _pending[str(update.effective_chat.id)] = {"action": "settings_monitor_interval"}
        await update.message.reply_text(
            "알림간격을 숫자와 단위로 입력해주세요.\n"
            "예: `15초`, `1분`, `5m`, `3600`\n"
            f"허용 범위: {format_interval(MIN_MONITOR_INTERVAL_SECONDS)} ~ "
            f"{format_interval(MAX_MONITOR_INTERVAL_SECONDS)}",
            parse_mode="Markdown",
        )
        return

    set_setting(MONITOR_INTERVAL_SETTING_KEY, str(seconds))
    if context.job_queue:
        schedule_notification_job(
            context.job_queue,
            {"misfire_grace_time": 30},
            first=seconds,
        )
    await update.message.reply_text(
        "✅ 메시지 알림간격을 저장했습니다.\n"
        f"새 간격: *{format_interval(seconds)}*",
        parse_mode="Markdown",
        reply_markup=MAIN_KEYBOARD,
    )


async def cmd_notification_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    set_notification_enabled(True)
    interval = get_monitor_interval_seconds()
    if context.job_queue:
        schedule_notification_job(
            context.job_queue,
            {"misfire_grace_time": 30},
            first=interval,
        )
    await update.message.reply_text(
        "🔔 메시지 알림을 시작했습니다.\n"
        f"알림간격: *{format_interval(interval)}*",
        parse_mode="Markdown",
        reply_markup=MAIN_KEYBOARD,
    )


async def cmd_notification_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    set_notification_enabled(False)
    if context.job_queue:
        for job in context.job_queue.get_jobs_by_name(NOTIFICATION_JOB_NAME):
            job.schedule_removal()
    await update.message.reply_text(
        "🔕 메시지 알림을 중지했습니다.\n수동 조회 버튼은 계속 사용할 수 있습니다.",
        reply_markup=MAIN_KEYBOARD,
    )


async def _build_portfolio_lines(active: list) -> list[str]:
    """보유 종목별 상세 현황 라인 생성 (health_job / cmd_status 공용)"""
    lines = []
    stock_lines_for_llm = []

    for stock in active:
        code      = stock.get("code", "")
        buy_price = stock["buy_price"]
        try:
            info  = get_stock_info(code)
            daily = get_daily_candles(code, count=25)
            if not info:
                raise ValueError("가격 조회 실패")

            cur       = info["price"]
            gap       = (cur - buy_price) / buy_price * 100
            gap_emoji = "📈" if gap >= 0 else "📉"
            trend     = _analyze_trend(cur, daily, buy_price, info.get("open", 0))

            chg5 = chg10 = ""
            if len(daily) >= 10:
                closes = [c["close"] for c in daily]
                chg5  = f"{(closes[-1]-closes[-5])/closes[-5]*100:+.1f}%"
                chg10 = f"{(closes[-1]-closes[-min(10,len(closes))])/closes[-min(10,len(closes))]*100:+.1f}%"

            lines.append(
                f"\n*{stock['name']}* ({code})\n"
                f"  매수가: {buy_price:,.0f}원\n"
                f"  현재가: {cur:,.0f}원\n"
                f"  {gap_emoji} 갭: {gap:+.2f}%\n"
                f"  추이: {trend}"
            )
            stock_lines_for_llm.append(
                f"{stock['name']}: 매수가 {buy_price:,.0f}원, "
                f"현재가 {cur:,.0f}원, 수익률 {gap:+.2f}%, "
                f"추이 {trend}, 5일 {chg5 or 'N/A'}, 10일 {chg10 or 'N/A'}"
            )
        except Exception as e:
            print(f"[포트폴리오] {stock['name']} 예외: {type(e).__name__}: {e}")
            lines.append(f"\n*{stock['name']}* ({code}): 조회 실패")

    if stock_lines_for_llm:
        commentary = await llm(
            "당신은 한국 주식 단타 전문가입니다. 간결하게 핵심만 답하세요.",
            "보유 종목 현황입니다. 각 종목별로 추가매수/보유/매도 중 하나를 제시하고, "
            "마지막에 전체 포트폴리오 대응 방향을 2문장으로 요약해주세요. "
            "종목별 답변은 한 줄씩 작성하세요:\n"
            + "\n".join(stock_lines_for_llm),
            max_tokens=1200,
        )
        if commentary:
            lines.append(f"\n🤖 *AI 종합 분석*\n{commentary}")

    return lines


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        active = get_active_stocks()
        if not active:
            await update.message.reply_text("현재 추적 중인 종목이 없습니다.")
            return
        now = now_kst().strftime("%H:%M:%S")
        await update.message.reply_text(f"📋 *보유 종목 현황* `{now}` 조회 중...", parse_mode="Markdown")
        lines = [f"📋 *보유 종목 현황* `{now}`"]
        lines += await _build_portfolio_lines(active)
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


def resolve_stock(query: str) -> tuple[str, str]:
    """종목명 또는 코드 → (name, code) 반환"""
    query = query.strip()
    if query.isdigit() and len(query) == 6:
        return get_name_by_code(query), query
    # 이름으로 검색
    url = (
        f"https://ac.finance.naver.com/ac"
        f"?q={quote(query)}&q_enc=UTF-8&t_aid=stock&st=111"
        f"&r_format=json&r_enc=UTF-8&r_unicode=0&t_koreng=1&r_lt=5"
    )
    try:
        data  = requests.get(url, headers=HEADERS, timeout=8).json()
        items = data.get("items", [[]])[0]
        if items and len(items[0]) > 1:
            return items[0][0], items[0][1]
    except Exception:
        pass
    return query, ""


async def cmd_stock_analysis(update: Update, query: str):
    """IB 스타일 종목 심층 분석"""
    await update.message.reply_text(f"🔬 *{query}* 분석 중... (30~60초 소요)", parse_mode="Markdown")

    name, code = resolve_stock(query)

    # 기초 데이터 수집
    info   = get_stock_info(code) if code else None
    daily  = get_daily_candles(code, count=60) if code else []

    data_block = f"종목명: {name}"
    if code:
        data_block += f" (코드: {code})"
    if info:
        data_block += (
            f"\n현재가: {info['price']:,}원"
            f"\n시가: {info['open']:,}원  고가: {info['high']:,}원  저가: {info['low']:,}원"
            f"\n누적거래량: {info['volume']:,}"
        )
    if len(daily) >= 20:
        closes  = [c["close"] for c in daily]
        ma5     = sum(closes[-5:]) / 5
        ma20    = sum(closes[-20:]) / 20
        chg1m   = (closes[-1] - closes[-20]) / closes[-20] * 100
        chg3m   = (closes[-1] - closes[0])   / closes[0]   * 100
        data_block += (
            f"\nMA5: {ma5:,.0f}원  MA20: {ma20:,.0f}원"
            f"\n1개월 변화율: {chg1m:+.1f}%  3개월 변화율: {chg3m:+.1f}%"
            f"\n52주 고가: {max(c['high'] for c in daily):,}원"
            f"  52주 저가: {min(c['low'] for c in daily):,}원"
        )

    system_prompt = (
        "당신은 투자은행(IB) 애널리스트입니다. "
        "제공된 데이터와 당신의 지식을 바탕으로 IB 스타일의 심층 분석을 수행합니다. "
        "마크다운 없이 plain-text로 작성하고, 표(테이블) 형식은 사용하지 마세요. "
        "한국어로 답변하세요."
    )

    user_prompt = f"""다음 종목을 IB 스타일로 분석해주세요.

[제공 데이터]
{data_block}

[분석 순서 - 반드시 이 순서로]
1. 내러티브 (시장이 현재 가격에 반영한 스토리)
2. Reverse DCF (현재 주가가 암시하는 성장률/마진 역산)
3. Forward DCF (합리적 가정 기반 적정가 추정)
4. 트레이딩 컴프 (주요 밸류에이션 멀티플 해석)
5. 리스크 요인 (Deal Radar: M&A, 규제, 경쟁 등)
6. So What (매수/보유/매도 판단 및 근거)

데이터가 부족한 항목은 [추정] 또는 [데이터 없음]으로 명시하세요."""

    result = await llm(system_prompt, user_prompt, max_tokens=3000)

    if not result:
        await update.message.reply_text("분석 실패: LLM 응답 없음")
        return

    # 텔레그램 4096자 제한 분할 전송
    for i in range(0, len(result), 4000):
        await update.message.reply_text(result[i:i+4000])


def resolve_delete_selection(query: str, active: list[dict]) -> dict | None:
    """번호 또는 종목코드로 삭제할 활성 추적 항목을 선택"""
    query = query.strip()
    if not query:
        return None

    if query.isdigit():
        idx = int(query)
        if 1 <= idx <= len(active):
            return active[idx - 1]

    normalized = normalize_stock_code(query)
    if normalized:
        matches = [s for s in active if s.get("code") == normalized]
        return matches[0] if len(matches) == 1 else None

    return None


def build_delete_keyboard(active: list[dict]) -> ReplyKeyboardMarkup:
    rows = []
    for i in range(0, len(active), 4):
        rows.append([KeyboardButton(str(n)) for n in range(i + 1, min(i + 5, len(active) + 1))])
    rows.append([KeyboardButton("취소")])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True, one_time_keyboard=True)


async def start_stock_delete(update: Update):
    active = get_active_stocks()
    if not active:
        await update.message.reply_text("추적 중인 종목이 없습니다.", reply_markup=MAIN_KEYBOARD)
        return

    cid = str(update.effective_chat.id)
    _pending[cid] = {"action": "close"}
    stock_list = "\n".join(
        f"{i}. {s['name']} ({s['code']}) / 매수가 {s['buy_price']:,.0f}원"
        for i, s in enumerate(active, 1)
    )
    await update.message.reply_text(
        "추적 중단할 종목을 선택하세요.\n"
        "아래 번호 버튼을 누르거나 종목코드를 입력할 수 있습니다.\n\n"
        f"{stock_list}",
        parse_mode="Markdown",
        reply_markup=build_delete_keyboard(active),
    )


async def handle_pending_stock_delete(update: Update, text: str, pending: dict):
    active = get_active_stocks()
    stock = resolve_delete_selection(text, active)
    if not stock:
        _pending[str(update.effective_chat.id)] = pending
        await update.message.reply_text(
            "삭제할 종목을 찾을 수 없습니다. 목록의 번호 버튼을 누르거나 정확한 종목코드를 입력해주세요.",
            reply_markup=build_delete_keyboard(active) if active else MAIN_KEYBOARD,
        )
        return

    if close_stock_by_id(stock["id"]):
        await update.message.reply_text(
            f"🛑 {stock['name']} ({stock['code']}) 추적을 종료했습니다.",
            reply_markup=MAIN_KEYBOARD,
        )
    else:
        await update.message.reply_text(
            "이미 삭제되었거나 찾을 수 없는 항목입니다.",
            reply_markup=MAIN_KEYBOARD,
        )


async def cmd_close(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await start_stock_delete(update)
        return

    query = " ".join(args).strip()
    active = get_active_stocks()
    stock = resolve_delete_selection(query, active)
    if not stock:
        await update.message.reply_text(
            "삭제할 종목을 찾을 수 없습니다.\n"
            "`종목삭제`를 눌러 목록의 번호 버튼을 선택하거나 종목코드를 입력해주세요.",
            parse_mode="Markdown",
            reply_markup=MAIN_KEYBOARD,
        )
        return

    if close_stock_by_id(stock["id"]):
        await update.message.reply_text(
            f"🛑 {stock['name']} ({stock['code']}) 추적을 종료했습니다.",
            reply_markup=MAIN_KEYBOARD,
        )
    else:
        await update.message.reply_text(
            "이미 삭제되었거나 찾을 수 없는 항목입니다.",
            reply_markup=MAIN_KEYBOARD,
        )


async def message_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """버튼/텍스트 명령어 라우팅 + 다단계 입력 상태 처리"""
    text    = update.message.text.strip()
    parts   = text.split()
    keyword = parts[0] if parts else ""
    cid     = str(update.effective_chat.id)
    button_keyword = keyword in BUTTON_KEYWORDS
    command_has_args = len(parts) > 1

    # ── 다단계 입력 대기 중인 경우 ──
    pending = _pending.pop(cid, None)
    if pending and button_keyword:
        await update.message.reply_text(
            "이전 입력 대기를 취소하고 선택한 버튼을 실행합니다.",
            reply_markup=MAIN_KEYBOARD,
        )
        pending = None

    if pending:
        if text == "취소":
            await update.message.reply_text("입력을 취소하고 대기 내용을 삭제했습니다.", reply_markup=MAIN_KEYBOARD)
            return

        action = pending.get("action")
        if action in {"buy_code", "buy_price", "buy_confirm"}:
            await handle_pending_stock_registration(update, text, parts, pending)
            return
        if action == "close":
            await handle_pending_stock_delete(update, text, pending)
            return
        if action == "stock_analysis":
            await cmd_stock_analysis(update, text)
            return
        if action == "settings_monitor_interval":
            await handle_monitor_interval_input(update, context, text)
            return

    if keyword in LEGACY_BUTTONS:
        await update.message.reply_text(
            "🔄 버튼 메뉴를 최신 버전으로 갱신했습니다.",
            reply_markup=MAIN_KEYBOARD,
        )

    # ── 일반 라우팅 ──
    if keyword in {"AI추천", "추천"}:
        await cmd_recommend(update, context)
        await cmd_new_recommend(update, context)
    elif keyword == "신규추천":
        await cmd_new_recommend(update, context)
    elif keyword in {"종목등록", "매수"}:
        if len(parts) >= 3:
            context.args = parts[1:]
            await cmd_buy(update, context)
        else:
            await start_stock_registration(update)
    elif keyword in {"현재상황", "상태"}:
        if len(parts) >= 2:
            context.args = parts[1:]
        else:
            context.args = []
        await cmd_status(update, context)
    elif keyword in {"종목삭제", "종료"}:
        if len(parts) >= 2:
            context.args = parts[1:]
            await cmd_close(update, context)
        else:
            await start_stock_delete(update)
    elif keyword == "종목분석":
        if len(parts) >= 2:
            await cmd_stock_analysis(update, " ".join(parts[1:]))
        else:
            _pending[cid] = {"action": "stock_analysis"}
            await update.message.reply_text(
                "🔬 분석할 *종목명 또는 종목코드*를 입력하세요.\n예: `삼성전자` 또는 `005930`",
                parse_mode="Markdown",
            )
    elif keyword == "도움말":
        await cmd_help(update, context)
    elif keyword == "설정":
        await cmd_settings(update)
    elif keyword == "메시지 알림받기":
        await cmd_notification_on(update, context)
    elif keyword == "메시지 알림중지":
        await cmd_notification_off(update, context)
    else:
        await update.message.reply_text(
            HELP_TEXT, parse_mode="Markdown", reply_markup=MAIN_KEYBOARD
        )


async def cmd_new_recommend(update: Update, context: ContextTypes.DEFAULT_TYPE):
    market_open = is_market_open()
    label_time  = "장중" if market_open else "장 외(전일 일봉 기준)"
    await update.message.reply_text(f"🆕 신규 모멘텀 종목 스캔 중... [{label_time}]")
    try:
        threshold = 70 if market_open else 50
        results = []
        for stock in scrape_top_stocks(limit=40):
            code = stock.get("code")
            if not code:
                continue
            candles = get_candles(code, count=80) if market_open else get_daily_candles(code, count=30)
            sd = calculate_new_score(stock, candles)
            if sd["score"] >= threshold:
                results.append({**stock, **sd})

        results.sort(key=lambda x: x["score"], reverse=True)
        top5 = results[:5]

        if not top5:
            await update.message.reply_text("⚠️ 현재 신규 모멘텀 종목이 없습니다.")
            return

        lines = ["🆕 *신규 모멘텀 TOP 5*\n" + "─" * 22]
        for i, s in enumerate(top5, 1):
            lines.append(
                f"{i}. *{s['name']}* ({s['market']})\n"
                f"   현재가 {s['price']:,}원  등락 {s['change_rate']:+.1f}%\n"
                f"   점수 {s['score']}점 | {', '.join(s['reasons'])}"
            )
        await update.message.reply_text("\n\n".join(lines), parse_mode="Markdown")

        # LLM 신규 모멘텀 해설
        stock_summary = "\n".join(
            f"- {s['name']}: 현재가 {s['price']:,}원, 등락 {s['change_rate']:+.1f}%, "
            f"신호: {', '.join(s['reasons'])}"
            for s in top5
        )
        commentary = await llm(
            "당신은 한국 주식 단타 전문가입니다. 간결하고 핵심만 답하세요.",
            f"방금 모멘텀이 시작된 종목들입니다. 진입 시 유의사항을 2~3문장으로 설명해주세요:\n{stock_summary}",
            max_tokens=800,
        )
        if commentary:
            await update.message.reply_text(f"🤖 *AI 분석*\n{commentary}", parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"오류: {e}")


async def _send_recommend(bot, chat_id: str, label: str):
    """추천 결과를 공통으로 전송 (자동 추천 job용)"""
    market_open = is_market_open()
    threshold   = 70 if market_open else 50
    results = []
    for stock in scrape_top_stocks(limit=40):
        code = stock.get("code")
        if not code:
            continue
        candles = get_candles(code, count=80) if market_open else get_daily_candles(code, count=30)
        sd = calculate_new_score(stock, candles)
        if sd["score"] >= threshold:
            results.append({**stock, **sd})

    results.sort(key=lambda x: x["score"], reverse=True)
    top5 = results[:5]

    if not top5:
        return

    lines = [f"🤖 *{label}*\n" + "─" * 22]
    for i, s in enumerate(top5, 1):
        lines.append(
            f"{i}. *{s['name']}* ({s['market']})\n"
            f"   현재가 {s['price']:,}원  등락 {s['change_rate']:+.1f}%\n"
            f"   점수 {s['score']}점 | {', '.join(s['reasons'])}"
        )
    await bot.send_message(
        chat_id=int(chat_id),
        text="\n\n".join(lines),
        parse_mode="Markdown",
    )


async def auto_recommend_job(context: ContextTypes.DEFAULT_TYPE):
    """30분마다 장중 자동 신규 종목 추천"""
    chat_id = get_setting("chat_id")
    if not chat_id:
        return
    if not is_notification_enabled():
        return

    # 장중 시간만 실행 (KST 09:05 ~ 15:25)
    now = now_kst()
    if not (9 * 60 + 5 <= now.hour * 60 + now.minute <= 15 * 60 + 25):
        return

    try:
        label = f"자동 신규추천 {now.strftime('%H:%M')}"
        await _send_recommend(context.bot, chat_id, label)
    except Exception as e:
        print(f"[auto_recommend_job] 오류: {e}")


# ── 주기 작업 (15초) ──────────────────────────────────────────────────

async def track_job(context: ContextTypes.DEFAULT_TYPE):
    """보유 종목 매도 신호 감시"""
    chat_id = get_setting("chat_id")
    if not chat_id:
        return
    if not is_notification_enabled():
        return
    sell_signals = []
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
                sell_signals.append({
                    "name": stock["name"],
                    "code": code,
                    "score": sd["score"],
                    "price": info["price"],
                    "pnl": sd["pnl"],
                    "reasons": sd["reasons"],
                })
        except Exception as e:
            print(f"[track_job] {stock['name']} 오류: {e}")

    if not sell_signals:
        return

    lines = ["⚠️ *매도 신호 감지*"]
    for signal in sell_signals:
        lines.append(
            f"\n*{signal['name']}* ({signal['code']})  점수: {signal['score']}\n"
            f"현재가: {signal['price']:,.0f}원  수익률: {signal['pnl']:+.2f}%\n"
            f"사유: {', '.join(signal['reasons'])}"
        )

    signal_summary = "\n".join(
        f"- {s['name']}({s['code']}): 점수 {s['score']}, 현재가 {s['price']:,.0f}원, "
        f"수익률 {s['pnl']:+.2f}%, 사유: {', '.join(s['reasons'])}"
        for s in sell_signals
    )
    commentary = await llm(
        "당신은 한국 주식 단타 전문가입니다. 간결하고 실행 중심으로 답하세요.",
        "다음 종목들에 매도 신호가 감지됐습니다. "
        "각 종목별로 매도/보유/부분매도 중 하나와 핵심 이유를 한 줄씩 제시하세요:\n"
        + signal_summary,
        max_tokens=1200,
    )
    if commentary:
        lines.append(f"\n🤖 *AI 일괄 판단*\n{commentary}")

    await context.bot.send_message(
        chat_id=int(chat_id),
        text="\n".join(lines),
        parse_mode="Markdown",
    )


def _analyze_trend(cur: int, daily: list, buy_price: float, open_price: int) -> str:
    """
    일봉 데이터 기반 추이 분석
    - MA5 / MA20 방향 (골든/데드크로스)
    - 5일 / 10일 변화율
    - 장중이면 당일 시가 대비 흐름도 추가
    """
    if len(daily) < 5:
        # 일봉 부족 → 매수가 대비만 표시
        base  = open_price if open_price > 0 else buy_price
        label = "시가" if open_price > 0 else "매수가"
        diff  = (cur - base) / base * 100
        arrow = "↑" if diff > 0.3 else ("↓" if diff < -0.3 else "→")
        return f"{arrow} {label} 대비 {diff:+.1f}%"

    closes = [c["close"] for c in daily]

    # MA5 / MA20
    ma5  = sum(closes[-5:]) / 5
    ma20 = sum(closes[-min(20, len(closes)):]) / min(20, len(closes))

    # 기간 변화율
    chg5  = (closes[-1] - closes[-5])  / closes[-5]  * 100
    chg10 = (closes[-1] - closes[-min(10, len(closes))]) / closes[-min(10, len(closes))] * 100

    # 방향 판단
    if ma5 > ma20 and chg5 > 0:
        cross = "골든크로스"
        arrow = "↑"
    elif ma5 < ma20 and chg5 < 0:
        cross = "데드크로스"
        arrow = "↓"
    else:
        cross = "혼조"
        arrow = "→"

    trend = f"{arrow} {cross} | 5일 {chg5:+.1f}% / 10일 {chg10:+.1f}%"

    # 장중이면 당일 흐름 추가
    if open_price > 0:
        intraday = (cur - open_price) / open_price * 100
        trend += f" | 당일 {intraday:+.1f}%"

    return trend


async def startup_notify(context: ContextTypes.DEFAULT_TYPE):
    """봇 시작 시 시작 시각 + GitHub 최종 업데이트 일자 전송"""
    chat_id = get_setting("chat_id")
    if not chat_id:
        return

    start_time = now_kst().strftime("%Y-%m-%d %H:%M:%S")

    # GitHub raw 파일의 Last-Modified 헤더로 업데이트 일자 확인
    update_date = "확인 불가"
    try:
        res = requests.head(
            "https://raw.githubusercontent.com/escaredleaf/py/main/run.py",
            timeout=8,
        )
        lm = res.headers.get("Last-Modified", "")
        if lm:
            # 예: "Mon, 28 Apr 2026 04:00:00 GMT" → 파싱
            from email.utils import parsedate_to_datetime
            dt = parsedate_to_datetime(lm)
            update_date = dt.astimezone(KST).strftime("%Y-%m-%d %H:%M KST")
    except Exception:
        pass

    await context.bot.send_message(
        chat_id=int(chat_id),
        text=(
            "🚀 *QuantScalpBot 시작*\n"
            f"  시작 시각: `{start_time}`\n"
            f"  최신 업데이트: `{update_date}`\n"
            "  버튼 메뉴: 최신 버전으로 갱신"
        ),
        parse_mode="Markdown",
        reply_markup=MAIN_KEYBOARD,
    )


async def health_job(context: ContextTypes.DEFAULT_TYPE):
    """설정된 간격마다 연동 상태 + 보유 종목 현황 전송"""
    chat_id = get_setting("chat_id")
    if not chat_id:
        return
    if not is_notification_enabled():
        return

    # ── 연동 상태 체크 ──
    results = {}
    try:
        res = requests.get(
            "https://finance.naver.com/sise/sise_quant.nhn?sosok=0",
            headers=HEADERS, timeout=8
        )
        results["네이버 금융"] = "✅" if res.status_code == 200 else f"❌ {res.status_code}"
    except Exception:
        results["네이버 금융"] = "❌ 연결 실패"

    try:
        res = requests.get(
            "https://m.stock.naver.com/api/stock/005930/basic",
            headers=HEADERS, timeout=8
        )
        results["네이버 API"] = "✅" if res.status_code == 200 else f"❌ {res.status_code}"
    except Exception:
        results["네이버 API"] = "❌ 연결 실패"

    try:
        active = get_active_stocks()
        results["DB"] = "✅"
    except Exception:
        results["DB"] = "❌ 오류"
        active = []

    now = now_kst().strftime("%H:%M:%S")
    lines = [f"🔍 *헬스체크* `{now}`"]
    for k, v in results.items():
        lines.append(f"• {k}: {v}")

    # ── 보유 종목 현황 ──
    if active:
        lines.append("\n📋 *보유 종목 현황*")
        lines += await _build_portfolio_lines(active)

    await context.bot.send_message(
        chat_id=int(chat_id),
        text="\n".join(lines),
        parse_mode="Markdown",
    )


# ── 진입점 ────────────────────────────────────────────────────────────

def main():
    init_db()
    print("✅ DB 초기화 완료")

    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help",  cmd_help))
    # 한글 명령어는 텍스트 메시지로 처리 (텔레그램은 영문 명령어만 허용)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_router))

    jk = {"misfire_grace_time": 30}  # 30초 이내 지연은 경고 없이 실행
    monitor_interval = get_monitor_interval_seconds()
    schedule_track_job(app.job_queue, jk, first=SELL_SCAN_INTERVAL_SECONDS)
    schedule_notification_job(app.job_queue, jk, first=monitor_interval)
    app.job_queue.run_repeating(auto_recommend_job, interval=1800, first=120, job_kwargs=jk)
    app.job_queue.run_once(startup_notify, when=3)

    print("🚀 QuantScalpBot 가동 중 (Ctrl+C 로 종료)")
    app.run_polling(allowed_updates=["message"])


if __name__ == "__main__":
    main()
