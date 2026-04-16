"""
ATLAS PRO — WhatsApp Client (Baileys bridge)
Envoie des messages via le service Node.js Baileys local
"""
import os, logging, requests
from app.core.config import cfg

logger = logging.getLogger("atlas.whatsapp")

WA_URL    = os.getenv("WA_SERVICE_URL", "http://localhost:3001")
WA_SECRET = os.getenv("WA_SECRET", "atlas_wa_secret_2024")
HEADERS   = {"x-wa-token": WA_SECRET, "Content-Type": "application/json"}

def wa_connected() -> bool:
    try:
        r = requests.get(f"{WA_URL}/health", timeout=3)
        return r.json().get("connected", False)
    except: return False

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
        r = requests.post(f"{WA_URL}/send", json={"phone": p, "message": message},
                         headers=HEADERS, timeout=10)
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
    objet   = tender.get("objet","")[:120]
    secteur = tender.get("secteur","")
    acheteur= tender.get("acheteur","")[:60]
    dl      = tender.get("date_limite","")
    url     = tender.get("url","")
    site    = cfg.SITE_URL

    return f"""🔔 *ATLAS PRO — Nouveau Marché*

📋 *{objet}*

🏷 Secteur: {secteur}
🏢 Acheteur: {acheteur}
⏰ Date limite: {dl or 'Non précisée'}

👉 Voir les détails: {site}/tenders/{tender.get('id','')}

_ATLAS PRO — Veille Marchés Publics Maroc_"""
