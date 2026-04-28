import os
import sys
import platform
import requests
from datetime import datetime

TOKEN = os.environ.get("TELEGRAM_TOKEN", "8751027463:AAEt_Xg7nR0AAVJyXYkyUgkt6BXFbC_x28o")
API = f"https://api.telegram.org/bot{TOKEN}"


def send(chat_id, text):
    requests.post(f"{API}/sendMessage", json={"chat_id": chat_id, "text": text})


def system_info():
    return (
        f"Python: {sys.version.split()[0]}\n"
        f"Platform: {platform.system()} {platform.machine()}\n"
        f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )


def fizzbuzz(n):
    result = []
    for i in range(1, n + 1):
        if i % 15 == 0:
            result.append("FizzBuzz")
        elif i % 3 == 0:
            result.append("Fizz")
        elif i % 5 == 0:
            result.append("Buzz")
        else:
            result.append(str(i))
    return ", ".join(result)


def calc(expr):
    try:
        # 안전한 수식만 허용
        allowed = set("0123456789+-*/(). ")
        if not all(c in allowed for c in expr):
            return "허용되지 않는 문자가 포함되어 있습니다."
        return str(eval(expr))
    except Exception as e:
        return f"오류: {e}"


def handle(message):
    chat_id = message["chat"]["id"]
    text = message.get("text", "").strip()

    if text == "/start":
        send(chat_id, "안녕하세요! 사용 가능한 명령어:\n/info - 시스템 정보\n/fizzbuzz - FizzBuzz (1~20)\n/calc 수식 - 계산기\n그 외 메시지는 그대로 돌려드립니다.")
    elif text == "/info":
        send(chat_id, system_info())
    elif text == "/fizzbuzz":
        send(chat_id, fizzbuzz(20))
    elif text.startswith("/calc "):
        expr = text[6:].strip()
        send(chat_id, f"{expr} = {calc(expr)}")
    else:
        send(chat_id, f"받은 메시지: {text}")


def poll():
    print("Telegram 봇 시작... (종료: Ctrl+C)")
    offset = None
    while True:
        try:
            res = requests.get(f"{API}/getUpdates", params={"offset": offset, "timeout": 30}, timeout=35)
            updates = res.json().get("result", [])
            for update in updates:
                offset = update["update_id"] + 1
                if "message" in update:
                    handle(update["message"])
        except KeyboardInterrupt:
            print("\n봇 종료.")
            break
        except Exception as e:
            print(f"오류: {e}")


if __name__ == "__main__":
    poll()
