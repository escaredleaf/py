# Session Server (FastAPI)

안드로이드 앱에서 WebRTC 통화를 시작할 때 필요한 OpenAI Realtime **ephemeral client secret**을 발급해 주는 최소 서버입니다.

## 1) 환경 준비

```bash
cd /workspace/android-call-app/session-server
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 2) 환경 변수 설정

```bash
cp .env.example .env
```

`.env` 파일에서 아래 값을 채우세요.

- `OPENAI_API_KEY`: 서버에서 사용할 OpenAI API Key
- `OPENAI_REALTIME_MODEL`: 기본 `gpt-4o-realtime-preview`
- `OPENAI_REALTIME_VOICE`: 기본 `alloy`
- `OPENAI_TIMEOUT_SECONDS`: 기본 `30`

## 3) 서버 실행

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

## 4) 앱 연결

안드로이드 앱의 세션 서버 URL 입력칸에 다음 주소를 입력합니다.

- 에뮬레이터: `http://10.0.2.2:8000/session`
- 실기기: `http://<개발PC_IP>:8000/session`

## 엔드포인트

- `POST /session`
  - 응답 예시:
    ```json
    {
      "client_secret": "...",
      "model": "gpt-4o-realtime-preview"
    }
    ```
