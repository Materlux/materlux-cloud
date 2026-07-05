"""Webhook do WhatsApp — agnóstico de provedor (Z-API, Meta, ou console de teste).

- GET  /webhook/whatsapp : verificação (usada pela Meta Cloud API).
- POST /webhook/whatsapp : recebe a mensagem, chama o agente e responde.
- POST /api/simulate     : endpoint interno para testar o agente sem WhatsApp real.
"""
import httpx
from fastapi import APIRouter, Request, Query, Depends
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from ..config import get_settings
from ..security import current_user
from .. import agent

router = APIRouter()
_s = get_settings()


def _extract(provider: str, payload: dict):
    """Normaliza o payload de diferentes provedores para (telefone, texto)."""
    if provider == "zapi":
        phone = payload.get("phone") or payload.get("sender")
        txt = ((payload.get("text") or {}).get("message")
               if isinstance(payload.get("text"), dict) else payload.get("message"))
        return phone, txt
    if provider == "meta":
        try:
            v = payload["entry"][0]["changes"][0]["value"]
            msg = v["messages"][0]
            return msg["from"], msg["text"]["body"]
        except (KeyError, IndexError):
            return None, None
    return payload.get("phone"), payload.get("message")


def send_reply(phone: str, text: str):
    """Envia a resposta pela API do provedor configurado."""
    if _s.WA_PROVIDER == "zapi" and _s.ZAPI_INSTANCE:
        url = f"https://api.z-api.io/instances/{_s.ZAPI_INSTANCE}/token/{_s.ZAPI_TOKEN}/send-text"
        headers = {"Client-Token": _s.ZAPI_CLIENT_TOKEN} if _s.ZAPI_CLIENT_TOKEN else {}
        httpx.post(url, json={"phone": phone, "message": text}, headers=headers, timeout=15)
    elif _s.WA_PROVIDER == "meta" and _s.META_PHONE_ID:
        url = f"https://graph.facebook.com/v20.0/{_s.META_PHONE_ID}/messages"
        headers = {"Authorization": f"Bearer {_s.META_TOKEN}"}
        httpx.post(url, headers=headers, timeout=15, json={
            "messaging_product": "whatsapp", "to": phone,
            "type": "text", "text": {"body": text}})
    # provider "console": não envia; resposta volta no corpo HTTP (para testes)


@router.get("/webhook/whatsapp")
def verify(mode: str = Query(None, alias="hub.mode"),
           token: str = Query(None, alias="hub.verify_token"),
           challenge: str = Query(None, alias="hub.challenge")):
    if mode == "subscribe" and token == _s.WA_VERIFY_TOKEN:
        return PlainTextResponse(challenge or "")
    return PlainTextResponse("forbidden", status_code=403)


@router.post("/webhook/whatsapp")
async def incoming(request: Request):
    payload = await request.json()
    phone, text = _extract(_s.WA_PROVIDER, payload)
    if not phone or not text:
        return {"status": "ignored"}
    reply = agent.process_message(phone, text)
    send_reply(phone, reply)
    return {"status": "ok", "reply": reply}


class SimIn(BaseModel):
    phone: str
    message: str


@router.post("/api/simulate")
def simulate(body: SimIn, user: dict = Depends(current_user)):
    """Testa o agente pela interface, sem enviar WhatsApp real."""
    return {"reply": agent.process_message(body.phone, body.message)}
