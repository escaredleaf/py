import pandas as pd


def calculate_buy_score(stock: dict, candles: list) -> dict:
    """
    매수 추천 점수 계산 (0~100)

    채점 항목:
      1. 거래량 급증    (20점) - 최근 5봉 평균 vs 이전 10봉 평균
      2. 가격 가속도    (20점) - 최근 모멘텀 > 직전 모멘텀
      3. 거래량 가속도  (20점) - 3봉 연속 거래량 증가
      4. 눌림목 돌파    (20점) - 직전 고점 대비 현재 종가
      5. 등락률 적정    (20점) - 당일 등락 +1% ~ +8%
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
            score += 20
            reasons.append(f"거래량 {ratio:.1f}배 급증")
        elif ratio >= 2.0:
            score += 12
            reasons.append(f"거래량 {ratio:.1f}배 증가")
        elif ratio >= 1.5:
            score += 6

    # 2. 가격 가속도
    if len(df) >= 6:
        c0 = df["close"].iloc[-6]
        c3 = df["close"].iloc[-3]
        c6 = df["close"].iloc[-1]
        mom_now  = (c6 - c3) / c3 * 100 if c3 > 0 else 0
        mom_prev = (c3 - c0) / c0 * 100 if c0 > 0 else 0
        if mom_now > mom_prev and mom_now > 0.5:
            score += 20
            reasons.append(f"가격 가속 +{mom_now:.1f}%")
        elif mom_now > 0.3:
            score += 10
            reasons.append(f"상승 중 +{mom_now:.1f}%")

    # 3. 거래량 가속도 (3봉 연속 증가)
    if len(df) >= 3:
        v = df["volume"].iloc[-3:].tolist()
        if v[2] > v[1] > v[0]:
            score += 20
            reasons.append("거래량 3봉 연속 증가")
        elif v[2] > v[1]:
            score += 8

    # 4. 눌림목 후 돌파
    if len(df) >= 10:
        recent_high = df["high"].iloc[-10:-3].max()
        current     = df["close"].iloc[-1]
        if recent_high > 0:
            if current >= recent_high * 0.998:
                score += 20
                reasons.append("전고점 돌파")
            elif current >= recent_high * 0.990:
                score += 10
                reasons.append("전고점 근접")

    # 5. 당일 등락률 2~8% 적정 구간
    rate = stock.get("change_rate", 0)
    if 2.0 <= rate <= 8.0:
        score += 20
        reasons.append(f"등락 +{rate:.1f}%")
    elif 1.0 <= rate < 2.0:
        score += 8
    elif rate > 8.0:
        score -= 10
        reasons.append("과열 주의")

    return {"score": min(100, max(0, score)), "reasons": reasons}
