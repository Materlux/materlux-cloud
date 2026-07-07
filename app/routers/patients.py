from zoneinfo import ZoneInfo
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from ..security import current_user
from ..config import get_settings
from ..validators import valida_cpf
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
    cpf_clean = valida_cpf(body.cpf)
    if not cpf_clean:
        raise HTTPException(status_code=400,
                            detail="CPF inválido — confira os 11 dígitos")
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


@router.get("/api/patients/{patient_id}")
def get_patient(patient_id: int, user: dict = Depends(current_user)):
    r = db.query(
        "SELECT id, first_name, last_name, email, cpf, birth_date, address_street, "
        "address_neighbourhood, address_city, address_state, address_zipcode, "
        "address_number, address_complement FROM patients.records WHERE id = %s",
        (patient_id,), one=True,
    )
    if not r:
        raise HTTPException(status_code=404, detail="Paciente não encontrada")
    tel = db.query(
        "SELECT phone_number FROM patients.contacts WHERE patient_id = %s "
        "ORDER BY is_primary DESC LIMIT 1", (patient_id,), one=True,
    )
    return {
        "id": r["id"],
        "nome": f"{r['first_name']} {r['last_name']}".strip(),
        "email": r["email"] or "",
        "telefone": (tel or {}).get("phone_number") or "",
        "cpf": r["cpf"] or "",
        "birth_date": r["birth_date"].isoformat() if r["birth_date"] else "",
        "cep": r["address_zipcode"] or "",
        "address_street": r["address_street"] or "",
        "address_neighbourhood": r["address_neighbourhood"] or "",
        "address_city": r["address_city"] or "",
        "address_state": r["address_state"] or "",
        "address_number": r["address_number"] or "",
        "address_complement": r["address_complement"] or "",
    }


@router.put("/api/patients/{patient_id}")
def update_patient(patient_id: int, body: NewPatient,
                   user: dict = Depends(current_user)):
    if not db.query("SELECT id FROM patients.records WHERE id = %s",
                    (patient_id,), one=True):
        raise HTTPException(status_code=404, detail="Paciente não encontrada")
    # Na edição só nome e CPF são obrigatórios: cadastros antigos restaurados não
    # têm e-mail/nascimento/endereço e precisam poder ser corrigidos assim mesmo.
    if not body.nome.strip():
        raise HTTPException(status_code=400, detail="Campo obrigatório: nome")
    cpf_clean = valida_cpf(body.cpf)
    if not cpf_clean:
        raise HTTPException(status_code=400,
                            detail="CPF inválido — confira os 11 dígitos")
    if db.query("SELECT id FROM patients.records WHERE cpf = %s AND id <> %s",
                (cpf_clean, patient_id), one=True):
        raise HTTPException(status_code=409,
                            detail="Já existe OUTRA paciente com este CPF")

    partes = body.nome.strip().split(" ", 1)
    first, last = partes[0], (partes[1] if len(partes) > 1 else "")
    cep_clean = "".join(c for c in (body.cep or "") if c.isdigit()) or None
    vazio = lambda s: (s or "").strip() or None  # noqa: E731
    db.query(
        "UPDATE patients.records SET first_name=%s, last_name=%s, email=%s, cpf=%s, "
        "birth_date=%s, address_street=%s, address_neighbourhood=%s, address_city=%s, "
        "address_state=%s, address_zipcode=%s, address_number=%s, address_complement=%s "
        "WHERE id=%s",
        (first, last, vazio(body.email), cpf_clean,
         vazio(body.birth_date), vazio(body.address_street),
         vazio(body.address_neighbourhood), vazio(body.address_city),
         vazio(body.address_state), cep_clean, vazio(body.address_number),
         vazio(body.address_complement), patient_id),
        commit=True,
    )
    tel = "".join(c for c in body.telefone if c.isdigit())
    if tel:
        atual = db.query(
            "SELECT phone_number FROM patients.contacts WHERE patient_id = %s "
            "ORDER BY is_primary DESC LIMIT 1", (patient_id,), one=True,
        )
        if atual:
            db.query("UPDATE patients.contacts SET phone_number = %s "
                     "WHERE patient_id = %s AND phone_number = %s",
                     (tel, patient_id, atual["phone_number"]), commit=True)
        else:
            db.query("INSERT INTO patients.contacts (patient_id, phone_number, is_primary) "
                     "VALUES (%s, %s, true)", (patient_id, tel), commit=True)
    return {"ok": True, "patient_id": patient_id}


@router.delete("/api/patients/{patient_id}")
def delete_patient(patient_id: int, user: dict = Depends(current_user)):
    if not db.query("SELECT id FROM patients.records WHERE id = %s",
                    (patient_id,), one=True):
        raise HTTPException(status_code=404, detail="Paciente não encontrada")
    n_ag = db.query("SELECT count(*) AS n FROM medical.appointments WHERE patient_id = %s",
                    (patient_id,), one=True)["n"]
    n_ev = db.query("SELECT count(*) AS n FROM medical.clinical_evolutions "
                    "WHERE patient_id = %s", (patient_id,), one=True)["n"]
    if n_ag or n_ev:
        raise HTTPException(
            status_code=409,
            detail=(f"Não é possível excluir: a paciente tem {n_ag} agendamento(s) "
                    f"e {n_ev} evolução(ões) clínica(s). Corrija o cadastro pela "
                    "edição ou cancele/reatribua os registros antes."))
    db.query("DELETE FROM patients.contacts WHERE patient_id = %s",
             (patient_id,), commit=True)
    db.query("DELETE FROM patients.records WHERE id = %s", (patient_id,), commit=True)
    return {"ok": True}


@router.get("/api/patients/{patient_id}/appointments")
def patient_appointments(patient_id: int, user: dict = Depends(current_user)):
    rows = db.query(
        "SELECT a.id, a.start_time, a.valor_pago, st.status_name AS status, "
        "s.name AS servico, pr.title, pr.full_name AS profissional "
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
        "valor": float(r["valor_pago"]) if r["valor_pago"] is not None else None,
    } for r in rows]
