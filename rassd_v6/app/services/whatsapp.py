"""
Maroc Entrepreneuriat — WhatsApp Client (Baileys bridge)
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

def normalize_ma_phone(phone: str) -> str:
    """Normalise un numéro marocain au format international sans '+'.

    Accepte '06 12 34 56 78', '+212612345678', '0612345678', '212612345678'.
    Retourne '' si le numéro ne ressemble pas à un numéro exploitable, pour
    éviter d'envoyer vers une destination invalide.
    """
    if not phone:
        return ""
    p = "".join(ch for ch in str(phone) if ch.isdigit() or ch == "+")
    p = p.lstrip("+")
    if p.startswith("00"):
        p = p[2:]
    if p.startswith("0") and len(p) == 10:
        p = "212" + p[1:]
    if p.startswith("212") and len(p) == 12:
        return p
    return p if 8 <= len(p) <= 15 else ""

def twilio_configured() -> bool:
    return bool(cfg.TWILIO_SID and cfg.TWILIO_AUTH_TOKEN and cfg.TWILIO_WA_FROM)

def send_wa_twilio(phone: str, message: str) -> bool:
    """Envoi via l'API WhatsApp de Twilio.

    Actif uniquement si TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN /
    TWILIO_WHATSAPP_FROM sont configurés. Utilise l'API REST directement
    (pas de SDK) pour ne pas ajouter de dépendance au déploiement.
    """
    p = normalize_ma_phone(phone)
    if not p:
        logger.warning(f"[WA/Twilio] Numéro invalide: {phone}")
        return False
    frm = cfg.TWILIO_WA_FROM if cfg.TWILIO_WA_FROM.startswith("whatsapp:") else f"whatsapp:+{cfg.TWILIO_WA_FROM.lstrip('+')}"
    try:
        r = requests.post(
            f"https://api.twilio.com/2010-04-01/Accounts/{cfg.TWILIO_SID}/Messages.json",
            auth=(cfg.TWILIO_SID, cfg.TWILIO_AUTH_TOKEN),
            data={"From": frm, "To": f"whatsapp:+{p}", "Body": message},
            timeout=15)
        if r.status_code in (200, 201):
            logger.info(f"[WA/Twilio] ✅ → {p}")
            return True
        logger.error(f"[WA/Twilio] Erreur {r.status_code}: {r.text[:200]}")
        return False
    except Exception as e:
        logger.error(f"[WA/Twilio] ❌ {e}")
        return False

def send_wa(phone: str, message: str) -> bool:
    """Envoie un message WhatsApp via le fournisseur configuré.

    Twilio prend la main dès qu'il est configuré, sinon on conserve le
    service Baileys déjà en place.
    """
    if not phone or not phone.strip(): return False
    if twilio_configured():
        return send_wa_twilio(phone, message)
    p = normalize_ma_phone(phone)
    if not p:
        logger.warning(f"[WA] Numéro invalide: {phone}")
        return False
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

    return f"""🔔 *Maroc Entrepreneuriat — Nouveau Marché {type_offre}*

📋 *{objet}*

🏷 Secteur: {secteur}
🏢 Acheteur: {acheteur}
⏰ Date limite: {dl or 'Non précisée'}

👉 Voir les détails: {site}/tenders/{tender.get('id','')}

_Maroc Entrepreneuriat — Veille Marchés Publics & Privés Maroc_"""
