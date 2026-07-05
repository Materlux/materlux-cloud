from fastapi import APIRouter, Depends
from ..security import current_user
from .. import db

router = APIRouter()


@router.get("/api/patients/search")
def search(name: str, user: dict = Depends(current_user)):
    rows = db.query(
        "SELECT id, first_name, last_name, cpf, email FROM patients.records "
        "WHERE lower(first_name || ' ' || last_name) LIKE %s "
        "OR cpf = %s ORDER BY first_name LIMIT 25",
        (f"%{name.lower()}%", name),
    )
    return [{"id": r["id"],
             "nome": f"{r['first_name']} {r['last_name']}".strip(),
             "cpf": r["cpf"] or "", "email": r["email"] or ""} for r in rows]
