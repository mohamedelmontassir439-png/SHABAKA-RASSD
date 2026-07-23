"""
ATLAS PRO — WhatsApp Client (Baileys bridge)
Envoie des messages via le service Node.js Baileys local
"""
import logging, requests
from app.core.config import cfg
from app.core.sectors import get_label

logger = logging.getLogger("atlas.whatsapp")

def _headers():
    return {"x-wa-token": cfg.WA_SECRET, "Content-Type": "application/json"}

def wa_connected() -> bool:
    """Vérifie si le service WhatsApp local est connecté."""
    try:
        r = requests.get(f"{cfg.WA_SERVICE_URL}/health", timeout=3)
        return r.json().get("connected", False)
    except (requests.RequestException, ValueError) as e:
        # RequestException = réseau down, ValueError = JSON invalide
        logger.debug(f"[wa_connected] Service indisponible: {e}")
        return False

def send_wa(phone: str, message: str) -> bool:
    """Envoie un message WhatsApp"""
    if not phone or not phone.strip(): return False
    # Normalize phone: add 212 prefix for Morocco if needed
    p = phone.strip().replace(" ","").replace("-","")
    if p.startswith("0") and len(p) == 10:
        p = "212" + p[1:]
    elif p.startswith("+"):
        p = p[1:]
    try:
        r = requests.post(f"{cfg.WA_SERVICE_URL}/send", json={"phone": p, "message": message},
                         headers=_headers(), timeout=10)
        data = r.json()
        if data.get("ok"):
            logger.info(f"[WA] ✅ Message envoyé → {phone}")
            return True
        logger.warning(f"[WA] ⚠ {data.get('msg')}")
        return False
    except Exception as e:
        logger.error(f"[WA] ❌ {e}")
        return False

def format_tender_wa(tender: dict) -> str:
    """Format un marché pour WhatsApp"""
    objet      = tender.get("objet","")[:120]
    secteur    = get_label(tender.get("secteur",""))
    acheteur   = tender.get("acheteur","")[:60]
    dl         = tender.get("date_limite","")
    site       = cfg.SITE_URL
    type_offre = tender.get("type_offre","Public")

    return f"""🔔 *ATLAS PRO — Nouveau Marché {type_offre}*

📋 *{objet}*

🏷 Secteur: {secteur}
🏢 Acheteur: {acheteur}
⏰ Date limite: {dl or 'Non précisée'}

👉 Voir les détails: {site}/tenders/{tender.get('id','')}

_ATLAS PRO — Veille Marchés Publics & Privés Maroc_"""
