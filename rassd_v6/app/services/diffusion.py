# -*- coding: utf-8 -*-
"""La campagne publique: quoi publier cette semaine, et ce que chaque canal rapporte.

La prospection directe (app/services/campagne.py) écrit à une entreprise à
la fois. Ici, on parle à tout le monde à la fois — Facebook, LinkedIn,
Instagram, les statuts et groupes WhatsApp — et la règle reste la même:
**montrer des marchés, pas décrire la plateforme**. « 1 219 marchés publics
ouverts cette semaine, dont un de 6,9 millions à Settat, limite le 26/10 »
se vérifie; « la meilleure plateforme de veille » ne se vérifie pas, et
tout le monde l'écrit.

Les textes sont donc régénérés à chaque ouverture de la page, à partir des
marchés en base: chiffres du jour, trois marchés réels, lien suivi par
canal. Il n'y a rien à rédiger, seulement à relire et publier.
"""
import re
from datetime import date, datetime, timedelta
from urllib.parse import quote

from app.core.canaux import CANAUX, CANAUX_DEDUITS, libelle, lien
from app.core.config import cfg
from app.core.database import get_db
from app.core.sectors import get_label
from app.core.security import PAID_PLANS

# Un marché qui ferme dans trois jours ne se prépare plus: le citer dans une
# publication qui circulera une semaine, c'est montrer une porte fermée.
MARGE_JOURS = 5

# Au-delà, l'estimation est presque toujours une erreur de saisie de
# l'acheteur: mesuré le 20/10/2026, le plus gros « marché » ouvert était un
# gardiennage à 5,4 milliards de dirhams. Choisir le plus gros montant,
# c'est choisir ces erreurs — et une publication qui les cite se fait
# reprendre en commentaire. Les marchés au-dessus restent sur le site.
PLAFOND_CREDIBLE = 150_000_000


def _montant(texte: str) -> float:
    """« 6.983.640,00 MAD » ou « 470 400,00 MAD » -> 6983640.0."""
    entier = (texte or "").split(",")[0]
    chiffres = re.sub(r"\D", "", entier)
    return float(chiffres) if chiffres else 0.0


def _jour(texte: str):
    try:
        return datetime.strptime((texte or "")[:10], "%d/%m/%Y").date()
    except ValueError:
        return None


def montant_lisible(valeur: float, langue: str = "fr") -> str:
    """6 983 640 -> « 6,9 millions de dirhams » / « 6,9 مليون درهم »."""
    if valeur >= 1_000_000:
        n = f"{int(valeur / 100_000) / 10:g}".replace(".", ",")
        if langue == "ar":
            return f"{n} مليون درهم"
        return f"{n} million{'' if n == '1' else 's'} de dirhams"
    n = f"{int(valeur):,}".replace(",", " ")
    return f"{n} درهم" if langue == "ar" else f"{n} dirhams"


def matiere(aujourdhui: date = None) -> dict:
    """Les chiffres et les marchés que les publications citent."""
    aujourdhui = aujourdhui or date.today()
    db = get_db()
    try:
        actifs = [dict(r) for r in db.execute(
            """SELECT id, objet, acheteur, region, montant, date_limite, secteur, scraped_at
               FROM tenders WHERE statut='actif'""").fetchall()]
    finally:
        db.close()

    par_secteur = {}
    for m in actifs:
        if m.get("secteur"):
            par_secteur[m["secteur"]] = par_secteur.get(m["secteur"], 0) + 1
    secteurs = [{"code": s, "label": get_label(s) or s, "n": n}
                for s, n in sorted(par_secteur.items(), key=lambda x: -x[1])[:3]]

    # La vitrine: les plus gros marchés encore préparables, un par secteur —
    # trois marchés de BTP ne parlent qu'au BTP.
    limite = aujourdhui + timedelta(days=MARGE_JOURS)
    candidats = sorted(
        (m for m in actifs if 0 < _montant(m.get("montant")) <= PLAFOND_CREDIBLE
         and (_jour(m.get("date_limite")) or date.min) >= limite),
        key=lambda m: -_montant(m.get("montant")))
    vitrine, vus = [], set()
    for m in candidats:
        if m.get("secteur") in vus:
            continue
        vus.add(m.get("secteur"))
        m["valeur"] = _montant(m["montant"])
        vitrine.append(m)
        if len(vitrine) == 3:
            break

    acheteurs = len({(m.get("acheteur") or "").strip().lower()
                     for m in actifs if m.get("acheteur")})
    return {"actifs": len(actifs), "secteurs": secteurs,
            "vitrine": vitrine, "acheteurs": acheteurs,
            "semaine": f"s{aujourdhui.isocalendar()[1]:02d}-{aujourdhui.year}"}


def _n(x: int) -> str:
    return f"{x:,}".replace(",", " ")


def _lignes_marches(vitrine: list, langue: str, puce: str = "▪") -> list:
    lignes = []
    for m in vitrine:
        objet = re.sub(r"\s+", " ", m.get("objet") or "").strip()
        if len(objet) > 90:
            objet = objet[:87].rsplit(" ", 1)[0] + "…"
        # « Province d'Ifrane MAROC »: le pays n'apprend rien à un Marocain.
        ville = re.sub(r"[\s,-]*\bMAROC\b[\s,.]*$", "", (m.get("region") or "").strip(),
                       flags=re.I)
        if langue == "ar":
            # La ligne commence par l'arabe: elle se lit alors de droite à
            # gauche, la ville en caractères latins à la fin.
            bas = " · ".join(x for x in [f"آخر أجل {m['date_limite']}",
                                         montant_lisible(m["valeur"], "ar"), ville] if x)
        else:
            bas = " · ".join(x for x in [montant_lisible(m["valeur"]), ville,
                                         f"limite le {m['date_limite']}"] if x)
        lignes.append(f"{puce} {objet}\n   {bas}")
    return lignes


def publications(aujourdhui: date = None) -> list:
    """Les textes de la semaine, un par canal et par langue, avec leur lien suivi."""
    m = matiere(aujourdhui)
    if not m["actifs"]:
        return []
    site, essai, sem = cfg.SITE_URL, cfg.TRIAL_DAYS, m["semaine"]
    secteurs_fr = ", ".join(f"{s['label']} ({_n(s['n'])})" for s in m["secteurs"])
    pubs = []

    def ajoute(canal, langue, titre, texte, page="/"):
        adresse = lien(site, canal, page, sem)
        texte = texte.replace("{LIEN}", adresse)
        partage = {
            "facebook": f"https://www.facebook.com/sharer/sharer.php?u={quote(adresse, safe='')}",
            "linkedin": f"https://www.linkedin.com/sharing/share-offsite/?url={quote(adresse, safe='')}",
            "whatsapp": f"https://wa.me/?text={quote(texte, safe='')}",
        }.get(canal, "")
        pubs.append({"canal": canal, "canal_label": CANAUX[canal], "langue": langue,
                     "titre": titre, "texte": texte, "lien": adresse, "partage": partage})

    # ── Facebook: le public large des patrons de TPE, en arabe d'abord ──
    ajoute("facebook", "ar", "Facebook — العربية", "\n".join([
        f"📢 {m['actifs']} صفقة عمومية مفتوحة الآن في المغرب، أطلقها {m['acheteurs']} صاحب مشروع.",
        "",
        "من بينها:",
        *_lignes_marches(m["vitrine"], "ar"),
        "",
        "Maroc Entrepreneuriat يجمع لك صفقات البوابة الوطنية ومصادر أخرى، ويرسل لك كلّ صباح ما يخصّ قطاعك ومدينتك فقط — مع شروط كلّ صفقة مبسّطة: الضمانة، التأهيل، زيارة الموقع، آخر أجل.",
        "",
        f"✅ {essai} أيّام مجّانية، بدون بطاقة بنكية",
        "👉 {LIEN}",
    ]))
    ajoute("facebook", "fr", "Facebook — Français", "\n".join([
        f"📢 {_n(m['actifs'])} marchés publics ouverts au Maroc, lancés par {_n(m['acheteurs'])} acheteurs publics.",
        "",
        "Parmi eux :",
        *_lignes_marches(m["vitrine"], "fr"),
        "",
        "Maroc Entrepreneuriat rassemble les appels d'offres et vous envoie chaque matin ceux de votre secteur et de votre ville — avec les conditions déjà lues : caution, qualification, visite des lieux, heure limite.",
        "",
        f"✅ {essai} jours gratuits, sans carte bancaire",
        "👉 {LIEN}",
    ]))

    # ── LinkedIn: dirigeants et responsables commerciaux, ton factuel ──
    ajoute("linkedin", "fr", "LinkedIn — Français", "\n".join([
        f"Cette semaine, {_n(m['actifs'])} marchés publics sont ouverts au Maroc, "
        f"lancés par {_n(m['acheteurs'])} acheteurs publics.",
        "",
        f"Les secteurs les plus demandés : {secteurs_fr}.",
        "",
        "Trois exemples encore préparables :",
        *_lignes_marches(m["vitrine"], "fr", "→"),
        "",
        "Le frein, pour une PME, n'est pas l'accès à l'information : c'est le temps de la trier. "
        "Un avis de vingt champs pour savoir s'il faut une caution, un agrément ou une visite "
        "obligatoire ; des dizaines de publications par jour pour en trouver deux dans son métier.",
        "",
        "C'est ce que fait Maroc Entrepreneuriat : la veille quotidienne par secteur et par ville, "
        "les conditions de chaque avis en clair, les résultats d'attribution et la mise en relation "
        "pour la sous-traitance.",
        "",
        f"Essai {essai} jours, sans engagement : {{LIEN}}",
        "",
        "#MarchésPublics #Maroc #PME #AppelsDOffres #Entrepreneuriat",
    ]))

    # ── Instagram: légende courte, le lien va dans la bio ──
    ajoute("instagram", "ar", "Instagram — légende (lien en bio)", "\n".join([
        f"{m['actifs']} صفقة عمومية مفتوحة الآن 🇲🇦",
        "",
        "توصلك كلّ صباح صفقات قطاعك فقط، بشروطها مبسّطة.",
        f"{essai} أيّام مجّانًا — الرابط في البايو 🔗",
        "",
        "#صفقات_عمومية #المغرب #مقاولات #طلبات_العروض #MarchésPublics",
    ]))

    # ── WhatsApp: statuts et groupes de métier, très court ──
    ajoute("whatsapp", "ar", "WhatsApp — statut / groupes (العربية)", "\n".join([
        f"*{m['actifs']} صفقة عمومية مفتوحة الآن* 📢",
        *_lignes_marches(m["vitrine"][:2], "ar", "•"),
        "",
        f"صفقات قطاعك كلّ صباح — {essai} أيّام مجّانًا:",
        "{LIEN}",
    ]))
    ajoute("whatsapp", "fr", "WhatsApp — statut / groupes (Français)", "\n".join([
        f"*{_n(m['actifs'])} marchés publics ouverts* 📢",
        *_lignes_marches(m["vitrine"][:2], "fr", "•"),
        "",
        f"Ceux de votre secteur chaque matin — {essai} jours gratuits :",
        "{LIEN}",
    ]))
    return pubs


def bilan_canaux() -> list:
    """Par canal: inscrits, email confirmé, abonnés payants, inscrits sur 30 jours.

    Le payant est la colonne qui compte: un canal qui amène cent essais et
    aucun abonné coûte du temps sans rien rapporter.
    """
    depuis = (datetime.now() - timedelta(days=30)).isoformat()
    payants = ",".join("?" * len(PAID_PLANS))
    db = get_db()
    try:
        lignes = db.execute(
            f"""SELECT COALESCE(source,''), COUNT(*),
                       SUM(CASE WHEN email_verified=1 THEN 1 ELSE 0 END),
                       SUM(CASE WHEN plan IN ({payants}) THEN 1 ELSE 0 END),
                       SUM(CASE WHEN created_at >= ? THEN 1 ELSE 0 END)
                FROM members GROUP BY 1""", (*PAID_PLANS, depuis)).fetchall()
        campagnes = {}
        for src, cmp, n in db.execute(
                """SELECT COALESCE(source,''), source_campagne, COUNT(*) FROM members
                   WHERE COALESCE(source_campagne,'')!='' GROUP BY 1, 2
                   ORDER BY 3 DESC""").fetchall():
            campagnes.setdefault(src, []).append((cmp, n))
    finally:
        db.close()
    ordre = list(CANAUX) + list(CANAUX_DEDUITS)
    bilan = [{"cle": s, "label": libelle(s), "inscrits": n, "confirmes": c or 0,
              "payants": p or 0, "recents": r or 0, "campagnes": campagnes.get(s, [])[:4]}
             for s, n, c, p, r in lignes]
    bilan.sort(key=lambda x: (-x["payants"], -x["inscrits"],
                              ordre.index(x["cle"]) if x["cle"] in ordre else 99))
    return bilan


def bilan_invitations() -> dict:
    """La prospection directe dans le même tableau: envoyées, ouvertes, inscrites."""
    db = get_db()
    try:
        r = db.execute(
            """SELECT SUM(CASE WHEN sent_at!='' THEN 1 ELSE 0 END),
                      SUM(CASE WHEN opened_at!='' THEN 1 ELSE 0 END),
                      SUM(CASE WHEN member_id>0 THEN 1 ELSE 0 END)
               FROM invitations""").fetchone()
    finally:
        db.close()
    return {"envoyees": r[0] or 0, "ouvertes": r[1] or 0, "inscrites": r[2] or 0}
