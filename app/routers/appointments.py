from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from ..security import current_user
from ..config import get_settings
from .. import db, scheduling

router = APIRouter()
_s = get_settings()
TZ = ZoneInfo(_s.CLINIC_TZ)


@router.get("/api/professionals")
def professionals(user: dict = Depends(current_user)):
    rows = db.query(
        "SELECT id, title, full_name FROM medical.professionals "
        "WHERE id = ANY(%s) AND is_active = true ORDER BY id",
        (_s.BOOKABLE_PROFESSIONAL_IDS,),
    )
    return [{"id": r["id"], "nome": f"{(r['title'] or '').strip()} {r['full_name']}".strip()}
            for r in rows]


@router.get("/api/services")
def services(professional_id: int, user: dict = Depends(current_user)):
    rows = db.query(
        "SELECT s.id, s.name, s.service_type_id, ps.price "
        "FROM medical.professional_services ps "
        "JOIN medical.services s ON s.id = ps.service_id WHERE ps.professional_id = %s "
        "ORDER BY ps.display_order", (professional_id,),
    )
    return [{"id": r["id"], "nome": r["name"], "preco": float(r["price"]),
             "service_type_id": r["service_type_id"]} for r in rows]


@router.get("/api/slots")
def slots(professional_id: int, service_id: int, data: str,
          user: dict = Depends(current_user)):
    d = date.fromisoformat(data)
    return {"horarios": scheduling.available_slots(professional_id, service_id, d),
            "duracao_min": scheduling.slot_minutes(professional_id, service_id)}


_CANCELLED_STATUSES = [3, 4, 5]  # cancelada (paciente/clínica) e expirado


@router.get("/api/appointments")
def list_appointments(data: str, professional_id: int | None = None,
                      data_fim: str | None = None, cancelados: bool = False,
                      user: dict = Depends(current_user)):
    d = date.fromisoformat(data)
    day_start = datetime.combine(d, datetime.min.time(), tzinfo=TZ)
    d_fim = date.fromisoformat(data_fim) if data_fim else d
    day_end = datetime.combine(d_fim, datetime.min.time(), tzinfo=TZ) + timedelta(days=1)
    where = "a.start_time >= %s AND a.start_time < %s"
    params: list = [day_start, day_end]
    if cancelados:
        # aba Cancelamentos: só os que saíram da agenda
        where += " AND a.status_id = ANY(%s)"
    else:
        # agenda principal: cancelados/expirados não aparecem
        where += " AND a.status_id <> ALL(%s)"
    params.append(_CANCELLED_STATUSES)
    if professional_id:
        where += " AND a.professional_id = %s"
        params.append(professional_id)
    rows = db.query(
        f"""SELECT a.id, a.start_time, a.end_time, a.status_id, a.origem,
                   a.forma_pagamento, a.valor_pago, a.observacoes,
                   st.status_name AS status,
                   p.first_name, p.last_name, p.cpf,
                   pr.full_name AS profissional, pr.title,
                   s.name AS servico
            FROM medical.appointments a
            JOIN medical.appointment_statuses st ON st.id = a.status_id
            JOIN patients.records p ON p.id = a.patient_id
            JOIN medical.professionals pr ON pr.id = a.professional_id
            LEFT JOIN medical.services s ON s.id = a.service_id
            WHERE {where} ORDER BY a.start_time""",
        tuple(params),
    )
    out = []
    for r in rows:
        out.append({
            "id": r["id"],
            "data": r["start_time"].astimezone(TZ).strftime("%d/%m/%Y"),
            "hora": r["start_time"].astimezone(TZ).strftime("%H:%M"),
            "paciente": f"{r['first_name']} {r['last_name']}".strip(),
            "cpf": r["cpf"] or "",
            "profissional": f"{(r['title'] or '').strip()} {r['profissional']}".strip(),
            "servico": r["servico"] or "",
            "status": r["status"],
            "origem": r["origem"],
            "forma_pagamento": r["forma_pagamento"] or "",
            "valor_pago": float(r["valor_pago"]) if r["valor_pago"] is not None else None,
            "observacoes": r["observacoes"] or "",
        })
    return out


class NewAppointment(BaseModel):
    professional_id: int
    service_id: int
    patient_id: int | None = None
    first_name: str | None = None
    last_name: str | None = None
    cpf: str | None = None
    phone: str | None = None
    data: str          # YYYY-MM-DD
    hora: str          # HH:MM


def _start_end(professional_id, service_id, data, hora):
    start = datetime.fromisoformat(f"{data}T{hora}:00").replace(tzinfo=TZ)
    end = start + timedelta(minutes=scheduling.slot_minutes(professional_id, service_id))
    return start, end


@router.post("/api/appointments")
def create_appointment(body: NewAppointment, user: dict = Depends(current_user)):
    if body.hora not in scheduling.available_slots(
            body.professional_id, body.service_id, date.fromisoformat(body.data)):
        raise HTTPException(status_code=409, detail="Horário indisponível")
    start, end = _start_end(body.professional_id, body.service_id, body.data, body.hora)

    patient_id = body.patient_id
    if not patient_id:
        cpf_clean = "".join(c for c in (body.cpf or "") if c.isdigit()) or None
        pat = db.query(
            "INSERT INTO patients.records (first_name, last_name, cpf) "
            "VALUES (%s, %s, %s) ON CONFLICT (cpf) DO UPDATE SET cpf = EXCLUDED.cpf "
            "RETURNING id",
            (body.first_name or "Paciente", body.last_name or "", cpf_clean),
            one=True, commit=True,
        )
        patient_id = pat["id"]

    row = db.query(
        "INSERT INTO medical.appointments "
        "(professional_id, patient_id, service_id, status_id, start_time, end_time, origem) "
        "VALUES (%s, %s, %s, 2, %s, %s, 'secretaria') RETURNING id",
        (body.professional_id, patient_id, body.service_id, start, end),
        one=True, commit=True,
    )
    return {"ok": True, "appointment_id": row["id"]}


@router.get("/api/appointments/{appointment_id}")
def get_appointment(appointment_id: int, user: dict = Depends(current_user)):
    r = db.query(
        "SELECT a.id, a.professional_id, a.service_id, a.start_time, a.status_id, "
        "p.first_name, p.last_name, p.cpf FROM medical.appointments a "
        "JOIN patients.records p ON p.id = a.patient_id WHERE a.id = %s",
        (appointment_id,), one=True,
    )
    if not r:
        raise HTTPException(status_code=404, detail="Agendamento não encontrado")
    return {
        "id": r["id"], "professional_id": r["professional_id"],
        "service_id": r["service_id"], "status_id": r["status_id"],
        "data": r["start_time"].astimezone(TZ).strftime("%Y-%m-%d"),
        "hora": r["start_time"].astimezone(TZ).strftime("%H:%M"),
        "paciente": f"{r['first_name']} {r['last_name']}".strip(), "cpf": r["cpf"] or "",
    }


class Reschedule(BaseModel):
    professional_id: int
    service_id: int
    data: str
    hora: str


@router.put("/api/appointments/{appointment_id}")
def reschedule(appointment_id: int, body: Reschedule,
               user: dict = Depends(current_user)):
    cur = db.query(
        "SELECT professional_id, start_time FROM medical.appointments WHERE id = %s",
        (appointment_id,), one=True)
    if not cur:
        raise HTTPException(status_code=404, detail="Agendamento não encontrado")
    same = (body.professional_id == cur["professional_id"]
            and body.data == cur["start_time"].astimezone(TZ).strftime("%Y-%m-%d")
            and body.hora == cur["start_time"].astimezone(TZ).strftime("%H:%M"))
    free = scheduling.available_slots(body.professional_id, body.service_id,
                                      date.fromisoformat(body.data))
    if body.hora not in free and not same:
        raise HTTPException(status_code=409, detail="Horário indisponível")
    start, end = _start_end(body.professional_id, body.service_id, body.data, body.hora)
    db.query(
        "UPDATE medical.appointments SET professional_id=%s, service_id=%s, "
        "start_time=%s, end_time=%s WHERE id=%s",
        (body.professional_id, body.service_id, start, end, appointment_id),
        commit=True,
    )
    return {"ok": True}


class Financeiro(BaseModel):
    forma_pagamento: str | None = None
    valor_pago: float | None = None
    observacoes: str | None = None


@router.patch("/api/appointments/{appointment_id}/financeiro")
def set_financeiro(appointment_id: int, body: Financeiro,
                   user: dict = Depends(current_user)):
    forma = body.forma_pagamento
    if forma and forma not in _s.PAYMENT_METHODS:
        raise HTTPException(status_code=400, detail="Forma de pagamento inválida")
    db.query(
        "UPDATE medical.appointments SET forma_pagamento=%s, valor_pago=%s, "
        "observacoes=%s WHERE id=%s",
        (forma or None, body.valor_pago, body.observacoes, appointment_id),
        commit=True,
    )
    return {"ok": True}


@router.post("/api/appointments/{appointment_id}/cancel")
def cancel_appointment(appointment_id: int, user: dict = Depends(current_user)):
    db.query("UPDATE medical.appointments SET status_id = 4 WHERE id = %s",
             (appointment_id,), commit=True)
    return {"ok": True}


@router.get("/api/reports/revenue")
def revenue(start: str, end: str, forma_pagamento: str | None = None,
            professional_id: int | None = None, user: dict = Depends(current_user)):
    d0 = datetime.combine(date.fromisoformat(start), datetime.min.time(), tzinfo=TZ)
    d1 = datetime.combine(date.fromisoformat(end), datetime.min.time(), tzinfo=TZ) \
        + timedelta(days=1)
    where = "a.start_time >= %s AND a.start_time < %s AND a.valor_pago IS NOT NULL"
    params: list = [d0, d1]
    if forma_pagamento:
        where += " AND a.forma_pagamento = %s"
        params.append(forma_pagamento)
    if professional_id:
        where += " AND a.professional_id = %s"
        params.append(professional_id)
    rows = db.query(
        f"""SELECT pr.id, pr.title, pr.full_name,
                   COALESCE(SUM(a.valor_pago), 0) AS total,
                   COUNT(*) AS qtd
            FROM medical.appointments a
            JOIN medical.professionals pr ON pr.id = a.professional_id
            WHERE {where}
            GROUP BY pr.id, pr.title, pr.full_name
            ORDER BY total DESC""",
        tuple(params),
    )
    por_prof = [{
        "profissional": f"{(r['title'] or '').strip()} {r['full_name']}".strip(),
        "total": float(r["total"]), "qtd": r["qtd"],
    } for r in rows]
    total_geral = sum(p["total"] for p in por_prof)
    return {"por_profissional": por_prof, "total_geral": total_geral,
            "formas_pagamento": _s.PAYMENT_METHODS}
