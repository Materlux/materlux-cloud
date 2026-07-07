from datetime import date
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from ..security import current_user
from .. import db

router = APIRouter()


def _data_iso(s: str | None) -> date | None:
    if not (s or "").strip():
        return None
    try:
        return date.fromisoformat(s.strip())
    except ValueError:
        raise HTTPException(status_code=400,
                            detail="Data de pagamento inválida (YYYY-MM-DD)")


class NewParto(BaseModel):
    patient_id: int
    professional_id: int
    valor_pago: float | None = None
    data_pagamento: str | None = None   # YYYY-MM-DD
    observacoes: str | None = None


@router.post("/api/partos")
def create_parto(body: NewParto, user: dict = Depends(current_user)):
    if not db.query("SELECT id FROM patients.records WHERE id = %s",
                    (body.patient_id,), one=True):
        raise HTTPException(status_code=404, detail="Paciente não encontrada")
    row = db.query(
        "INSERT INTO medical.partos "
        "(patient_id, professional_id, valor_pago, data_pagamento, observacoes) "
        "VALUES (%s, %s, %s, %s, %s) RETURNING id",
        (body.patient_id, body.professional_id, body.valor_pago,
         _data_iso(body.data_pagamento), (body.observacoes or "").strip() or None),
        one=True, commit=True,
    )
    return {"ok": True, "parto_id": row["id"]}


@router.get("/api/partos")
def list_partos(inicio: str, fim: str, user: dict = Depends(current_user)):
    """Partos pagos no período + todos os ainda sem data de pagamento
    (para a secretária poder completar depois)."""
    d0, d1 = date.fromisoformat(inicio), date.fromisoformat(fim)
    rows = db.query(
        "SELECT t.id, t.valor_pago, t.data_pagamento, t.observacoes, "
        "p.first_name, p.last_name, pr.title, pr.full_name "
        "FROM medical.partos t "
        "JOIN patients.records p ON p.id = t.patient_id "
        "JOIN medical.professionals pr ON pr.id = t.professional_id "
        "WHERE t.data_pagamento IS NULL "
        "   OR (t.data_pagamento >= %s AND t.data_pagamento <= %s) "
        "ORDER BY t.data_pagamento DESC NULLS FIRST, t.id DESC",
        (d0, d1),
    )
    return [{
        "id": r["id"],
        "paciente": f"{r['first_name']} {r['last_name']}".strip(),
        "profissional": f"{(r['title'] or '').strip()} {r['full_name']}".strip(),
        "valor_pago": float(r["valor_pago"]) if r["valor_pago"] is not None else None,
        "data_pagamento": (r["data_pagamento"].strftime("%d/%m/%Y")
                           if r["data_pagamento"] else ""),
        "observacoes": r["observacoes"] or "",
    } for r in rows]


class PartoUpdate(BaseModel):
    valor_pago: float | None = None
    data_pagamento: str | None = None   # YYYY-MM-DD
    observacoes: str | None = None


@router.patch("/api/partos/{parto_id}")
def update_parto(parto_id: int, body: PartoUpdate,
                 user: dict = Depends(current_user)):
    if not db.query("SELECT id FROM medical.partos WHERE id = %s",
                    (parto_id,), one=True):
        raise HTTPException(status_code=404, detail="Parto não encontrado")
    db.query(
        "UPDATE medical.partos SET valor_pago = %s, data_pagamento = %s, "
        "observacoes = %s WHERE id = %s",
        (body.valor_pago, _data_iso(body.data_pagamento),
         (body.observacoes or "").strip() or None, parto_id),
        commit=True,
    )
    return {"ok": True}


@router.delete("/api/partos/{parto_id}")
def delete_parto(parto_id: int, user: dict = Depends(current_user)):
    if not db.query("SELECT id FROM medical.partos WHERE id = %s",
                    (parto_id,), one=True):
        raise HTTPException(status_code=404, detail="Parto não encontrado")
    db.query("DELETE FROM medical.partos WHERE id = %s", (parto_id,), commit=True)
    return {"ok": True}
