from zoneinfo import ZoneInfo
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from ..security import current_user
from ..config import get_settings
from .. import db

router = APIRouter()
TZ = ZoneInfo(get_settings().CLINIC_TZ)


@router.get("/api/patients/search")
def search(name: str, user: dict = Depends(current_user)):
    # só casa por CPF quando o termo tem dígitos; senão evita casar com
    # registros de CPF vazio (None nunca satisfaz a igualdade)
    cpf_digits = "".join(c for c in name if c.isdigit()) or None
    rows = db.query(
        "SELECT id, first_name, last_name, cpf, email FROM patients.records "
        "WHERE lower(first_name || ' ' || last_name) LIKE %s OR cpf = %s "
        "ORDER BY first_name LIMIT 25",
        (f"%{name.lower()}%", cpf_digits),
    )
    return [{"id": r["id"], "nome": f"{r['first_name']} {r['last_name']}".strip(),
             "cpf": r["cpf"] or "", "email": r["email"] or ""} for r in rows]


class NewPatient(BaseModel):
    nome: str
    email: str
    telefone: str
    cpf: str
    birth_date: str            # YYYY-MM-DD
    cep: str | None = None
    address_street: str | None = None
    address_neighbourhood: str | None = None
    address_city: str | None = None
    address_state: str | None = None
    address_number: str | None = None
    address_complement: str | None = None


@router.post("/api/patients")
def create_patient(body: NewPatient, user: dict = Depends(current_user)):
    obrig = (("nome", body.nome), ("e-mail", body.email), ("telefone", body.telefone),
             ("CPF", body.cpf), ("data de nascimento", body.birth_date),
             ("endereço", body.address_street), ("número", body.address_number))
    for campo, val in obrig:
        if not (val or "").strip():
            raise HTTPException(status_code=400, detail=f"Campo obrigatório: {campo}")
    cpf_clean = "".join(c for c in body.cpf if c.isdigit())
    if len(cpf_clean) != 11:
        raise HTTPException(status_code=400, detail="CPF inválido (11 dígitos)")
    if db.query("SELECT id FROM patients.records WHERE cpf = %s", (cpf_clean,), one=True):
        raise HTTPException(status_code=409, detail="Já existe paciente com este CPF")

    partes = body.nome.strip().split(" ", 1)
    first, last = partes[0], (partes[1] if len(partes) > 1 else "")
    cep_clean = "".join(c for c in (body.cep or "") if c.isdigit()) or None

    pat = db.query(
        "INSERT INTO patients.records "
        "(first_name, last_name, email, cpf, birth_date, address_street, "
        " address_neighbourhood, address_city, address_state, address_zipcode, "
        " address_number, address_complement) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
        (first, last, body.email.strip(), cpf_clean, body.birth_date,
         body.address_street, body.address_neighbourhood, body.address_city,
         body.address_state, cep_clean, body.address_number, body.address_complement),
        one=True, commit=True,
    )
    pid = pat["id"]
    tel = "".join(c for c in body.telefone if c.isdigit())
    if tel:
        db.query("INSERT INTO patients.contacts (patient_id, phone_number, is_primary) "
                 "VALUES (%s, %s, true)", (pid, tel), commit=True)
    return {"ok": True, "patient_id": pid}


@router.get("/api/patients/{patient_id}/appointments")
def patient_appointments(patient_id: int, user: dict = Depends(current_user)):
    rows = db.query(
        "SELECT a.id, a.start_time, st.status_name AS status, s.name AS servico, "
        "pr.title, pr.full_name AS profissional "
        "FROM medical.appointments a "
        "JOIN medical.appointment_statuses st ON st.id = a.status_id "
        "LEFT JOIN medical.services s ON s.id = a.service_id "
        "JOIN medical.professionals pr ON pr.id = a.professional_id "
        "WHERE a.patient_id = %s ORDER BY a.start_time DESC",
        (patient_id,),
    )
    return [{
        "id": r["id"],
        "data": r["start_time"].astimezone(TZ).strftime("%d/%m/%Y %H:%M"),
        "servico": r["servico"] or "",
        "profissional": f"{(r['title'] or '').strip()} {r['profissional']}".strip(),
        "status": r["status"],
    } for r in rows]
