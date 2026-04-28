import pandas as pd


def _vwap(candles: list) -> float:
    """VWAP = Σ(종가 × 거래량) / Σ거래량"""
    tv = sum(c["close"] * c["volume"] for c in candles)
    vol = sum(c["volume"] for c in candles)
    return tv / vol if vol > 0 else 0.0


def calculate_sell_score(stock_info: dict, candles: list, buy_price: float) -> dict:
    """
    매도 신호 점수 계산 (0~100)

    채점 항목:
      - 손절 -2% / 목표 +5%   → 즉시 100점
      1. 연속 고점 하락        (25점) - 3봉 연속 고점 하락
      2. 거래량 감소           (25점) - 피크 대비 최근 거래량
      3. VWAP 하회            (25점) - 현재가 < VWAP
      4. 모멘텀 둔화           (25점) - 최근 모멘텀 < 직전 모멘텀
    """
    score = 0
    reasons: list[str] = []

    if len(candles) < 5:
        return {"score": 0, "reasons": ["데이터 부족"], "pnl": 0.0}

    current = stock_info.get("price", 0)
    if current == 0:
        return {"score": 0, "reasons": ["가격 정보 없음"], "pnl": 0.0}

    pnl = round((current - buy_price) / buy_price * 100, 2)

    # 즉시 매도 조건
    if pnl <= -2.0:
        return {"score": 100, "reasons": [f"손절 기준 도달 ({pnl:.1f}%)"], "pnl": pnl}
    if pnl >= 5.0:
        return {"score": 100, "reasons": [f"목표 수익 달성 ({pnl:.1f}%)"], "pnl": pnl}

    df = pd.DataFrame(candles)

    # 1. 연속 고점 하락 (3봉)
    if len(df) >= 3:
        h = df["high"].iloc[-3:].tolist()
        if h[2] < h[1] < h[0]:
            score += 25
            reasons.append("3봉 연속 고점 하락")
        elif h[2] < h[1]:
            score += 10

    # 2. 거래량 감소 (피크 대비)
    if len(df) >= 6:
        window = df["volume"].iloc[-6:]
        peak_vol   = window.max()
        recent_avg = df["volume"].iloc[-3:].mean()
        if peak_vol > 0:
            decay = (peak_vol - recent_avg) / peak_vol
            if decay >= 0.5:
                score += 25
                reasons.append(f"거래량 {decay*100:.0f}% 급감")
            elif decay >= 0.3:
                score += 12

    # 3. VWAP 하회
    vwap = _vwap(candles[-30:] if len(candles) >= 30 else candles)
    if vwap > 0 and current < vwap:
        score += 25
        reasons.append(f"VWAP({vwap:,.0f}) 하회")

    # 4. 모멘텀 둔화
    if len(df) >= 6:
        c = df["close"]
        mom_now  = (c.iloc[-1] - c.iloc[-3]) / c.iloc[-3] * 100 if c.iloc[-3] > 0 else 0
        mom_prev = (c.iloc[-3] - c.iloc[-6]) / c.iloc[-6] * 100 if c.iloc[-6] > 0 else 0
        if mom_now < 0 and mom_prev > 0:
            score += 25
            reasons.append("모멘텀 반전")
        elif mom_now < mom_prev:
            score += 10
            reasons.append("모멘텀 둔화")

    return {
        "score": min(100, max(0, score)),
        "reasons": reasons,
        "pnl": pnl,
        "vwap": round(vwap),
    }
