"""
ATLAS PRO — WhatsApp Client v2.0
Supporte:
  1. Baileys Bridge (Node.js local/Railway)
  2. WhatsApp Business API (wa.me link)
"""
import os, logging, requests
from app.core.config import cfg

logger = logging.getLogger("atlas.whatsapp")

def wa_connected() -> bool:
    """Vérifie si le service Baileys est actif"""
    try:
        r = requests.get(f"{cfg.WA_SERVICE_URL}/health",
                        headers={"x-wa-token": cfg.WA_SECRET},
                        timeout=3)
        return r.json().get("connected", False)
    except:
        return False

def send_wa(phone: str, message: str) -> bool:
    """Envoie un message WhatsApp via Baileys ou fallback"""
    if not phone or not phone.strip():
        return False

    # Normaliser le numéro
    p = phone.strip().replace(" ","").replace("-","").replace("+","")
    if p.startswith("0") and len(p) == 10:
        p = "212" + p[1:]

    # Essayer Baileys en premier
    try:
        r = requests.post(
            f"{cfg.WA_SERVICE_URL}/send",
            json={"phone": p, "message": message},
            headers={"x-wa-token": cfg.WA_SECRET, "Content-Type": "application/json"},
            timeout=10)
        data = r.json()
        if data.get("ok"):
            logger.info(f"[WA] ✅ Baileys → {phone}")
            return True
        logger.warning(f"[WA] Baileys: {data.get('msg','?')}")
    except Exception as e:
        logger.debug(f"[WA] Baileys indisponible: {e}")

    # Fallback: log uniquement (wa.me links ne peuvent pas être envoyés par code)
    logger.info(f"[WA] Fallback — message non envoyé à {phone}: {message[:50]}")
    return False

def get_wa_link(phone: str = None, message: str = None) -> str:
    """Génère un lien wa.me pour le paiement"""
    phone = phone or cfg.PAYMENT_PHONE
    msg   = message or cfg.PAYMENT_MSG
    import urllib.parse
    return f"https://wa.me/{phone}?text={urllib.parse.quote(msg)}"

def format_tender_wa(tender: dict) -> str:
    """Format un marché pour WhatsApp"""
    objet    = tender.get("objet","")[:120]
    secteur  = tender.get("secteur","")
    acheteur = tender.get("acheteur","")[:60]
    dl       = tender.get("date_limite","")
    tid      = tender.get("id","")

    return (f"🔔 *ATLAS PRO — Nouveau Marché*\n\n"
            f"📋 *{objet}*\n\n"
            f"🏷 Secteur: {secteur}\n"
            f"🏢 Acheteur: {acheteur}\n"
            f"⏰ Date limite: {dl or 'Non précisée'}\n\n"
            f"👉 {cfg.SITE_URL}/tenders/{tid}\n\n"
            f"_ATLAS PRO — Veille Marchés Publics Maroc_")
