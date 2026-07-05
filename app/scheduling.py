"""Cálculo de horários livres — usado tanto pela interface quanto pelo agente.

Regras (herdadas do sistema antigo, corrigidas):
- A grade vem de medical.professional_schedules (day_of_week no padrão Postgres DOW:
  domingo=0 ... sábado=6).
- Slots de SLOT_MINUTES minutos.
- Um horário está ocupado se colide com um appointment cujo status NÃO é
  cancelado/expirado (status_id in 1,2,6,7 contam como ocupando a agenda).
- Bloqueios de medical.professional_timeoff removem faixas inteiras.
"""
from datetime import datetime, timedelta, date, time
from zoneinfo import ZoneInfo
from .config import get_settings
from . import db

_s = get_settings()
TZ = ZoneInfo(_s.CLINIC_TZ)

# status que NÃO ocupam a agenda (cancelados/expirados)
_FREE_STATUS = (3, 4, 5)


def _pg_dow(d: date) -> int:
    return (d.weekday() + 1) % 7  # Monday=0(py) -> 1 ; Sunday=6 -> 0


def professional_name(professional_id: int) -> str | None:
    row = db.query(
        "SELECT title, full_name FROM medical.professionals WHERE id = %s",
        (professional_id,), one=True,
    )
    if not row:
        return None
    return f"{(row['title'] or '').strip()} {row['full_name']}".strip()


def available_slots(professional_id: int, target: date) -> list[str]:
    """Retorna lista de horários 'HH:MM' livres para o profissional na data."""
    dow = _pg_dow(target)
    windows = db.query(
        "SELECT start_time, end_time FROM medical.professional_schedules "
        "WHERE professional_id = %s AND day_of_week = %s ORDER BY start_time",
        (professional_id, dow),
    )
    if not windows:
        return []

    day_start = datetime.combine(target, time(0, 0), tzinfo=TZ)
    day_end = day_start + timedelta(days=1)

    booked = db.query(
        "SELECT start_time, end_time FROM medical.appointments "
        "WHERE professional_id = %s AND start_time >= %s AND start_time < %s "
        "AND status_id <> ALL(%s)",
        (professional_id, day_start, day_end, list(_FREE_STATUS)),
    )
    timeoffs = db.query(
        "SELECT start_timestamp, end_timestamp FROM medical.professional_timeoff "
        "WHERE professional_id = %s AND start_timestamp < %s AND end_timestamp > %s",
        (professional_id, day_end, day_start),
    ) or []

    blocks = [(b["start_time"], b["end_time"]) for b in booked]
    blocks += [(t["start_timestamp"], t["end_timestamp"]) for t in timeoffs]

    now = datetime.now(TZ)
    step = timedelta(minutes=_s.SLOT_MINUTES)
    free: list[str] = []

    for w in windows:
        cur = datetime.combine(target, w["start_time"], tzinfo=TZ)
        win_end = datetime.combine(target, w["end_time"], tzinfo=TZ)
        while cur + step <= win_end:
            slot_end = cur + step
            if cur <= now:  # não oferecer horário no passado
                cur += step
                continue
            overlap = any(cur < be and slot_end > bs for bs, be in blocks)
            if not overlap:
                free.append(cur.strftime("%H:%M"))
            cur += step
    return free


def next_available_days(professional_id: int, from_date: date, days: int = 14,
                        max_days_with_slots: int = 5) -> list[dict]:
    """Varre os próximos dias e devolve os que têm horário livre."""
    out = []
    for i in range(days):
        d = from_date + timedelta(days=i)
        slots = available_slots(professional_id, d)
        if slots:
            out.append({"date": d.isoformat(), "slots": slots})
            if len(out) >= max_days_with_slots:
                break
    return out
