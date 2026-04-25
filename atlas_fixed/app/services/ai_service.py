"""
ATLAS PRO — AI Service (Groq)
================================
ذكاء اصطناعي مدمج في المنصة
- تصنيف STX10 بالذكاء الاصطناعي
- ملخص ذكي للصفقات
- تنبيهات مخصصة
- chatbot داخلي
"""
import os, json, logging, requests
from app.core.config import cfg

logger = logging.getLogger("atlas.ai")

GROQ_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL    = "llama-3.1-8b-instant"  # مجاني 1M token/jour

def _ask(prompt: str, system: str = "", max_tokens: int = 500, json_mode: bool = False) -> str:
    """Appel Groq de base"""
    if not GROQ_KEY:
        return ""
    try:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        body = {
            "model": MODEL,
            "max_tokens": max_tokens,
            "messages": messages,
            "temperature": 0.3,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}

        r = requests.post(GROQ_URL,
            headers={"Authorization": f"Bearer {GROQ_KEY}",
                     "Content-Type": "application/json"},
            json=body, timeout=15)

        if r.status_code == 200:
            return r.json()["choices"][0]["message"]["content"].strip()
        logger.warning(f"[AI] Groq {r.status_code}: {r.text[:100]}")
        return ""
    except Exception as e:
        logger.error(f"[AI] {e}")
        return ""

# ══════════════════════════════════════════════════════════
# 1. CLASSIFICATION STX10 PAR IA
# ══════════════════════════════════════════════════════════
def ai_classify_stx10(tender_text: str) -> dict:
    """
    Classifie une offre avec l'IA (plus précis que les mots-clés).
    Retourne: {"code": "T101", "label": "...", "confidence": 0.9}
    """
    if not GROQ_KEY or not tender_text:
        return {}

    prompt = f"""Tu es un expert en marchés publics marocains.
Classifie cette offre selon le système STX10 marocain.

Catégories principales:
T = Travaux (T101=Construction, T110=Génie civil, T201=Assainissement, T301=Routes, T401=Électricité, T403=Télécoms)
P = Produits/Équipements (P818=Informatique, P813=Médical, P816=Véhicules, P839=Matériaux construction, P850=Solaire)
S = Services (S901=Développement IT, S902=Études/Conseil, S906=Maintenance, S908=Gardiennage, S913=Formation, S910=Communication)

Texte: {tender_text[:600]}

Réponds UNIQUEMENT en JSON:
{{"code": "CODE", "label": "Description courte", "confidence": 0.0-1.0, "category": "T|P|S"}}"""

    result = _ask(prompt, json_mode=True)
    if result:
        try:
            return json.loads(result)
        except:
            pass
    return {}

# ══════════════════════════════════════════════════════════
# 2. RÉSUMÉ INTELLIGENT
# ══════════════════════════════════════════════════════════
def ai_summarize(tender: dict) -> str:
    """
    Génère un résumé clair et actionnable d'un marché.
    """
    if not GROQ_KEY:
        return ""

    text = f"Objet: {tender.get('objet','')}\nAcheteur: {tender.get('acheteur','')}\nMontant: {tender.get('montant','')}\nDate limite: {tender.get('date_limite','')}"
    if tender.get('description'):
        text += f"\nDescription: {tender['description'][:400]}"

    prompt = f"""Résume ce marché public marocain en 3 points clés pour un entrepreneur:
1. Ce que demande exactement ce marché
2. Le profil d'entreprise idéal pour y répondre
3. Points d'attention importants (délai, montant, conditions)

Marché:
{text}

Réponds en français, concis et professionnel (max 120 mots)."""

    return _ask(prompt, max_tokens=200)

# ══════════════════════════════════════════════════════════
# 3. MESSAGE DE NOTIFICATION PERSONNALISÉ
# ══════════════════════════════════════════════════════════
def ai_notification_message(tender: dict, member: dict, matched_codes: list) -> str:
    """
    Génère un message de notification personnalisé et engageant.
    """
    if not GROQ_KEY:
        return ""

    prompt = f"""Tu rédiges une alerte WhatsApp/Telegram pour un entrepreneur marocain.
Ton style: direct, professionnel, en français avec quelques mots arabes courants.
Maximum 5 lignes.

Marché: {tender.get('objet','')[:150]}
Acheteur: {tender.get('acheteur','')}
Budget: {tender.get('montant','Non précisé')}
Date limite: {tender.get('date_limite','')}
Codes STX10 correspondants: {', '.join(matched_codes)}

Entreprise: {member.get('nom','')} (plan {member.get('plan','pro')})

Rédige l'alerte en commençant par une emoji et le nom de l'entreprise."""

    return _ask(prompt, max_tokens=200)

# ══════════════════════════════════════════════════════════
# 4. CHATBOT INTERNE
# ══════════════════════════════════════════════════════════
def ai_chat(question: str, context: dict = None) -> str:
    """
    Répond aux questions des membres sur les marchés publics.
    context: {"tenders_count": 150, "member_plan": "pro", "member_sectors": ["BTP"]}
    """
    if not GROQ_KEY:
        return "L'assistant IA n'est pas disponible pour le moment."

    ctx = context or {}
    system = f"""Tu es l'assistant ATLAS PRO, expert en marchés publics marocains.
Tu aides les entrepreneurs marocains à trouver et remporter des marchés.

Contexte:
- Plateforme: ATLAS PRO (veille marchés publics maroc)
- Marchés actifs: {ctx.get('tenders_count', '?')}
- Plan membre: {ctx.get('member_plan', 'gratuit')}
- Secteurs: {', '.join(ctx.get('member_sectors', []))}

Tu réponds en français (ou arabe si on te parle en arabe).
Tu es concis, utile et pratique.
Si on te demande des données précises que tu n'as pas, dis-le honnêtement."""

    return _ask(question, system=system, max_tokens=400)

# ══════════════════════════════════════════════════════════
# 5. ANALYSE DE TENDANCES
# ══════════════════════════════════════════════════════════
def ai_analyze_trends(stats: dict) -> str:
    """
    Analyse les statistiques et donne des insights business.
    """
    if not GROQ_KEY:
        return ""

    prompt = f"""Analyse ces statistiques de marchés publics marocains et donne 3 insights actionnables:

Statistiques:
- Total marchés actifs: {stats.get('tenders', 0)}
- Nouveaux aujourd'hui: {stats.get('today', 0)}
- Top secteurs: {stats.get('top_sectors', [])}
- Montant moyen: {stats.get('avg_montant', 'N/A')}

Donne 3 conseils concrets pour les entrepreneurs en 2-3 lignes chacun."""

    return _ask(prompt, max_tokens=300)

# ══════════════════════════════════════════════════════════
# 6. VÉRIFICATION DISPONIBILITÉ
# ══════════════════════════════════════════════════════════
def ai_available() -> bool:
    """Vérifie si l'API Groq est disponible"""
    return bool(GROQ_KEY)
