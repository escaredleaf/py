import requests
from urllib.parse import quote
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 13; Pixel 7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Mobile Safari/537.36"
    )
}


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
                    change_rate = float(rate_text) if rate_text else 0.0
                    volume = int(vol_text) if vol_text.isdigit() else 0

                    # 가격 필터 2,000 ~ 30,000원
                    if not (2_000 <= price <= 30_000):
                        continue

                    stocks.append({
                        "name": name,
                        "code": code,
                        "price": price,
                        "change_rate": change_rate,
                        "volume": volume,
                        "market": "KOSPI" if sosok == 0 else "KOSDAQ",
                    })
                except (ValueError, IndexError):
                    continue
        except Exception as e:
            print(f"[collector] scrape_top_stocks error: {e}")

    return stocks[:limit]


def get_stock_info(code: str) -> dict | None:
    """네이버 모바일 API로 현재가 및 거래량 조회"""
    url = f"https://m.stock.naver.com/api/stock/{code}/basic"
    try:
        res = requests.get(url, headers=HEADERS, timeout=8)
        d = res.json()

        def _int(v: str) -> int:
            return int(str(v).replace(",", "")) if v else 0

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
    """네이버 fchart API로 1분봉 데이터 조회"""
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


def find_code_by_name(name: str) -> str | None:
    """종목명으로 종목코드 검색 (네이버 자동완성 API)"""
    url = (
        f"https://ac.finance.naver.com/ac"
        f"?q={quote(name)}&q_enc=UTF-8&t_aid=stock&st=111"
        f"&r_format=json&r_enc=UTF-8&r_unicode=0&t_koreng=1&r_lt=5"
    )
    try:
        res = requests.get(url, headers=HEADERS, timeout=8)
        data = res.json()
        items = data.get("items", [[]])[0]
        # items[0] = [이름, 코드, ...]
        return items[0][1] if items and len(items[0]) > 1 else None
    except Exception as e:
        print(f"[collector] find_code_by_name error: {e}")
        return None
