import os

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel


load_dotenv()

OPENAI_API_URL = "https://api.openai.com/v1/realtime/sessions"
DEFAULT_MODEL = os.getenv("OPENAI_REALTIME_MODEL", "gpt-4o-realtime-preview")
DEFAULT_VOICE = os.getenv("OPENAI_REALTIME_VOICE", "alloy")


class SessionRequest(BaseModel):
    voice: str = DEFAULT_VOICE
    instructions: str = "You are a helpful Korean-speaking voice assistant."


app = FastAPI(title="AI Realtime Session Server")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/session")
async def create_session(payload: SessionRequest) -> dict[str, str]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY is not configured.")

    model = DEFAULT_MODEL
    timeout = float(os.getenv("OPENAI_TIMEOUT_SECONDS", "30"))

    request_body = {
        "model": model,
        "voice": payload.voice,
        "instructions": payload.instructions,
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(OPENAI_API_URL, headers=headers, json=request_body)

    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail=response.text)

    data = response.json()
    client_secret = (data.get("client_secret") or {}).get("value")
    if not client_secret:
        raise HTTPException(status_code=500, detail="OpenAI response missing client_secret.")

    return {"client_secret": client_secret, "model": model}
