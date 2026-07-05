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
        "SELECT s.id, s.name, ps.price FROM medical.professional_services ps "
        "JOIN medical.services s ON s.id = ps.service_id WHERE ps.professional_id = %s "
        "ORDER BY ps.display_order", (professional_id,),
    )
    return [{"id": r["id"], "nome": r["name"], "preco": float(r["price"])} for r in rows]


@router.get("/api/slots")
def slots(professional_id: int, data: str, user: dict = Depends(current_user)):
    return {"horarios": scheduling.available_slots(professional_id, date.fromisoformat(data))}


@router.get("/api/appointments")
def list_appointments(data: str, professional_id: int | None = None,
                      user: dict = Depends(current_user)):
    d = date.fromisoformat(data)
    day_start = datetime.combine(d, datetime.min.time(), tzinfo=TZ)
    day_end = day_start + timedelta(days=1)
    where = "a.start_time >= %s AND a.start_time < %s"
    params: list = [day_start, day_end]
    if professional_id:
        where += " AND a.professional_id = %s"
        params.append(professional_id)
    rows = db.query(
        f"""SELECT a.id, a.start_time, a.end_time, a.status_id, a.origem,
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
            "hora": r["start_time"].astimezone(TZ).strftime("%H:%M"),
            "paciente": f"{r['first_name']} {r['last_name']}".strip(),
            "cpf": r["cpf"] or "",
            "profissional": f"{(r['title'] or '').strip()} {r['profissional']}".strip(),
            "servico": r["servico"] or "",
            "status": r["status"],
            "origem": r["origem"],
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


@router.post("/api/appointments")
def create_appointment(body: NewAppointment, user: dict = Depends(current_user)):
    start = datetime.fromisoformat(f"{body.data}T{body.hora}:00").replace(tzinfo=TZ)
    if body.hora not in scheduling.available_slots(body.professional_id, start.date()):
        raise HTTPException(status_code=409, detail="Horário indisponível")
    end = start + timedelta(minutes=_s.SLOT_MINUTES)

    patient_id = body.patient_id
    if not patient_id:
        # CPF só com dígitos; reaproveita paciente existente pelo CPF (evita duplicar)
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


@router.post("/api/appointments/{appointment_id}/cancel")
def cancel_appointment(appointment_id: int, user: dict = Depends(current_user)):
    db.query("UPDATE medical.appointments SET status_id = 4 WHERE id = %s",
             (appointment_id,), commit=True)
    return {"ok": True}
