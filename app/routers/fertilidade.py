"""Plataforma "Fertilidade Sem Segredos" — matching médico ↔ paciente por
proximidade (raio padrão 100 km).

Fluxo:
- Médico se cadastra (endpoint público) → entra 'pendente' e é geocodificado.
- A Materlux aprova pela área /fertilidade/admin (protegida pelo login do painel).
  Ao aprovar, avisa por WhatsApp as pacientes em espera dentro do raio.
- Paciente informa o endereço e busca médicos aprovados no raio. Se não houver,
  recebe o CTA de teleconsulta (WhatsApp) e pode deixar "me avise".

Endpoints públicos ficam sem autenticação (site aberto); os /admin exigem o
cookie de sessão do painel (current_user).
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from ..security import current_user
from ..config import get_settings
from .. import db, geocoding
from .whatsapp import send_reply

router = APIRouter()
_s = get_settings()


def _normaliza_fone(fone: str | None) -> str | None:
    """Garante DDI 55 (Z-API espera o número com código do país)."""
    d = "".join(c for c in (fone or "") if c.isdigit())
    if len(d) in (10, 11):
        return "55" + d
    if len(d) in (12, 13) and d.startswith("55"):
        return d
    return d or None


def _so_digitos(s: str | None) -> str | None:
    d = "".join(c for c in (s or "") if c.isdigit())
    return d or None


# --------------------------------------------------------------------------- #
# Cadastro de médico (público)
# --------------------------------------------------------------------------- #
class NovoMedico(BaseModel):
    nome: str
    crm: str
    especialidade: str | None = None
    telefone: str
    email: str | None = None
    cep: str | None = None
    endereco: str | None = None
    numero: str | None = None
    complemento: str | None = None
    bairro: str | None = None
    cidade: str | None = None
    estado: str | None = None
    observacoes: str | None = None


@router.post("/api/fertilidade/medicos")
def cadastrar_medico(body: NovoMedico):
    for campo, val in (("nome", body.nome), ("CRM", body.crm),
                       ("contato", body.telefone), ("cidade", body.cidade),
                       ("estado", body.estado)):
        if not (val or "").strip():
            raise HTTPException(status_code=400, detail=f"Campo obrigatório: {campo}")

    lat, lng = geocoding.geocode(geocoding.monta_endereco(
        endereco=body.endereco, numero=body.numero, bairro=body.bairro,
        cidade=body.cidade, estado=body.estado, cep=body.cep))

    row = db.query(
        "INSERT INTO fertilidade.medicos "
        "(nome, crm, especialidade, telefone, email, cep, endereco, numero, "
        " complemento, bairro, cidade, estado, observacoes, latitude, longitude) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
        (body.nome.strip(), body.crm.strip(),
         (body.especialidade or "").strip() or None,
         _so_digitos(body.telefone), (body.email or "").strip() or None,
         _so_digitos(body.cep), (body.endereco or "").strip() or None,
         (body.numero or "").strip() or None,
         (body.complemento or "").strip() or None,
         (body.bairro or "").strip() or None, body.cidade.strip(),
         body.estado.strip().upper()[:2], (body.observacoes or "").strip() or None,
         lat, lng),
        one=True, commit=True,
    )
    return {"ok": True, "medico_id": row["id"],
            "mensagem": ("Cadastro recebido! Ele passará por uma validação da "
                         "equipe Materlux antes de aparecer nas buscas.")}


# --------------------------------------------------------------------------- #
# Busca por proximidade (público)
# --------------------------------------------------------------------------- #
class BuscaPaciente(BaseModel):
    cep: str | None = None
    endereco: str | None = None
    numero: str | None = None
    bairro: str | None = None
    cidade: str | None = None
    estado: str | None = None


@router.post("/api/fertilidade/buscar")
def buscar_medicos(body: BuscaPaciente):
    lat, lng = geocoding.geocode(geocoding.monta_endereco(
        endereco=body.endereco, numero=body.numero, bairro=body.bairro,
        cidade=body.cidade, estado=body.estado, cep=body.cep))
    if lat is None:
        raise HTTPException(
            status_code=422,
            detail="Não consegui localizar esse endereço. Confira o CEP/cidade.")

    raio = _s.FERTILIDADE_RAIO_KM
    rows = db.query(
        "SELECT id, nome, crm, especialidade, telefone, email, endereco, numero, "
        "bairro, cidade, estado, observacoes, latitude, longitude "
        "FROM fertilidade.medicos "
        "WHERE status = 'aprovado' AND latitude IS NOT NULL AND longitude IS NOT NULL"
    )
    achados = []
    for r in rows:
        dist = geocoding.haversine_km(lat, lng, r["latitude"], r["longitude"])
        if dist <= raio:
            achados.append({
                "id": r["id"], "nome": r["nome"], "crm": r["crm"],
                "especialidade": r["especialidade"] or "",
                "telefone": r["telefone"] or "",
                "email": r["email"] or "",
                "cidade": r["cidade"] or "", "estado": r["estado"] or "",
                "endereco": " ".join(p for p in [r["endereco"], r["numero"]] if p),
                "bairro": r["bairro"] or "",
                "observacoes": r["observacoes"] or "",
                "distancia_km": round(dist, 1),
            })
    achados.sort(key=lambda m: m["distancia_km"])

    return {
        "encontrou": bool(achados),
        "raio_km": raio,
        "medicos": achados,
        "whatsapp": _s.FERTILIDADE_WHATSAPP,
    }


# --------------------------------------------------------------------------- #
# "Me avise quando um médico se cadastrar perto de mim" (público)
# --------------------------------------------------------------------------- #
class PacienteEspera(BaseModel):
    nome: str
    telefone: str
    email: str | None = None
    cep: str | None = None
    cidade: str | None = None
    estado: str | None = None
    endereco: str | None = None
    numero: str | None = None
    bairro: str | None = None


@router.post("/api/fertilidade/espera")
def entrar_na_espera(body: PacienteEspera):
    for campo, val in (("nome", body.nome), ("WhatsApp", body.telefone)):
        if not (val or "").strip():
            raise HTTPException(status_code=400, detail=f"Campo obrigatório: {campo}")

    lat, lng = geocoding.geocode(geocoding.monta_endereco(
        endereco=body.endereco, numero=body.numero, bairro=body.bairro,
        cidade=body.cidade, estado=body.estado, cep=body.cep))

    db.query(
        "INSERT INTO fertilidade.pacientes_espera "
        "(nome, telefone, email, cep, cidade, estado, latitude, longitude) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
        (body.nome.strip(), _so_digitos(body.telefone),
         (body.email or "").strip() or None, _so_digitos(body.cep),
         (body.cidade or "").strip() or None,
         (body.estado or "").strip().upper()[:2] or None, lat, lng),
        commit=True,
    )
    return {"ok": True, "mensagem": ("Pronto! Assim que um médico se cadastrar "
                                     "perto de você, avisamos pelo WhatsApp.")}


# --------------------------------------------------------------------------- #
# Administração — aprovação (exige login do painel)
# --------------------------------------------------------------------------- #
@router.get("/api/fertilidade/admin/medicos")
def admin_listar(status: str = "pendente", user: dict = Depends(current_user)):
    if status not in ("pendente", "aprovado", "rejeitado", "todos"):
        status = "pendente"
    where = "" if status == "todos" else "WHERE status = %s"
    params = () if status == "todos" else (status,)
    rows = db.query(
        "SELECT id, nome, crm, especialidade, telefone, email, cep, endereco, "
        "numero, complemento, bairro, cidade, estado, observacoes, latitude, "
        "longitude, status, created_at, approved_at "
        f"FROM fertilidade.medicos {where} ORDER BY created_at DESC", params)
    return [{
        "id": r["id"], "nome": r["nome"], "crm": r["crm"],
        "especialidade": r["especialidade"] or "",
        "telefone": r["telefone"] or "", "email": r["email"] or "",
        "endereco": ", ".join(p for p in [
            " ".join(x for x in [r["endereco"], r["numero"]] if x),
            r["bairro"], r["cidade"], r["estado"], r["cep"]] if p),
        "observacoes": r["observacoes"] or "",
        "geocodificado": r["latitude"] is not None,
        "status": r["status"],
        "created_at": r["created_at"].isoformat() if r["created_at"] else None,
    } for r in rows]


def _notifica_espera(medico: dict) -> int:
    """Avisa por WhatsApp as pacientes em espera dentro do raio deste médico."""
    if medico["latitude"] is None or medico["longitude"] is None:
        return 0
    raio = _s.FERTILIDADE_RAIO_KM
    espera = db.query(
        "SELECT id, nome, telefone, latitude, longitude FROM "
        "fertilidade.pacientes_espera WHERE notificado = false "
        "AND latitude IS NOT NULL AND longitude IS NOT NULL")
    avisados = 0
    cidade = f"{medico['cidade']}/{medico['estado']}".strip("/")
    for p in espera:
        dist = geocoding.haversine_km(
            p["latitude"], p["longitude"], medico["latitude"], medico["longitude"])
        if dist > raio:
            continue
        fone = _normaliza_fone(p["telefone"])
        if not fone:
            continue
        msg = (f"Olá, {(p['nome'] or '').split(' ')[0] or 'tudo bem'}! 😊 "
               "Boa notícia da plataforma Fertilidade Sem Segredos: um médico se "
               f"cadastrou perto de você — Dr(a). {medico['nome']}"
               f"{f' ({cidade})' if cidade else ''}. "
               "Acesse fertilidadesemsegredos.com.br e busque pelo seu endereço "
               "para ver os dados de contato. 💙")
        try:
            send_reply(fone, msg)
            db.query("UPDATE fertilidade.pacientes_espera "
                     "SET notificado = true, notificado_em = now() WHERE id = %s",
                     (p["id"],), commit=True)
            avisados += 1
        except Exception as e:  # noqa
            print(f"[fertilidade] falha ao avisar espera={p['id']}: {e}", flush=True)
    return avisados


@router.post("/api/fertilidade/admin/medicos/{medico_id}/aprovar")
def admin_aprovar(medico_id: int, user: dict = Depends(current_user)):
    m = db.query("SELECT * FROM fertilidade.medicos WHERE id = %s",
                 (medico_id,), one=True)
    if not m:
        raise HTTPException(status_code=404, detail="Médico não encontrado")
    db.query("UPDATE fertilidade.medicos SET status = 'aprovado', "
             "approved_at = now() WHERE id = %s", (medico_id,), commit=True)
    avisados = _notifica_espera(m)
    return {"ok": True, "status": "aprovado", "pacientes_avisadas": avisados}


@router.post("/api/fertilidade/admin/medicos/{medico_id}/rejeitar")
def admin_rejeitar(medico_id: int, user: dict = Depends(current_user)):
    if not db.query("SELECT id FROM fertilidade.medicos WHERE id = %s",
                    (medico_id,), one=True):
        raise HTTPException(status_code=404, detail="Médico não encontrado")
    db.query("UPDATE fertilidade.medicos SET status = 'rejeitado' WHERE id = %s",
             (medico_id,), commit=True)
    return {"ok": True, "status": "rejeitado"}
