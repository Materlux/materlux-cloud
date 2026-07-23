"""Webhook do WhatsApp — agnóstico de provedor (Z-API, Meta, ou console de teste).

- GET  /webhook/whatsapp : verificação (usada pela Meta Cloud API).
- POST /webhook/whatsapp : recebe a mensagem, chama o agente e responde.
- POST /api/simulate     : endpoint interno para testar o agente sem WhatsApp real.
"""
import httpx
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Request, Query, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from ..config import get_settings
from ..security import current_user
from .. import agent, db

router = APIRouter()
_s = get_settings()
TZ = ZoneInfo(_s.CLINIC_TZ)


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
    if agent.get_atendimento_status(phone) == "humano":
        # transbordo: recepção no comando — bot em silêncio absoluto,
        # só registra a mensagem para manter o contexto da conversa
        agent.log_paused_message(phone, text)
        return {"status": "humano"}
    reply = agent.process_message(phone, text)
    send_reply(phone, reply)
    return {"status": "ok", "reply": reply}


class WaStatusIn(BaseModel):
    status: str  # 'bot' | 'humano'


@router.get("/api/wa/conversas")
def wa_conversas(user: dict = Depends(current_user)):
    """Conversas recentes do WhatsApp com o status do atendimento (bot/humano)."""
    rows = db.query(
        "SELECT s.sender_number, s.pausado_em, s.pausado_por, "
        "(SELECT max(h.created_at) FROM conversations.state_history h "
        " WHERE h.sender_number = s.sender_number) AS ultima "
        "FROM conversations.sessions s "
        "ORDER BY ultima DESC NULLS LAST LIMIT 50"
    )
    out = []
    for r in rows:
        status = agent.get_atendimento_status(r["sender_number"])  # aplica o retorno após 12h
        nomes = db.query(
            "SELECT DISTINCT p.first_name || ' ' || p.last_name AS nome "
            "FROM patients.contacts c JOIN patients.records p ON p.id = c.patient_id "
            "WHERE c.phone_number = %s", (r["sender_number"],),
        )
        out.append({
            "numero": r["sender_number"],
            "pacientes": ", ".join(sorted(n["nome"].strip() for n in nomes)),
            "ultima": (r["ultima"].astimezone(TZ).strftime("%d/%m/%Y %H:%M")
                       if r["ultima"] else ""),
            "status": status,
            "pausado_em": (r["pausado_em"].astimezone(TZ).strftime("%d/%m %H:%M")
                           if status == "humano" and r["pausado_em"] else ""),
            "pausado_por": (r["pausado_por"] or "") if status == "humano" else "",
        })
    return out


@router.get("/api/wa/alerta")
def wa_alerta(user: dict = Depends(current_user)):
    """Resumo leve para o alerta da aba WhatsApp: quantas conversas estão em
    atendimento humano e quando foi a pausa mais recente (respeita as 12h)."""
    row = db.query(
        "SELECT count(*) AS n, max(pausado_em) AS ultimo "
        "FROM conversations.sessions "
        "WHERE atendimento_status = 'humano' "
        "AND (pausado_em IS NULL OR pausado_em > now() - interval '12 hours')",
        one=True,
    )
    return {"humano": row["n"],
            "ultimo": row["ultimo"].isoformat() if row["ultimo"] else None}


@router.post("/api/wa/conversas/{phone}/status")
def wa_set_status(phone: str, body: WaStatusIn,
                  user: dict = Depends(current_user)):
    if body.status not in ("bot", "humano"):
        raise HTTPException(status_code=400, detail="status deve ser 'bot' ou 'humano'")
    agent.set_atendimento_status(phone, body.status,
                                 user.get("name") or "painel")
    return {"ok": True, "status": body.status}


class SimIn(BaseModel):
    phone: str
    message: str


@router.post("/api/simulate")
def simulate(body: SimIn, user: dict = Depends(current_user)):
    """Testa o agente pela interface, sem enviar WhatsApp real."""
    return {"reply": agent.process_message(body.phone, body.message)}
