"""Atendente virtual da Materlux — substitui o fluxo n8n de 519 nós.

Gemini com tool-calling. O modelo conversa em português, consulta horários
livres da agenda do Dr. Murilo e da Dra. Isadora e cria o agendamento.
A sessão/estado da conversa é persistida em conversations.sessions para dar
continuidade entre mensagens.
"""
import json
import os
from pathlib import Path
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo
from .config import get_settings
from . import db, scheduling

_s = get_settings()
TZ = ZoneInfo(_s.CLINIC_TZ)

SYSTEM_PROMPT = """Você é a atendente virtual da Clínica Materlux (ginecologia, \
obstetrícia e pediatria). Fale em português do Brasil, de forma acolhedora, breve \
e objetiva. Seu único trabalho nesta fase é ajudar a paciente a AGENDAR uma consulta \
com o Dr. Murilo Ferraz ou com a Dra. Isadora Vencioneck.

Regras:
- Nunca invente horários. Sempre use as ferramentas para consultar a agenda real.
- Antes de confirmar, colete: nome da profissional desejada, tipo de atendimento \
(serviço), data e horário. Se a paciente não souber o serviço, liste as opções da \
profissional escolhida.
- Confirme os dados com a paciente antes de chamar criar_agendamento.
- Ao confirmar, informe data e horário por extenso e diga que a recepção confirmará \
os detalhes de pagamento. Não fale sobre QR Code nem porta (desativado nesta fase).
- Se não houver horário, ofereça as próximas datas disponíveis.
- Hoje é {hoje} ({dia_semana})."""


# Política de conversa: arquivo versionado (editável), com override por variável de
# ambiente (WA_SYSTEM_PROMPT) e fallback embutido no SYSTEM_PROMPT acima.
_POLICY_FILE = Path(__file__).parent / "politica_atendente.md"


def _load_policy(hoje_str: str, dia_semana: str) -> str:
    override = os.getenv("WA_SYSTEM_PROMPT", "").strip()
    if override:
        base = override
    else:
        try:
            base = _POLICY_FILE.read_text(encoding="utf-8")
        except Exception:
            base = SYSTEM_PROMPT.split("- Hoje é")[0]
    return f"{base}\n\nContexto: hoje é {hoje_str} ({dia_semana})."


# ---------------------------------------------------------------- ferramentas
def listar_profissionais() -> list[dict]:
    rows = db.query(
        "SELECT id, title, full_name FROM medical.professionals "
        "WHERE id = ANY(%s) AND is_active = true",
        (_s.BOOKABLE_PROFESSIONAL_IDS,),
    )
    return [{"id": r["id"], "nome": f"{(r['title'] or '').strip()} {r['full_name']}".strip()}
            for r in rows]


def listar_servicos(professional_id: int) -> list[dict]:
    rows = db.query(
        "SELECT s.id, s.name, ps.price FROM medical.professional_services ps "
        "JOIN medical.services s ON s.id = ps.service_id "
        "WHERE ps.professional_id = %s AND s.is_visible_to_patient = true "
        "ORDER BY ps.display_order",
        (professional_id,),
    )
    return [{"service_id": r["id"], "nome": r["name"], "preco": float(r["price"])} for r in rows]


def consultar_horarios(professional_id: int, data_iso: str) -> dict:
    d = date.fromisoformat(data_iso)
    slots = scheduling.available_slots(professional_id, d)
    if slots:
        return {"data": data_iso, "horarios": slots}
    prox = scheduling.next_available_days(professional_id, d + timedelta(days=1))
    return {"data": data_iso, "horarios": [], "proximas_datas": prox}


def criar_agendamento(sender_number: str, professional_id: int, service_id: int,
                      data_iso: str, hora: str, nome_paciente: str) -> dict:
    start = datetime.fromisoformat(f"{data_iso}T{hora}:00").replace(tzinfo=TZ)
    # revalida que o horário ainda está livre (evita corrida)
    if hora not in scheduling.available_slots(professional_id, start.date()):
        return {"ok": False, "motivo": "horario_indisponivel"}
    end = start + timedelta(minutes=_s.SLOT_MINUTES)

    patient_id = _get_or_create_patient(sender_number, nome_paciente)
    row = db.query(
        "INSERT INTO medical.appointments "
        "(professional_id, patient_id, service_id, status_id, start_time, end_time, origem) "
        "VALUES (%s, %s, %s, 1, %s, %s, 'whatsapp') RETURNING id",
        (professional_id, patient_id, service_id, start, end),
        one=True, commit=True,
    )
    return {
        "ok": True,
        "appointment_id": row["id"],
        "quando": start.strftime("%d/%m/%Y às %H:%M"),
        "profissional": scheduling.professional_name(professional_id),
    }


def _get_or_create_patient(sender_number: str, nome: str) -> int:
    contact = db.query(
        "SELECT patient_id FROM patients.contacts WHERE phone_number = %s LIMIT 1",
        (sender_number,), one=True,
    )
    if contact:
        return contact["patient_id"]
    partes = (nome or "Paciente WhatsApp").strip().split(" ", 1)
    first, last = partes[0], (partes[1] if len(partes) > 1 else "")
    pat = db.query(
        "INSERT INTO patients.records (first_name, last_name) VALUES (%s, %s) RETURNING id",
        (first, last), one=True, commit=True,
    )
    db.query(
        "INSERT INTO patients.contacts (patient_id, phone_number, is_primary) VALUES (%s, %s, true)",
        (pat["id"], sender_number), commit=True,
    )
    return pat["id"]


# ---------------------------------------------------------------- sessão/estado
def _load_history(sender_number: str) -> list[dict]:
    row = db.query(
        "SELECT context_data FROM conversations.state_history "
        "WHERE sender_number = %s ORDER BY created_at DESC LIMIT 1",
        (sender_number,), one=True,
    )
    if row and row.get("context_data"):
        data = row["context_data"]
        if isinstance(data, str):
            data = json.loads(data)
        return data.get("history", [])
    return []


def _save_history(sender_number: str, history: list[dict]):
    # mantém as últimas 20 mensagens
    trimmed = history[-20:]
    db.query(
        "INSERT INTO conversations.state_history (sender_number, state, context_data) "
        "VALUES (%s, %s, %s)",
        (sender_number, "chat", json.dumps({"history": trimmed}, default=str)),
        commit=True,
    )
    db.query(
        "INSERT INTO conversations.sessions (sender_number) "
        "SELECT %s WHERE NOT EXISTS "
        "(SELECT 1 FROM conversations.sessions WHERE sender_number = %s)",
        (sender_number, sender_number), commit=True,
    )


# ---------------------------------------------------------------- loop do agente
_TOOLS_SPEC = None


def _build_tools():
    from google.genai import types
    return [types.Tool(function_declarations=[
        types.FunctionDeclaration(
            name="listar_profissionais",
            description="Lista as profissionais que a paciente pode agendar.",
            parameters=types.Schema(type="OBJECT", properties={}),
        ),
        types.FunctionDeclaration(
            name="listar_servicos",
            description="Lista os serviços/atendimentos de uma profissional, com preço.",
            parameters=types.Schema(type="OBJECT", properties={
                "professional_id": types.Schema(type="INTEGER")}, required=["professional_id"]),
        ),
        types.FunctionDeclaration(
            name="consultar_horarios",
            description="Consulta horários livres de uma profissional em uma data (YYYY-MM-DD).",
            parameters=types.Schema(type="OBJECT", properties={
                "professional_id": types.Schema(type="INTEGER"),
                "data_iso": types.Schema(type="STRING")}, required=["professional_id", "data_iso"]),
        ),
        types.FunctionDeclaration(
            name="criar_agendamento",
            description="Cria o agendamento após confirmar todos os dados com a paciente.",
            parameters=types.Schema(type="OBJECT", properties={
                "professional_id": types.Schema(type="INTEGER"),
                "service_id": types.Schema(type="INTEGER"),
                "data_iso": types.Schema(type="STRING"),
                "hora": types.Schema(type="STRING", description="HH:MM"),
                "nome_paciente": types.Schema(type="STRING")},
                required=["professional_id", "service_id", "data_iso", "hora", "nome_paciente"]),
        ),
    ])]


_DISPATCH = {
    "listar_profissionais": lambda a, s: listar_profissionais(),
    "listar_servicos": lambda a, s: listar_servicos(a["professional_id"]),
    "consultar_horarios": lambda a, s: consultar_horarios(a["professional_id"], a["data_iso"]),
    "criar_agendamento": lambda a, s: criar_agendamento(
        s, a["professional_id"], a["service_id"], a["data_iso"], a["hora"], a["nome_paciente"]),
}


def process_message(sender_number: str, text: str) -> str:
    """Processa uma mensagem da paciente e devolve a resposta em texto."""
    from google import genai
    from google.genai import types

    if not _s.GEMINI_API_KEY:
        return ("Olá! Sou a atendente virtual da Materlux. No momento estou em "
                "configuração — a recepção falará com você em instantes. 🙏")

    client = genai.Client(api_key=_s.GEMINI_API_KEY)
    hoje = datetime.now(TZ)
    dias = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
    sys = _load_policy(hoje.strftime("%Y-%m-%d"), dias[hoje.weekday()])

    history = _load_history(sender_number)
    contents = []
    for h in history:
        contents.append(types.Content(role=h["role"],
                                      parts=[types.Part(text=h["text"])]))
    contents.append(types.Content(role="user", parts=[types.Part(text=text)]))

    cfg = types.GenerateContentConfig(system_instruction=sys, tools=_build_tools())

    final_text = ""
    for _ in range(6):  # limita as rodadas de tool-calling
        resp = client.models.generate_content(
            model=_s.GEMINI_MODEL, contents=contents, config=cfg)
        cand = resp.candidates[0]
        calls = [p.function_call for p in cand.content.parts if p.function_call]
        contents.append(cand.content)
        if not calls:
            final_text = resp.text or ""
            break
        tool_parts = []
        for fc in calls:
            args = dict(fc.args) if fc.args else {}
            try:
                result = _DISPATCH[fc.name](args, sender_number)
            except Exception as e:  # noqa
                result = {"erro": str(e)}
            tool_parts.append(types.Part(function_response=types.FunctionResponse(
                name=fc.name, response={"result": result})))
        contents.append(types.Content(role="tool", parts=tool_parts))

    history.append({"role": "user", "text": text})
    history.append({"role": "model", "text": final_text})
    _save_history(sender_number, history)
    return final_text or "Desculpe, pode repetir?"
