"""
Maroc Entrepreneuriat — WhatsApp Client (Baileys bridge)
Envoie des messages via le service Node.js Baileys local
"""
import json, logging, re, requests
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

SANDBOX_NUMBER = "14155238886"

def is_twilio_sandbox() -> bool:
    """L'expéditeur est-il le numéro partagé du Sandbox Twilio ?"""
    return SANDBOX_NUMBER in "".join(ch for ch in (cfg.TWILIO_WA_FROM or "") if ch.isdigit())

def clean_template_var(value, fallback: str = "-", max_len: int = 180) -> str:
    """Rend une valeur acceptable comme variable de modèle WhatsApp.

    Meta refuse une variable contenant un saut de ligne, une tabulation ou
    plus de quatre espaces consécutifs, ainsi qu'une variable vide: le
    message entier serait rejeté à cause d'un seul titre mal formé.
    """
    text = re.sub(r"\s+", " ", str(value if value is not None else "")).strip()
    if len(text) > max_len:
        text = text[: max_len - 1].rstrip() + "…"
    return text or fallback

def _twilio_from() -> str:
    frm = cfg.TWILIO_WA_FROM or ""
    return frm if frm.startswith("whatsapp:") else f"whatsapp:+{frm.lstrip('+')}"

def send_wa_template(phone: str, content_sid: str, variables: dict) -> bool:
    """Envoie un modèle WhatsApp approuvé (ContentSid) via Twilio.

    Obligatoire pour tout message à l'initiative de l'entreprise en dehors
    de la fenêtre de 24 h — c'est le cas du résumé quotidien.
    """
    if not twilio_configured() or not content_sid:
        return False
    p = normalize_ma_phone(phone)
    if not p:
        logger.warning(f"[WA/Twilio] Numéro invalide: {phone}")
        return False
    propres = {str(k): clean_template_var(v) for k, v in (variables or {}).items()}
    try:
        r = requests.post(
            f"https://api.twilio.com/2010-04-01/Accounts/{cfg.TWILIO_SID}/Messages.json",
            auth=(cfg.TWILIO_SID, cfg.TWILIO_AUTH_TOKEN),
            data={"From": _twilio_from(), "To": f"whatsapp:+{p}",
                  "ContentSid": content_sid,
                  "ContentVariables": json.dumps(propres, ensure_ascii=False)},
            timeout=15)
        if r.status_code in (200, 201):
            logger.info(f"[WA/Twilio] ✅ modèle → {p}")
            return True
        logger.error(f"[WA/Twilio] Erreur modèle {r.status_code}: {r.text[:200]}")
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
