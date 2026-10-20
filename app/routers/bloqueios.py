"""Bloqueios de agenda (folgas, reuniões, imprevistos) criados pela recepção.

Usa a tabela já existente medical.professional_timeoff — o cálculo de horários livres
(scheduling.available_slots) já a respeita, então a Malu, o painel e os agendamentos
manuais deixam de oferecer os horários bloqueados.

Regras: só datas avulsas (um dia por bloqueio), dia inteiro OU intervalo de horário,
e o bloqueio é RECUSADO se já houver agendamento ativo no período (a recepção remarca
as pacientes antes). Excluir o bloqueio libera os horários de novo.
"""
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo
import psycopg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from ..config import get_settings
from ..security import current_user
from .. import db

router = APIRouter()
_s = get_settings()
TZ = ZoneInfo(_s.CLINIC_TZ)

_CANCELLED_STATUSES = [3, 4, 5]  # cancelada (paciente/clínica) e expirado: não ocupam


class NewBloqueio(BaseModel):
    professional_id: int
    data: str                      # YYYY-MM-DD
    dia_inteiro: bool = True
    hora_inicio: str | None = None  # HH:MM (só se dia_inteiro = false)
    hora_fim: str | None = None


def _hora(s: str | None, campo: str) -> time:
    try:
        h, m = (s or "").strip().split(":")[:2]
        return time(int(h), int(m))
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail=f"{campo} inválida — use HH:MM.")


def _descricao(ini: datetime, fim: datetime) -> str:
    ini, fim = ini.astimezone(TZ), fim.astimezone(TZ)
    meia_noite = time(0, 0)
    if ini.time() == meia_noite and fim.time() == meia_noite and fim - ini == timedelta(days=1):
        return "Dia inteiro"
    if ini.date() == fim.date():
        return f"{ini:%H:%M} às {fim:%H:%M}"
    return f"{ini:%d/%m %H:%M} até {fim:%d/%m %H:%M}"


@router.get("/api/bloqueios")
def list_bloqueios(professional_id: int | None = None,
                   user: dict = Depends(current_user)):
    """Bloqueios que ainda não terminaram (do mais próximo ao mais distante)."""
    params: list = []
    where = "t.end_timestamp > now()"
    if professional_id:
        where += " AND t.professional_id = %s"
        params.append(professional_id)
    rows = db.query(
        "SELECT t.id, t.professional_id, t.start_timestamp, t.end_timestamp, "
        "pr.title, pr.full_name "
        "FROM medical.professional_timeoff t "
        "JOIN medical.professionals pr ON pr.id = t.professional_id "
        f"WHERE {where} ORDER BY t.start_timestamp LIMIT 200", tuple(params),
    )
    out = []
    for r in rows:
        ini = r["start_timestamp"].astimezone(TZ)
        out.append({
            "id": r["id"],
            "professional_id": r["professional_id"],
            "profissional": f"{(r['title'] or '').strip()} {r['full_name']}".strip(),
            "data": ini.strftime("%d/%m/%Y"),
            "dia_semana": ["segunda", "terça", "quarta", "quinta", "sexta", "sábado",
                           "domingo"][ini.weekday()],
            "periodo": _descricao(r["start_timestamp"], r["end_timestamp"]),
        })
    return out


def _insert(professional_id: int, ini: datetime, fim: datetime) -> int:
    sql = ("INSERT INTO medical.professional_timeoff "
           "(professional_id, start_timestamp, end_timestamp, reason) "
           "VALUES (%s, %s, %s, %s) RETURNING id")
    params = (professional_id, ini, fim, "Bloqueio da recepção (painel)")
    try:
        return db.query(sql, params, one=True, commit=True)["id"]
    except psycopg.errors.UniqueViolation:
        # sequência defasada do banco restaurado (ver CLAUDE.md): conserta e repete
        db.query(
            "SELECT setval(pg_get_serial_sequence('medical.professional_timeoff', 'id'), "
            "(SELECT COALESCE(max(id), 1) FROM medical.professional_timeoff))",
            commit=True)
        return db.query(sql, params, one=True, commit=True)["id"]


@router.post("/api/bloqueios")
def create_bloqueio(body: NewBloqueio, user: dict = Depends(current_user)):
    try:
        dia = date.fromisoformat(body.data)
    except ValueError:
        raise HTTPException(status_code=400, detail="Data inválida.")
    if dia < datetime.now(TZ).date():
        raise HTTPException(status_code=400, detail="Não é possível bloquear uma data que já passou.")
    if not db.query("SELECT 1 FROM medical.professionals WHERE id = %s",
                    (body.professional_id,), one=True):
        raise HTTPException(status_code=404, detail="Profissional não encontrado.")

    if body.dia_inteiro:
        ini = datetime.combine(dia, time(0, 0), tzinfo=TZ)
        fim = ini + timedelta(days=1)
    else:
        h_ini, h_fim = _hora(body.hora_inicio, "Hora inicial"), _hora(body.hora_fim, "Hora final")
        if h_fim <= h_ini:
            raise HTTPException(status_code=400, detail="A hora final precisa ser depois da hora inicial.")
        ini = datetime.combine(dia, h_ini, tzinfo=TZ)
        fim = datetime.combine(dia, h_fim, tzinfo=TZ)

    # a agenda do período precisa estar LIVRE: com agendamento ativo, não bloqueia
    conflitos = db.query(
        "SELECT a.start_time, p.first_name, p.last_name "
        "FROM medical.appointments a "
        "JOIN patients.records p ON p.id = a.patient_id "
        "WHERE a.professional_id = %s AND a.status_id <> ALL(%s) "
        "AND a.start_time < %s "
        "AND COALESCE(a.end_time, a.start_time + interval '15 minutes') > %s "
        "ORDER BY a.start_time",
        (body.professional_id, _CANCELLED_STATUSES, fim, ini),
    )
    if conflitos:
        lista = "; ".join(
            f"{c['start_time'].astimezone(TZ):%H:%M} {c['first_name']} {c['last_name']}".strip()
            for c in conflitos[:10])
        mais = f" (e mais {len(conflitos) - 10})" if len(conflitos) > 10 else ""
        raise HTTPException(
            status_code=409,
            detail=(f"Existem {len(conflitos)} agendamento(s) neste período: {lista}{mais}. "
                    "Remarque essas pacientes (aba Editar agendamentos) e tente bloquear "
                    "de novo."))

    # já existe bloqueio cobrindo parte do período? evita duplicar
    if db.query(
        "SELECT 1 FROM medical.professional_timeoff WHERE professional_id = %s "
        "AND start_timestamp < %s AND end_timestamp > %s LIMIT 1",
        (body.professional_id, fim, ini), one=True,
    ):
        raise HTTPException(status_code=409,
                            detail="Já existe um bloqueio que cobre parte deste período. "
                                   "Exclua-o na lista abaixo antes de criar outro.")

    novo_id = _insert(body.professional_id, ini, fim)
    return {"ok": True, "id": novo_id, "periodo": _descricao(ini, fim)}


@router.delete("/api/bloqueios/{bloqueio_id}")
def delete_bloqueio(bloqueio_id: int, user: dict = Depends(current_user)):
    row = db.query("DELETE FROM medical.professional_timeoff WHERE id = %s RETURNING id",
                   (bloqueio_id,), one=True, commit=True)
    if not row:
        raise HTTPException(status_code=404, detail="Bloqueio não encontrado.")
    return {"ok": True}
