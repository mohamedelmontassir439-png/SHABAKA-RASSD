# -*- coding: utf-8 -*-
"""Les conditions d'un appel d'offres, lues dans l'avis du portail.

Pour savoir s'il peut soumissionner, une entreprise devait ouvrir l'avis,
puis souvent le dossier entier: quelle caution provisoire, quel agrément,
une visite des lieux obligatoire, des échantillons à déposer, un marché
réservé aux TPE et PME… Ces réponses tiennent en une quinzaine de champs,
et le portail les publie tous sur la page de l'avis.

Nous les avions déjà: la description stockée d'un appel d'offres est le
texte de cette page, à partir de « Référence ». Mesuré le 20/10/2026 sur 218
avis: la caution, les qualifications, les agréments, le lieu d'ouverture
des plis y figurent dans 100 % des cas, la visite, la réunion, la variante
et le contact dans 99 %. On les lit donc à l'affichage — sans recharger le
portail, et sans migrer la base: les avis déjà collectés en profitent tout
de suite.

L'heure limite fait exception: elle précède « Référence » sur la page, et
la coupe la faisait tomber pour deux avis sur trois. La collecte la garde
désormais en tête de la description.
"""
import re

# Les étiquettes du portail, dans l'ordre où elles se suivent sur la page.
# La valeur d'une étiquette court jusqu'à la suivante: c'est leur
# succession, et non une mise en forme, qui délimite les champs. Celles qui
# n'ont pas de clé servent seulement de bornes.
_ETIQUETTES = (
    ("limite",        r"Date et heure limite de remise des plis"),
    ("reference",     r"Référence"),
    (None,            r"Objet"),
    (None,            r"Acheteur public"),
    (None,            r"Type d'annonce"),
    ("procedure",     r"Procédure"),
    ("categorie",     r"Catégorie principale"),
    ("allotissement", r"Allotissement"),
    ("lieu",          r"Lieu d'exécution"),
    ("estimation",    r"Estimation \(en Dhs TTC\)\s*\*?"),
    ("reserve",       r"Réservé à la TPE et PME[^:]{0,140}?\*?"),
    ("domaines",      r"Domaines d'activité"),
    ("retrait",       r"Adresse de retrait des dossiers"),
    ("depot",         r"Adresse de dépôt des offres"),
    ("ouverture",     r"Lieu d'ouverture des plis"),
    ("prix_plans",    r"Prix d'acquisition des plans"),
    ("caution",       r"Caution provisoire"),
    ("qualifications", r"Qualifications"),
    ("agrements",     r"Agréments"),
    ("echantillons",  r"Prospectus, notices ou autres documents"),
    ("reunion",       r"Réunion"),
    ("visite",        r"Visites des lieux"),
    ("variante",      r"Variante"),
    ("contact",       r"Contact Administratif"),
)

# Ce qui suit le dernier champ sur la page: le bloc de signature
# électronique, sans intérêt pour le soumissionnaire.
_FIN = re.compile(r"champsvide|Vous ne pouvez pas|Jeton de signature|Certificat émis",
                  re.IGNORECASE)

# « Référence » est la seule étiquette sans deux-points sur la page
# (« Référence 81/2026/DR9 Objet : … »). On la reconnaît au numéro qui la
# suit, pour ne pas couper sur le mot employé dans un objet.
_SANS_DEUX_POINTS = {"reference": r"(?=\s+\S*\d)"}

_MOTIF = re.compile("|".join(
    f"(?P<e{i}>{motif})" + _SANS_DEUX_POINTS.get(cle, r"\s*:")
    for i, (cle, motif) in enumerate(_ETIQUETTES)))


def _propre(valeur: str) -> str:
    """Retire les signes du portail et rend "" pour une case vide."""
    v = re.sub(r"@{2,}|\*", " ", valeur or "")
    # Le portail sépare certaines valeurs d'une barre: « Appel d'offres
    # ouvert | Sur offre de prix ».
    v = re.sub(r"\s*\|\s*", " · ", v)
    v = re.sub(r"\s+", " ", v).strip(" :|·-–—")
    # La visite, la réunion et les échantillons portent un sous-champ
    # « Date et heure » — resté seul quand l'acheteur n'en prévoit pas.
    v = re.sub(r"^Date et heure(?: limite)?\s*:?\s*", "", v).strip(" :,")
    # « TAOURIRT TAOURIRT »: le portail répète la ville quand la province
    # porte son nom.
    mots = v.split(" ")
    if len(mots) % 2 == 0 and mots[: len(mots) // 2] == mots[len(mots) // 2:]:
        v = " ".join(mots[: len(mots) // 2])
    return "" if v in ("", "-", "—", "Néant", "néant", "NEANT") else v


def conditions_avis(texte: str) -> dict:
    """Les champs de l'avis, par clé. Un champ absent ou vide n'y figure pas.

    Rend {} pour un texte qui n'est pas un avis du portail — un bon de
    commande, une source privée: la fiche n'affiche alors rien de plus.
    """
    t = re.sub(r"\s+", " ", texte or "")
    fin = _FIN.search(t)
    if fin:
        t = t[: fin.start()]

    reperes = []
    for m in _MOTIF.finditer(t):
        i = int(next(k for k, v in m.groupdict().items() if v is not None)[1:])
        reperes.append((m.start(), m.end(), _ETIQUETTES[i][0]))

    champs = {}
    for n, (_, fin_etiquette, cle) in enumerate(reperes):
        if not cle or cle in champs:
            continue
        borne = reperes[n + 1][0] if n + 1 < len(reperes) else len(t)
        valeur = _propre(t[fin_etiquette:borne])
        if valeur:
            champs[cle] = valeur[:300]
    return champs


# ─── Ce qu'on en dit au membre ────────────────────────────────────────────

def _montant_nul(valeur: str) -> bool:
    return not re.search(r"[1-9]", valeur or "")


def cartes(cond: dict) -> list:
    """Les cases à afficher, dans l'ordre où un soumissionnaire se pose les
    questions: puis-je répondre, que dois-je préparer, où et quand déposer.

    Chaque case: (clé du libellé, valeur affichée, clé de l'aide ou "",
    exigence). Une exigence est ce qui écarte une offre si on l'ignore — la
    caution, l'agrément, la visite obligatoire: on les signale.

    Une case vide n'est pas omise quand son absence est elle-même une
    information: « aucune caution », « aucun agrément exigé » disent à
    l'entreprise qu'elle peut y aller.
    """
    if not cond:
        return []
    c = []

    if cond.get("limite"):
        c.append(("cond_limite", cond["limite"], "cond_limite_aide", True))

    reserve = (cond.get("reserve") or "").lower()
    if reserve.startswith("oui"):
        c.append(("cond_reserve", "oui", "cond_reserve_aide", True))
    elif reserve.startswith("non"):
        c.append(("cond_reserve", "non", "", False))

    # Un marché en lots se soumissionne lot par lot. Le portail range alors
    # caution et qualifications dans le tableau des lots, et laisse les
    # champs généraux vides: vide ne veut pas dire « aucune ». Mesuré le
    # 20/10/2026: les 26 avis sans caution étaient tous des marchés en lots.
    en_lots = bool(re.search(r"[2-9]|\d{2}", cond.get("allotissement", "")))
    if en_lots:
        c.append(("cond_lots", cond["allotissement"], "cond_lots_aide", False))

    caution = cond.get("caution", "")
    if caution and not _montant_nul(caution):
        c.append(("cond_caution", caution, "cond_caution_aide", True))
    elif en_lots:
        c.append(("cond_caution", "par_lot", "cond_caution_aide", True))
    else:
        c.append(("cond_caution", "aucune", "", False))

    if cond.get("agrements"):
        c.append(("cond_agrement", cond["agrements"], "cond_agrement_aide", True))
    if cond.get("qualifications"):
        # Une ligne par qualification: le texte brut enchaîne ministère,
        # secteur et classe et se lit mal dès la deuxième.
        from app.core.lecture import qualifications_lisibles
        c.append(("cond_qualification", " · ".join(qualifications_lisibles(cond["qualifications"])),
                  "cond_qualification_aide", True))
    if not cond.get("agrements") and not cond.get("qualifications") and not en_lots:
        c.append(("cond_agrement", "aucun", "", False))

    if cond.get("visite"):
        c.append(("cond_visite", cond["visite"], "cond_visite_aide", True))
    if cond.get("reunion"):
        c.append(("cond_reunion", cond["reunion"], "", False))
    if cond.get("echantillons"):
        c.append(("cond_echantillons", cond["echantillons"], "cond_echantillons_aide", True))

    variante = (cond.get("variante") or "").lower()
    if variante:
        c.append(("cond_variante", "oui" if variante.startswith("oui") else "non", "", False))

    depot = cond.get("depot", "")
    if depot:
        bas = depot.lower()
        c.append(("cond_depot", "electronique" if "marchespublics.gov.ma" in bas
                  or "électronique" in bas else depot, "", False))
    if cond.get("ouverture"):
        c.append(("cond_ouverture", cond["ouverture"], "", False))

    prix = cond.get("prix_plans", "")
    if prix:
        c.append(("cond_plans", "gratuit" if _montant_nul(prix) else prix, "", False))

    if cond.get("procedure"):
        c.append(("cond_procedure", cond["procedure"], "", False))
    if cond.get("contact"):
        c.append(("cond_contact", cond["contact"], "cond_contact_aide", False))
    return c


def contact_detaille(valeur: str) -> dict:
    """« Najat MEZIANE najatm4@gmail.com 06 60 13 44 64 » en trois morceaux,
    pour que l'email s'écrive et que le numéro se compose d'un doigt."""
    v = valeur or ""
    mail = re.search(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", v)
    # Un service publie souvent deux numéros: on garde le premier, mais on
    # les retire tous du nom — sinon le second s'y collait.
    tels = re.findall(r"(?:\+?212|0)\s*[5-7](?:[\s.]?\d){8}", v)
    nom = v.replace(mail.group(0), " ") if mail else v
    for numero in tels:
        nom = nom.replace(numero, " ")
    return {"nom": re.sub(r"\s+", " ", nom).strip(" ·"),
            "email": mail.group(0) if mail else "",
            "tel": re.sub(r"[^\d+]", "", tels[0]) if tels else ""}
