# Android WebRTC AI Voice Call App

안드로이드 앱에서 WebRTC를 통해 AI와 실시간 음성 통화를 수행하는 예제입니다.

## 프로젝트 위치

`/workspace/android-call-app`

## 구성

- Android 앱: `android-call-app/app`
  - 마이크 권한 요청
  - WebRTC Offer/Answer 교환
  - AI 통화 시작/종료 UI
- 세션 서버(FastAPI): `android-call-app/session-server`
  - 서버에 저장된 OpenAI API 키로 에페메럴 토큰 발급
  - 앱은 이 토큰으로 Realtime WebRTC 연결

## 빠른 실행

### 1) 세션 서버 실행

```bash
cd /workspace/android-call-app/session-server
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

`.env`에 실제 키 입력:

```env
OPENAI_API_KEY=sk-...
OPENAI_REALTIME_MODEL=gpt-4o-realtime-preview
OPENAI_REALTIME_VOICE=alloy
```

서버 실행:

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

### 2) Android 앱 실행

1. Android Studio에서 `/workspace/android-call-app` 열기
2. Gradle Sync 완료
3. 앱 실행
4. 세션 URL 입력
   - 에뮬레이터: `http://10.0.2.2:8000/session`
   - 실기기: `http://<서버IP>:8000/session`
5. `AI 통화 시작` 버튼으로 연결

## 주의

- 이 예제는 MVP 수준으로, 프로덕션에서는 재시도/로깅/상태관리 개선이 필요합니다.
- OpenAI API 키는 앱에 넣지 말고 반드시 서버에서만 사용하세요.
