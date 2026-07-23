"""Tarefas agendadas (chamadas pelo Cloud Scheduler, não por humanos).

Protegidas por um token no header X-Tasks-Token, comparado com a env TASKS_TOKEN.
Sem TASKS_TOKEN configurado, os endpoints ficam desligados (503).

- POST /tasks/lembretes : envia o lembrete da véspera às pacientes com consulta
  amanhã (status ativo, ainda sem lembrete). Idempotente: grava lembrete_enviado_em.
"""
import hmac
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Header, HTTPException
from ..config import get_settings
from .. import db
from .whatsapp import send_reply

router = APIRouter()
_s = get_settings()
TZ = ZoneInfo(_s.CLINIC_TZ)

_DIAS = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira",
         "sexta-feira", "sábado", "domingo"]

_MSG = ("Olá, {nome}! Estamos ansiosos para te receber na Materlux. 🤰 "
        "Seu atendimento com {profissional} será amanhã, {data}, às {hora}. "
        "📍 Localização: Materlux - Av. Carlos Gomes de Sá, 100, Mata da Praia, "
        "Vitória. Lembrete: chegue com 15 min de antecedência e a recepção vai te "
        "ajudar com todos os detalhes.")


def _auth(token: str | None):
    if not _s.TASKS_TOKEN:
        raise HTTPException(status_code=503, detail="Tarefas agendadas desativadas")
    if not token or not hmac.compare_digest(token, _s.TASKS_TOKEN):
        raise HTTPException(status_code=401, detail="Token inválido")


def _normaliza_fone(fone: str | None) -> str | None:
    """Garante DDI 55 (Z-API espera o número com código do país)."""
    d = "".join(c for c in (fone or "") if c.isdigit())
    if len(d) in (10, 11):          # DDD + número, sem país → prefixa 55
        return "55" + d
    if len(d) in (12, 13) and d.startswith("55"):
        return d
    return d or None


@router.post("/tasks/lembretes")
def enviar_lembretes(x_tasks_token: str | None = Header(default=None)):
    _auth(x_tasks_token)
    hoje = datetime.now(TZ).date()
    amanha = hoje + timedelta(days=1)
    ini = datetime.combine(amanha, time.min, tzinfo=TZ)
    fim = ini + timedelta(days=1)

    rows = db.query(
        "SELECT a.id, a.start_time, p.first_name, "
        "pr.title, pr.full_name, "
        "(SELECT c.phone_number FROM patients.contacts c "
        " WHERE c.patient_id = p.id ORDER BY c.is_primary DESC NULLS LAST LIMIT 1) AS fone "
        "FROM medical.appointments a "
        "JOIN patients.records p ON p.id = a.patient_id "
        "JOIN medical.professionals pr ON pr.id = a.professional_id "
        "WHERE a.start_time >= %s AND a.start_time < %s "
        "AND a.status_id = ANY(%s) AND a.lembrete_enviado_em IS NULL "
        "ORDER BY a.start_time",
        (ini, fim, [1, 2]),
    )

    enviados, falhas, sem_fone = 0, 0, 0
    for r in rows:
        fone = _normaliza_fone(r["fone"])
        if not fone:
            sem_fone += 1
            continue
        dt = r["start_time"].astimezone(TZ)
        prof = f"{(r['title'] or '').strip()} {r['full_name']}".strip()
        msg = _MSG.format(
            nome=(r["first_name"] or "").strip() or "paciente",
            profissional=prof,
            data=f"{_DIAS[dt.weekday()]}, {dt.strftime('%d/%m')}",
            hora=dt.strftime("%H:%M"),
        )
        try:
            send_reply(fone, msg)
            db.query(
                "UPDATE medical.appointments SET lembrete_enviado_em = now() "
                "WHERE id = %s", (r["id"],), commit=True,
            )
            enviados += 1
        except Exception as e:  # noqa
            print(f"[lembrete] falha appt={r['id']} fone={fone}: {e}", flush=True)
            falhas += 1

    resumo = {"data_alvo": amanha.isoformat(), "candidatos": len(rows),
              "enviados": enviados, "falhas": falhas, "sem_telefone": sem_fone}
    print(f"[lembrete] {resumo}", flush=True)
    return resumo
