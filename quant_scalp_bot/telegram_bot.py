from telegram import Update
from telegram.ext import ContextTypes, CommandHandler

from collector import scrape_top_stocks, get_candles, get_stock_info, find_code_by_name
from scorer import calculate_buy_score
from tracker import calculate_sell_score
from db import (
    add_tracked_stock, get_active_stocks, get_stock_record,
    close_stock, set_setting, get_setting,
)

HELP_TEXT = (
    "📈 *QuantScalpBot* 명령어\n"
    "─────────────────────\n"
    "/추천 - 매수 추천 종목 TOP 5\n"
    "/매수 종목명 매수가 - 매수 등록 및 모니터링 시작\n"
    "/상태 - 전체 추적 종목 현황\n"
    "/상태 종목명 - 특정 종목 상세 현황\n"
    "/종료 종목명 - 종목 추적 중단\n"
    "/도움말 - 이 메시지"
)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    set_setting("chat_id", chat_id)
    await update.message.reply_text(
        f"✅ QuantScalpBot 시작!\nchat_id 저장 완료.\n\n{HELP_TEXT}",
        parse_mode="Markdown",
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_TEXT, parse_mode="Markdown")


async def cmd_recommend(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📊 종목 스캔 중... (20~30초 소요)")
    try:
        stocks = scrape_top_stocks(limit=40)
        results = []

        for stock in stocks:
            code = stock.get("code")
            if not code:
                continue
            candles = get_candles(code, count=80)
            sd = calculate_buy_score(stock, candles)
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
        await update.message.reply_text("사용법: /매수 종목명 매수가\n예: /매수 삼성전자 71200")
        return

    name = args[0]
    try:
        buy_price = float(args[1].replace(",", ""))
    except ValueError:
        await update.message.reply_text("매수가를 숫자로 입력해주세요.")
        return

    code = find_code_by_name(name) or ""
    add_tracked_stock(name, code, buy_price)

    await update.message.reply_text(
        f"✅ *매수 등록 완료*\n"
        f"종목: {name}  코드: {code or '조회실패'}\n"
        f"매수가: {buy_price:,.0f}원\n"
        f"15초마다 매도 신호 모니터링 시작",
        parse_mode="Markdown",
    )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args

    # 전체 현황
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

    # 특정 종목 상세
    name = args[0]
    record = get_stock_record(name)
    if not record:
        await update.message.reply_text(f"'{name}' 을(를) 찾을 수 없습니다.")
        return

    code = record.get("code")
    if not code:
        await update.message.reply_text(f"{name}: 종목코드 없음")
        return

    info = get_stock_info(code)
    candles = get_candles(code, count=80)
    if not info:
        await update.message.reply_text(f"{name}: 현재가 조회 실패")
        return

    sd = calculate_sell_score(info, candles, record["buy_price"])
    pnl = sd["pnl"]
    emoji = "📈" if pnl >= 0 else "📉"

    await update.message.reply_text(
        f"📌 *{name}* 상태\n"
        f"매수가: {record['buy_price']:,.0f}원\n"
        f"현재가: {info['price']:,.0f}원\n"
        f"{emoji} 수익률: {pnl:+.2f}%\n"
        f"VWAP: {sd.get('vwap', 0):,.0f}원\n"
        f"매도 점수: {sd['score']}점\n"
        f"신호: {', '.join(sd['reasons']) or '없음'}",
        parse_mode="Markdown",
    )


async def cmd_close(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text("사용법: /종료 종목명")
        return
    name = args[0]
    close_stock(name)
    await update.message.reply_text(f"🛑 {name} 추적을 종료했습니다.")


# ── 주기적 매도 신호 감시 (15초) ──────────────────────────────────────

async def track_job(context: ContextTypes.DEFAULT_TYPE):
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
            candles = get_candles(code, count=80)
            sd = calculate_sell_score(info, candles, stock["buy_price"])

            if sd["score"] >= 60:
                pnl = sd["pnl"]
                await context.bot.send_message(
                    chat_id=int(chat_id),
                    text=(
                        f"⚠️ *매도 신호* {stock['name']}  (점수: {sd['score']})\n"
                        f"현재가: {info['price']:,.0f}원  수익률: {pnl:+.2f}%\n"
                        f"사유: {', '.join(sd['reasons'])}"
                    ),
                    parse_mode="Markdown",
                )
        except Exception as e:
            print(f"[track_job] {stock['name']} 오류: {e}")


def get_handlers():
    return [
        CommandHandler("start",   cmd_start),
        CommandHandler("도움말",  cmd_help),
        CommandHandler("추천",    cmd_recommend),
        CommandHandler("매수",    cmd_buy),
        CommandHandler("상태",    cmd_status),
        CommandHandler("종료",    cmd_close),
    ]
