"""Cálculo de horários livres — usado pela interface e pelo agente.

Regras de slot (v2), derivadas de profissional + tipo de serviço:
- Dras. Isadora (id 4) e Cristina (id 12): 60 min, ancorado na hora cheia (H:00).
- Dr. Murilo (id 1):
    - consulta (service_type_id = 1): 45 min, ancorado em H:00.
    - US/retorno/procedimento (service_type_id 3 ou 4): 15 min, ancorado em H:45.
Slots que colidem com agendamentos (status não cancelado/expirado) ou com bloqueios
(professional_timeoff) são removidos; horários no passado também.
"""
from datetime import datetime, timedelta, date, time
from zoneinfo import ZoneInfo
from .config import get_settings
from . import db

_s = get_settings()
TZ = ZoneInfo(_s.CLINIC_TZ)

_FREE_STATUS = (3, 4, 5)  # cancelados/expirados não ocupam a agenda
# Profissionais com slot de 60 min ancorado na hora cheia (pediatria).
HOURLY_IDS = (4, 12)  # Isadora, Cristina


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


def _service_type(service_id) -> int | None:
    if not service_id:
        return None
    row = db.query("SELECT service_type_id FROM medical.services WHERE id = %s",
                   (service_id,), one=True)
    return row["service_type_id"] if row else None


def slot_rule(professional_id: int, service_id) -> tuple[int, int]:
    """Retorna (duração_min, minuto_âncora) do slot para o profissional/serviço."""
    if professional_id in HOURLY_IDS:
        return 60, 0
    st = _service_type(service_id)
    if st == 1:            # consulta
        return 45, 0
    return 15, 45          # US / retorno / procedimento (types 3 e 4)


def slot_minutes(professional_id: int, service_id) -> int:
    return slot_rule(professional_id, service_id)[0]


def _candidate_starts(win_start: datetime, win_end: datetime,
                      duration_min: int, anchor_min: int) -> list:
    step = timedelta(hours=1)
    dur = timedelta(minutes=duration_min)
    cur = win_start.replace(minute=anchor_min, second=0, microsecond=0)
    if cur < win_start:
        cur += step
    out = []
    while cur + dur <= win_end:
        out.append(cur)
        cur += step
    return out


def available_slots(professional_id: int, service_id, target: date) -> list:
    """Horários 'HH:MM' livres para o profissional/serviço na data."""
    dow = _pg_dow(target)
    windows = db.query(
        "SELECT start_time, end_time FROM medical.professional_schedules "
        "WHERE professional_id = %s AND day_of_week = %s ORDER BY start_time",
        (professional_id, dow),
    )
    if not windows:
        return []

    duration_min, anchor_min = slot_rule(professional_id, service_id)
    dur = timedelta(minutes=duration_min)

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
    free = []
    for w in windows:
        w_start = datetime.combine(target, w["start_time"], tzinfo=TZ)
        w_end = datetime.combine(target, w["end_time"], tzinfo=TZ)
        for cur in _candidate_starts(w_start, w_end, duration_min, anchor_min):
            slot_end = cur + dur
            if cur <= now:
                continue
            if any(cur < be and slot_end > bs for bs, be in blocks):
                continue
            free.append(cur.strftime("%H:%M"))

    seen = set()
    return [h for h in free if not (h in seen or seen.add(h))]


def next_available_days(professional_id: int, service_id, from_date: date,
                        days: int = 14, max_days_with_slots: int = 5) -> list:
    out = []
    for i in range(days):
        d = from_date + timedelta(days=i)
        slots = available_slots(professional_id, service_id, d)
        if slots:
            out.append({"date": d.isoformat(), "slots": slots})
            if len(out) >= max_days_with_slots:
                break
    return out
