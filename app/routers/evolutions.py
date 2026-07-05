from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from ..security import require_role, current_user
from .. import db

router = APIRouter()


@router.get("/api/patients/{patient_id}/evolutions")
def history(patient_id: int, user: dict = Depends(current_user)):
    rows = db.query(
        "SELECT e.id, e.anamnese, e.exame_fisico, e.conduta, e.data_registro, "
        "e.origem, u.full_name AS autor "
        "FROM medical.clinical_evolutions e "
        "LEFT JOIN auth_app.users u ON u.id = e.author_user_id "
        "WHERE e.patient_id = %s ORDER BY e.data_registro DESC",
        (patient_id,),
    )
    return [{"id": r["id"], "anamnese": r["anamnese"],
             "exame_fisico": r["exame_fisico"] or "", "conduta": r["conduta"] or "",
             "data": r["data_registro"].strftime("%d/%m/%Y %H:%M"),
             "autor": r["autor"] or "", "origem": r["origem"]} for r in rows]


class NewEvolution(BaseModel):
    patient_id: int
    appointment_id: int | None = None
    anamnese: str
    exame_fisico: str | None = None
    conduta: str | None = None


@router.post("/api/evolutions")
def create(body: NewEvolution, user: dict = Depends(require_role("medico"))):
    if not body.anamnese.strip():
        raise HTTPException(status_code=400, detail="Anamnese vazia")
    pat = db.query("SELECT cpf FROM patients.records WHERE id = %s",
                   (body.patient_id,), one=True)
    if not pat:
        raise HTTPException(status_code=404, detail="Paciente não encontrada")
    row = db.query(
        "INSERT INTO medical.clinical_evolutions "
        "(patient_id, professional_id, appointment_id, cpf, anamnese, exame_fisico, "
        " conduta, author_user_id, origem) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'cloud') RETURNING id",
        (body.patient_id, user.get("professional_id"), body.appointment_id, pat["cpf"],
         body.anamnese, body.exame_fisico, body.conduta, int(user["sub"])),
        one=True, commit=True,
    )
    return {"ok": True, "id": row["id"]}
