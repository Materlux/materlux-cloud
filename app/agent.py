"""Atendente virtual da Materlux — substitui o fluxo n8n de 519 nós.

Gemini com tool-calling. O modelo conversa em português, consulta horários
livres da agenda do Dr. Murilo e da Dra. Isadora e cria o agendamento.
A sessão/estado da conversa é persistida em conversations.sessions para dar
continuidade entre mensagens.
"""
import json
import os
import unicodedata
from pathlib import Path
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo
from .config import get_settings
from .validators import valida_cpf as _valida_cpf
from . import db, scheduling

_s = get_settings()
TZ = ZoneInfo(_s.CLINIC_TZ)

SYSTEM_PROMPT = """Você é a atendente virtual da Clínica Materlux (ginecologia, \
obstetrícia e pediatria). Fale em português do Brasil, de forma acolhedora, breve \
e objetiva. Seu trabalho é ajudar a paciente a AGENDAR ou CANCELAR uma consulta \
com o Dr. Murilo Ferraz ou com a Dra. Isadora Vencioneck. Para cancelar, o motivo \
é obrigatório: pergunte, e só chame cancelar_agendamento com o motivo informado.

Regras:
- Nunca invente horários. Sempre use as ferramentas para consultar a agenda real.
- Antes de confirmar, colete: nome da profissional desejada, tipo de atendimento \
(serviço), data, horário, nome completo e CPF da paciente (obrigatório — sem CPF \
válido não há agendamento). Se a paciente não souber o serviço, liste as opções da \
profissional escolhida.
- Confirme os dados com a paciente antes de chamar criar_agendamento.
- Ao confirmar, informe data e horário por extenso e diga que a recepção confirmará \
os detalhes de pagamento. Não fale sobre QR Code nem porta (desativado nesta fase).
- Se não houver horário, ofereça as próximas datas disponíveis.
- Se a paciente pedir para falar com uma pessoa, chame transferir_para_humano e \
avise que a recepção continuará a conversa neste mesmo WhatsApp.
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


def consultar_horarios(professional_id: int, service_id: int, data_iso: str) -> dict:
    d = date.fromisoformat(data_iso)
    slots = scheduling.available_slots(professional_id, service_id, d)
    if slots:
        return {"data": data_iso, "horarios": slots}
    prox = scheduling.next_available_days(professional_id, service_id, d + timedelta(days=1))
    return {"data": data_iso, "horarios": [], "proximas_datas": prox}


def criar_agendamento(sender_number: str, professional_id: int, service_id: int,
                      data_iso: str, hora: str, nome_paciente: str, cpf: str,
                      nome_servico: str = "") -> dict:
    cpf_digits = _valida_cpf(cpf)
    if not cpf_digits:
        return {"ok": False, "motivo": "cpf_invalido",
                "detalhe": ("O CPF informado não é válido. Peça para a paciente "
                            "conferir e enviar novamente os 11 dígitos.")}
    # trava: o serviço tem que ser da profissional escolhida (o modelo já confundiu
    # ids e agendou serviço de um profissional na agenda do outro)
    svc = db.query(
        "SELECT s.name FROM medical.professional_services ps "
        "JOIN medical.services s ON s.id = ps.service_id "
        "WHERE ps.professional_id = %s AND ps.service_id = %s",
        (professional_id, service_id), one=True,
    )
    if not svc:
        return {"ok": False, "motivo": "servico_invalido",
                "detalhe": ("Esse service_id não pertence a essa profissional. "
                            "Chame listar_servicos dela e use exatamente o "
                            "service_id retornado.")}
    # trava contra id trocado dentro da lista certa: o nome que o modelo diz estar
    # agendando tem que conferir com o nome real do service_id informado
    if not _servico_confere(nome_servico, svc["name"]):
        return {"ok": False, "motivo": "servico_nao_confere",
                "detalhe": (f"O service_id {service_id} corresponde a "
                            f"'{svc['name']}', não a '{nome_servico or '(vazio)'}'. "
                            "Localize na lista de listar_servicos o id do serviço "
                            "que a paciente pediu e chame criar_agendamento de novo "
                            "AGORA, nesta mesma resposta.")}
    start = datetime.fromisoformat(f"{data_iso}T{hora}:00").replace(tzinfo=TZ)
    # revalida que o horário ainda está livre (evita corrida)
    if hora not in scheduling.available_slots(professional_id, service_id, start.date()):
        return {"ok": False, "motivo": "horario_indisponivel"}
    end = start + timedelta(minutes=scheduling.slot_minutes(professional_id, service_id))

    patient_id = _get_or_create_patient(sender_number, nome_paciente, cpf_digits)
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
        "servico": svc["name"],
        "profissional": scheduling.professional_name(professional_id),
    }


def listar_agendamentos_futuros(sender_number: str) -> list[dict]:
    """Agendamentos ativos (pendente/confirmado) futuros das fichas deste telefone."""
    rows = db.query(
        "SELECT DISTINCT a.id, a.start_time, s.name AS servico, pr.title, "
        "pr.full_name, p.first_name, p.last_name "
        "FROM medical.appointments a "
        "JOIN patients.records p ON p.id = a.patient_id "
        "JOIN patients.contacts c ON c.patient_id = p.id "
        "JOIN medical.professionals pr ON pr.id = a.professional_id "
        "LEFT JOIN medical.services s ON s.id = a.service_id "
        "WHERE c.phone_number = %s AND a.status_id = ANY(%s) "
        "AND a.start_time > now() ORDER BY a.start_time",
        (sender_number, [1, 2]),
    )
    return [{
        "appointment_id": r["id"],
        "quando": r["start_time"].astimezone(TZ).strftime("%d/%m/%Y às %H:%M"),
        "servico": r["servico"] or "",
        "profissional": f"{(r['title'] or '').strip()} {r['full_name']}".strip(),
        "paciente": f"{r['first_name']} {r['last_name']}".strip(),
    } for r in rows]


def cancelar_agendamento(sender_number: str, appointment_id: int, motivo: str) -> dict:
    motivo = " ".join((motivo or "").split())
    if len(motivo) < 3:
        return {"ok": False, "motivo_recusa": "motivo_obrigatorio",
                "detalhe": ("O motivo do cancelamento é obrigatório. Pergunte à "
                            "paciente por que ela precisa cancelar antes de chamar "
                            "esta ferramenta.")}
    # só cancela agendamento vinculado a uma ficha deste telefone
    r = db.query(
        "SELECT a.id, a.start_time, a.status_id FROM medical.appointments a "
        "JOIN patients.contacts c ON c.patient_id = a.patient_id "
        "WHERE a.id = %s AND c.phone_number = %s",
        (appointment_id, sender_number), one=True,
    )
    if not r:
        return {"ok": False, "motivo_recusa": "agendamento_nao_encontrado",
                "detalhe": ("Não há agendamento com esse appointment_id para este "
                            "número — você provavelmente usou um id errado. Os "
                            "agendamentos ativos reais deste número estão em "
                            "'ativos'; use o appointment_id EXATO de lá."),
                "ativos": listar_agendamentos_futuros(sender_number)}
    quando = r["start_time"].astimezone(TZ).strftime("%d/%m/%Y às %H:%M")
    if r["status_id"] in (3, 4, 5):
        return {"ok": True, "ja_estava_cancelado": True, "cancelado": quando,
                "detalhe": ("Esse agendamento JÁ está cancelado — não repita a "
                            "chamada; apenas confirme à paciente que está tudo "
                            "certo, o cancelamento já consta no sistema.")}
    if r["status_id"] not in (1, 2):
        return {"ok": False, "motivo_recusa": "nao_cancelavel",
                "detalhe": "Esse agendamento já foi realizado; não dá para cancelar."}
    db.query(
        "UPDATE medical.appointments SET status_id = 3, motivo_cancelamento = %s "
        "WHERE id = %s", (motivo, appointment_id), commit=True,
    )
    return {"ok": True, "cancelado": quando}


def _norm_name(s: str) -> str:
    return " ".join((s or "").lower().split())


_STOPWORDS = {"de", "da", "do", "das", "dos", "e", "a", "o", "para", "com"}


def _tokens(s: str) -> set[str]:
    """Palavras significativas, sem acentos/pontuação — p/ comparar nomes de serviço."""
    s = unicodedata.normalize("NFD", (s or "").lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    for p in ".-/()":
        s = s.replace(p, " ")
    return {t for t in s.split() if t and t not in _STOPWORDS}


def _servico_confere(informado: str, real: str) -> bool:
    ti, tr = _tokens(informado), _tokens(real)
    if not ti:
        return False
    if ti == tr:
        return True
    if "on" in (ti ^ tr):
        # 'On' distingue teleatendimento de presencial — aí só vale nome exato
        return False
    return ti <= tr or tr <= ti


def _get_or_create_patient(sender_number: str, nome: str, cpf: str) -> int:
    """Encontra a paciente pelo CPF; em segundo caso, por telefone E nome.

    O CPF (já validado, 11 dígitos) é o identificador confiável — é único em
    patients.records (records_cpf_key). Se existe cadastro com esse CPF, é ela.
    Sem cadastro por CPF, tentamos telefone+nome (fluxo antigo) e aproveitamos
    para gravar o CPF na ficha se ela ainda não tiver; um cadastro com CPF
    DIFERENTE nunca é reaproveitado, mesmo que telefone e nome batam. Em último
    caso criamos cadastro novo já com o CPF.
    """
    achado = db.query(
        "SELECT id FROM patients.records WHERE cpf = %s", (cpf,), one=True,
    )
    existentes = db.query(
        "SELECT p.id, p.first_name, p.last_name, p.cpf FROM patients.contacts c "
        "JOIN patients.records p ON p.id = c.patient_id WHERE c.phone_number = %s",
        (sender_number,),
    )
    if achado:
        # garante que este telefone fique vinculado à ficha encontrada
        if achado["id"] not in {r["id"] for r in existentes}:
            db.query(
                "INSERT INTO patients.contacts (patient_id, phone_number, is_primary) "
                "VALUES (%s, %s, %s)",
                (achado["id"], sender_number, len(existentes) == 0), commit=True,
            )
        return achado["id"]

    nome_norm = _norm_name(nome)
    if nome_norm:
        for r in existentes:
            if r["cpf"] and r["cpf"] != cpf:
                continue
            full = _norm_name(f"{r['first_name']} {r['last_name']}")
            if full and (nome_norm == full or nome_norm in full or full in nome_norm):
                if not r["cpf"]:
                    db.query("UPDATE patients.records SET cpf = %s WHERE id = %s",
                             (cpf, r["id"]), commit=True)
                return r["id"]

    partes = (nome or "Paciente WhatsApp").strip().split(" ", 1)
    first, last = partes[0], (partes[1] if len(partes) > 1 else "")
    pat = db.query(
        "INSERT INTO patients.records (first_name, last_name, cpf) VALUES (%s, %s, %s) "
        "ON CONFLICT (cpf) DO UPDATE SET cpf = EXCLUDED.cpf RETURNING id",
        (first, last, cpf), one=True, commit=True,
    )
    db.query(
        "INSERT INTO patients.contacts (patient_id, phone_number, is_primary) VALUES (%s, %s, %s)",
        (pat["id"], sender_number, len(existentes) == 0), commit=True,
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


# ------------------------------------------------------------ transbordo humano
_HANDOFF_HOURS = 12  # devolução automática ao bot depois deste tempo pausado


def get_atendimento_status(sender_number: str) -> str:
    """'bot' ou 'humano'. Aplica a devolução automática após _HANDOFF_HOURS."""
    row = db.query(
        "SELECT atendimento_status, pausado_em FROM conversations.sessions "
        "WHERE sender_number = %s", (sender_number,), one=True,
    )
    if not row or row["atendimento_status"] != "humano":
        return "bot"
    if row["pausado_em"] and \
            datetime.now(TZ) - row["pausado_em"] > timedelta(hours=_HANDOFF_HOURS):
        set_atendimento_status(sender_number, "bot")
        return "bot"
    return "humano"


def set_atendimento_status(sender_number: str, status: str, por: str | None = None):
    db.query(
        "INSERT INTO conversations.sessions (sender_number) "
        "SELECT %s WHERE NOT EXISTS "
        "(SELECT 1 FROM conversations.sessions WHERE sender_number = %s)",
        (sender_number, sender_number), commit=True,
    )
    pausado = status == "humano"
    db.query(
        "UPDATE conversations.sessions SET atendimento_status = %s, "
        "pausado_em = %s, pausado_por = %s WHERE sender_number = %s",
        (status, datetime.now(TZ) if pausado else None,
         (por or None) if pausado else None, sender_number), commit=True,
    )


def log_paused_message(sender_number: str, text: str):
    """Guarda a mensagem recebida durante atendimento humano — o bot fica em
    silêncio, mas mantém o contexto para quando a conversa voltar a ele."""
    history = _load_history(sender_number)
    history.append({"role": "user", "text": text})
    _save_history(sender_number, history)


def transferir_para_humano(sender_number: str) -> dict:
    set_atendimento_status(sender_number, "humano", "bot")
    return {"ok": True,
            "detalhe": ("Transferido: a recepção continuará a conversa neste mesmo "
                        "WhatsApp. Despeça-se avisando isso à paciente (e que ela "
                        "também pode ligar para 27999949612, 8h às 17h).")}


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
            description=("Consulta horários livres de uma profissional para um serviço "
                         "específico em uma data (YYYY-MM-DD). A duração do horário varia "
                         "conforme o profissional e o tipo de serviço."),
            parameters=types.Schema(type="OBJECT", properties={
                "professional_id": types.Schema(type="INTEGER"),
                "service_id": types.Schema(type="INTEGER"),
                "data_iso": types.Schema(type="STRING")},
                required=["professional_id", "service_id", "data_iso"]),
        ),
        types.FunctionDeclaration(
            name="criar_agendamento",
            description=("Cria o agendamento após confirmar todos os dados com a "
                         "paciente. O CPF é obrigatório e é validado; se vier "
                         "inválido, a ferramenta recusa com motivo cpf_invalido."),
            parameters=types.Schema(type="OBJECT", properties={
                "professional_id": types.Schema(type="INTEGER"),
                "service_id": types.Schema(type="INTEGER"),
                "data_iso": types.Schema(type="STRING"),
                "hora": types.Schema(type="STRING", description="HH:MM"),
                "nome_paciente": types.Schema(type="STRING",
                                              description="Nome completo da paciente"),
                "cpf": types.Schema(type="STRING",
                                    description="CPF da paciente, 11 dígitos"),
                "nome_servico": types.Schema(
                    type="STRING",
                    description=("Nome do serviço EXATAMENTE como retornado por "
                                 "listar_servicos — é conferido contra o "
                                 "service_id"))},
                required=["professional_id", "service_id", "data_iso", "hora",
                          "nome_paciente", "cpf", "nome_servico"]),
        ),
        types.FunctionDeclaration(
            name="transferir_para_humano",
            description=("Transfere a conversa para a recepção (atendente humana): "
                         "você fica em silêncio e a recepção responde neste mesmo "
                         "WhatsApp. Use quando a paciente pedir para falar com uma "
                         "pessoa, houver reclamação, ou o assunto fugir do que você "
                         "resolve com segurança."),
            parameters=types.Schema(type="OBJECT", properties={}),
        ),
        types.FunctionDeclaration(
            name="listar_agendamentos_futuros",
            description=("Lista os agendamentos futuros ainda ativos (pendentes ou "
                         "confirmados) vinculados ao WhatsApp da paciente. Use antes "
                         "de cancelar, para identificar qual agendamento ela quer "
                         "cancelar."),
            parameters=types.Schema(type="OBJECT", properties={}),
        ),
        types.FunctionDeclaration(
            name="cancelar_agendamento",
            description=("Cancela um agendamento da paciente. O MOTIVO do "
                         "cancelamento é obrigatório — pergunte à paciente antes; "
                         "se vier vazio, a ferramenta recusa."),
            parameters=types.Schema(type="OBJECT", properties={
                "appointment_id": types.Schema(type="INTEGER"),
                "motivo": types.Schema(
                    type="STRING",
                    description="Motivo do cancelamento informado pela paciente")},
                required=["appointment_id", "motivo"]),
        ),
    ])]


_DISPATCH = {
    "listar_profissionais": lambda a, s: listar_profissionais(),
    "listar_servicos": lambda a, s: listar_servicos(a["professional_id"]),
    "consultar_horarios": lambda a, s: consultar_horarios(
        a["professional_id"], a["service_id"], a["data_iso"]),
    "criar_agendamento": lambda a, s: criar_agendamento(
        s, a["professional_id"], a["service_id"], a["data_iso"], a["hora"],
        a["nome_paciente"], a.get("cpf", ""), a.get("nome_servico", "")),
    "transferir_para_humano": lambda a, s: transferir_para_humano(s),
    "listar_agendamentos_futuros": lambda a, s: listar_agendamentos_futuros(s),
    "cancelar_agendamento": lambda a, s: cancelar_agendamento(
        s, a["appointment_id"], a.get("motivo", "")),
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
    profs_ctx = "; ".join(f"{p['nome']}=id {p['id']}" for p in listar_profissionais())
    sys += ("\n\n[Contexto técnico] Profissionais que você pode agendar e seus IDs: "
            f"{profs_ctx}. Interprete datas no formato dia/mês (Brasil). Sempre chame "
            "consultar_horarios com o id correto do profissional; nunca invente id, "
            "data nem horário. Use SEMPRE o service_id retornado por listar_servicos "
            "da MESMA profissional que vai atender — nunca um id de memória ou de "
            "outra profissional. Ao confirmar, repita o nome do serviço devolvido "
            "pela ferramenta. REGRA INVIOLÁVEL: agendar e cancelar só acontecem de "
            "verdade quando você CHAMA a ferramenta (criar_agendamento / "
            "cancelar_agendamento) e ela responde ok=true. Nunca afirme à paciente "
            "que algo foi agendado ou cancelado sem ter feito a chamada e recebido "
            "ok=true nesta conversa; se a ferramenta recusar, diga o que faltou e "
            "resolva antes de confirmar. Você só consegue agir DURANTE a geração da "
            "resposta atual: se precisar consultar ou corrigir algo, chame a "
            "ferramenta imediatamente, antes de escrever a resposta final. NUNCA "
            "termine dizendo 'aguarde um momento' ou prometendo que vai fazer algo "
            "em seguida — não existe 'em seguida'; faça agora ou peça a informação "
            "que falta à paciente.")

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
                print(f"[agent] tool={fc.name} args={args}", flush=True)
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
