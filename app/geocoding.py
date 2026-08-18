"""Geocodificação (endereço → lat/lng) e distância, para a busca de médicos por
proximidade da plataforma Fertilidade Sem Segredos.

Usa a Google Geocoding API (mesma conta Google Cloud). A chave vem da env
GEOCODING_API_KEY (secret no Cloud Run). Sem chave, geocode() devolve (None, None)
e a busca degrada para "não encontrado" em vez de quebrar.
"""
import math
import httpx
from .config import get_settings

_s = get_settings()
_GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"


def monta_endereco(*, endereco: str | None = None, numero: str | None = None,
                   bairro: str | None = None, cidade: str | None = None,
                   estado: str | None = None, cep: str | None = None) -> str:
    """Monta um texto de endereço para geocodificar, ignorando partes vazias."""
    linha = " ".join(p for p in [(endereco or "").strip(),
                                 (numero or "").strip()] if p)
    partes = [linha, (bairro or "").strip(), (cidade or "").strip(),
              (estado or "").strip(), (cep or "").strip()]
    txt = ", ".join(p for p in partes if p)
    return f"{txt}, Brasil" if txt else "Brasil"


def geocode(endereco_texto: str) -> tuple[float | None, float | None]:
    """Devolve (lat, lng) do endereço, ou (None, None) se falhar/sem chave."""
    if not _s.GEOCODING_API_KEY or not (endereco_texto or "").strip():
        return None, None
    try:
        r = httpx.get(_GEOCODE_URL, timeout=15, params={
            "address": endereco_texto,
            "key": _s.GEOCODING_API_KEY,
            "region": "br",
            "components": "country:BR",
        })
        data = r.json()
        if data.get("status") == "OK" and data.get("results"):
            loc = data["results"][0]["geometry"]["location"]
            return float(loc["lat"]), float(loc["lng"])
        print(f"[geocode] status={data.get('status')} para {endereco_texto!r}",
              flush=True)
    except Exception as e:  # noqa
        print(f"[geocode] erro: {e}", flush=True)
    return None, None


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distância em km entre dois pontos (fórmula de Haversine)."""
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = (math.sin(dphi / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))
