# -*- coding: utf-8 -*-
"""La lecture du dossier de consultation: CPS et règlement de consultation.

Un cahier des prescriptions spéciales fait trente à cent cinquante pages.
L'entreprise y cherche une dizaine de choses — les pièces à fournir, les
critères d'évaluation, le délai d'exécution, les pénalités, la retenue de
garantie, le délai de paiement, si les prix sont fermes — et le bordereau
des prix à chiffrer. Elles suivent la même trame d'un acheteur à l'autre
(CCAG-Travaux, décret des marchés publics): un repérage par articles et par
formules suffit à les retrouver.

Deux règles:

- **chaque valeur vient avec la phrase d'où elle est tirée.** L'entreprise
  vérifie d'un coup d'œil; et une lecture automatique qui se tromperait sans
  montrer sa source serait pire que pas de lecture du tout;
- **une clause « à vérifier » n'est pas une clause « illégale ».** On
  signale ce qui s'écarte des usages (pénalité au-delà d'un millième par
  jour, plafond au-delà de 10 %, paiement au-delà de 60 jours…) pour que
  l'entreprise le lise de près, sans prétendre trancher.

Le fichier n'est pas conservé: seul le résultat de la lecture l'est.
"""
import io
import re
import unicodedata
import zipfile

TAILLE_MAX = 25 * 1024 * 1024
PAGES_MAX = 400
FICHIERS_ZIP_MAX = 12


# ─── Extraction du texte ─────────────────────────────────────────────────

def _texte_pdf(contenu: bytes) -> str:
    from pypdf import PdfReader
    lecteur = PdfReader(io.BytesIO(contenu))
    morceaux = []
    for i, page in enumerate(lecteur.pages):
        if i >= PAGES_MAX:
            break
        try:
            morceaux.append(page.extract_text() or "")
        except Exception:
            continue
    return "\n".join(morceaux)


def _texte_docx(contenu: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(contenu)) as z:
        xml = z.read("word/document.xml").decode("utf-8", "ignore")
    xml = re.sub(r"</w:p>", "\n", xml)
    xml = re.sub(r"<w:tab/>", "\t", xml)
    texte = re.sub(r"<[^>]+>", "", xml)
    for a, b in (("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'), ("&apos;", "'")):
        texte = texte.replace(a, b)
    return texte


def extraire_texte(contenu: bytes, nom: str) -> tuple:
    """(texte, [noms des pièces lues]) — une archive du portail est ouverte
    et ses PDF et DOCX lus l'un après l'autre."""
    nom = (nom or "").lower()
    if contenu[:4] == b"%PDF" or nom.endswith(".pdf"):
        return _texte_pdf(contenu), [nom]
    if contenu[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(contenu)) as z:
            noms = z.namelist()
            if "word/document.xml" in noms:
                return _texte_docx(contenu), [nom]
            textes, lus = [], []
            for n in noms:
                if len(lus) >= FICHIERS_ZIP_MAX:
                    break
                bas = n.lower()
                if not bas.endswith((".pdf", ".docx")):
                    continue
                info = z.getinfo(n)
                if info.file_size > TAILLE_MAX:
                    continue
                donnees = z.read(n)
                try:
                    t, _ = extraire_texte(donnees, bas)
                except Exception:
                    continue
                textes.append(f"\n===== {n} =====\n{t}")
                lus.append(n.split("/")[-1])
            return "\n".join(textes), lus
    raise ValueError("format")


# ─── Lecture ─────────────────────────────────────────────────────────────

def _nu(texte: str) -> str:
    d = unicodedata.normalize("NFD", (texte or "").lower())
    return "".join(c for c in d if unicodedata.category(c) != "Mn")


def _phrases(texte: str) -> list:
    t = re.sub(r"[ \t]+", " ", texte or "")
    t = re.sub(r"-\n(\w)", r"\1", t)
    morceaux = re.split(r"(?<=[.;:])\s+(?=[A-ZÉÈÀÂ0-9«(])|\n{2,}", t)
    return [re.sub(r"\s+", " ", m).strip() for m in morceaux if len(m.strip()) > 15]


def _cherche(phrases: list, mots: tuple, motif: str = None, exclure: tuple = ()):
    """La première phrase qui contient l'un des mots (et le motif, s'il y en a un)."""
    for p in phrases:
        n = _nu(p)
        if any(m in n for m in mots) and not any(x in n for x in exclure):
            if motif is None:
                return p, None
            # Le chiffre se cherche après le mot-clé: un titre d'article
            # collé à la phrase suivante (« CAUTIONNEMENT DEFINITIF ET
            # RETENUE DE GARANTIE — Le cautionnement est fixé à 3 % »)
            # donnerait sinon à la retenue le taux du cautionnement.
            for mot in mots:
                debut = n.find(mot)
                while debut >= 0:
                    original = p[debut:debut + len(mot)] if len(p) == len(n) else ""
                    # En capitales, c'est un titre d'article: le chiffre qui
                    # le suit appartient à la phrase d'après.
                    if not (original and original.isupper()):
                        m = re.search(motif, n[debut:])
                        if m:
                            return p[debut:] if len(p) == len(n) else p, m
                    debut = n.find(mot, debut + 1)
    return None, None


def _extrait(p: str, longueur: int = 320) -> str:
    return p if len(p) <= longueur else p[:longueur].rsplit(" ", 1)[0] + "…"


def _articles(texte: str) -> list:
    """[(titre, corps)] — découpe par « ARTICLE n : titre »."""
    morceaux = re.split(r"(?im)^\s*(?:article|art\.)\s*(\d+[\w.\-]*)\s*[:.\-–—]?\s*", texte or "")
    articles = []
    for i in range(1, len(morceaux) - 1, 2):
        corps = morceaux[i + 1]
        titre = corps.strip().split("\n", 1)[0][:140]
        articles.append((f"Article {morceaux[i]} — {titre}", corps[:6000]))
    return articles


def _liste(corps: str, limite: int = 25) -> list:
    """Les éléments d'une énumération: tirets, puces, lettres ou chiffres."""
    lignes = []
    for l in corps.split("\n"):
        l = l.strip()
        if re.match(r"^([-–•▪●*]|[a-z]\)|\d{1,2}[).-]|[ivx]+[).-])\s+\S", l, re.I) and len(l) > 6:
            lignes.append(re.sub(r"^([-–•▪●*]|[a-z]\)|\d{1,2}[).-]|[ivx]+[).-])\s+", "", l, flags=re.I)[:220])
        if len(lignes) >= limite:
            break
    return lignes


_UNITES = r"(?:u|unite|unité|ens|ensemble|f|forfait|ft|m2|m²|m3|m³|ml|m|kg|t|tonne|l|litre|j|jour|h|heure|km|mois|pm)"
_LIGNE_PRIX = re.compile(
    rf"^\s*(\d{{1,3}}(?:[.,]\d{{1,3}}){{0,3}})\s+(.{{4,180}}?)\s+({_UNITES})\.?\s+(\d[\d\s.,]*)\s*$",
    re.IGNORECASE)


def bordereau(texte: str, limite: int = 400) -> list:
    """Les lignes du bordereau des prix: numéro, désignation, unité, quantité."""
    lignes, vus = [], set()
    for l in (texte or "").split("\n"):
        m = _LIGNE_PRIX.match(l.strip())
        if not m:
            continue
        cle = (m.group(1), m.group(2)[:40])
        if cle in vus:
            continue
        vus.add(cle)
        lignes.append({"n": m.group(1), "designation": re.sub(r"\s+", " ", m.group(2)).strip(),
                       "unite": m.group(3), "quantite": m.group(4).strip()})
        if len(lignes) >= limite:
            break
    return lignes


def _nombre(texte: str) -> float:
    t = (texte or "").replace(" ", "").replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return 0.0


def analyser_texte(texte: str) -> dict:
    """Le résumé du dossier. Chaque entrée: {"valeur", "source", "alerte"}."""
    phrases = _phrases(texte)
    r = {}

    def pose(cle, valeur, source, alerte=""):
        if valeur and source:
            r[cle] = {"valeur": valeur, "source": _extrait(source), "alerte": alerte}

    # Délai d'exécution
    p, m = _cherche(phrases, ("delai d'execution", "delai d’execution", "delai global"),
                    r"(\d{1,4})\s*(jours?|mois|semaines?)")
    if m:
        pose("delai_execution", f"{m.group(1)} {m.group(2)}", p)

    # Pénalités de retard: « 1/1000 », « un millième », « 1‰ »
    p, m = _cherche(phrases, ("penalit",), r"(\d+(?:[.,]\d+)?)\s*/\s*1\s?000|(\d+(?:[.,]\d+)?)\s*‰|(un|deux|trois)\s+milliemes?")
    if m:
        mots = {"un": 1, "deux": 2, "trois": 3}
        taux = _nombre(m.group(1) or m.group(2) or "") or mots.get(m.group(3) or "", 0)
        pose("penalites", f"{taux:g}/1000 du montant par jour de retard", p,
             "plus d'un millième par jour" if taux > 1 else "")
    plaf_p, plaf_m = _cherche(phrases, ("penalit",), r"(?:plafon\w*|limit\w*|n'?excede\w*|ne (?:peut|doit|pourra) (?:depasser|exceder))\D{0,60}?(\d{1,2}(?:[.,]\d+)?)\s*%")
    if plaf_m:
        plafond = _nombre(plaf_m.group(1))
        pose("plafond_penalites", f"{plafond:g} % du montant du marché", plaf_p,
             "plafond supérieur à 10 %" if plafond > 10 else "")

    # Cautionnement définitif et retenue de garantie
    p, m = _cherche(phrases, ("cautionnement definitif", "caution definitive"), r"(\d{1,2}(?:[.,]\d+)?)\s*%")
    if m:
        pose("caution_definitive", f"{_nombre(m.group(1)):g} % du montant initial", p)
    p, m = _cherche(phrases, ("retenue de garantie",), r"(\d{1,2}(?:[.,]\d+)?)\s*%")
    if m:
        taux = _nombre(m.group(1))
        pose("retenue_garantie", f"{taux:g} % de chaque paiement", p,
             "retenue supérieure à 10 %" if taux > 10 else "")
    p, m = _cherche(phrases, ("delai de garantie",), r"(\d{1,3})\s*(mois|ans?|annees?|jours?)")
    if m:
        pose("delai_garantie", f"{m.group(1)} {m.group(2)}", p)

    # Paiement
    p, m = _cherche(phrases, ("delai de paiement", "paiement", "reglement"),
                    r"(?:dans un delai|delai)\D{0,40}?(\d{1,3})\s*jours?")
    if m:
        jours = int(m.group(1))
        pose("paiement", f"{jours} jours", p, "au-delà de 60 jours" if jours > 60 else "")

    # Prix fermes ou révisables
    p, _ = _cherche(phrases, ("prix fermes", "prix sont fermes", "fermes et non revisables",
                              "non revisables"))
    if p:
        pose("prix", "Fermes et non révisables", p)
    else:
        p, _ = _cherche(phrases, ("revisables", "revision des prix"), exclure=("non revisable",))
        if p:
            pose("prix", "Révisables", p)

    # Avance
    p, m = _cherche(phrases, ("avance",), r"(\d{1,2}(?:[.,]\d+)?)\s*%")
    if m:
        pose("avance", f"{_nombre(m.group(1)):g} % du montant", p)
    else:
        p, _ = _cherche(phrases, ("pas d'avance", "aucune avance", "il n'est pas prevu d'avance",
                                  "sans avance"))
        if p:
            pose("avance", "Aucune avance", p)

    # Variante, sous-traitance, assurance
    p, _ = _cherche(phrases, ("sous-traitance", "sous traitance"))
    if p:
        n = _nu(p)
        pose("sous_traitance", "Interdite" if re.search(r"interdi|n'est pas autoris|pas admis", n)
             else "Encadrée — lire la clause", p)

    # Les listes: pièces à fournir et critères
    pieces, criteres = [], []
    for titre, corps in _articles(texte):
        tn = _nu(titre)
        if not pieces and any(m in tn for m in ("pieces", "contenu des dossiers", "composition du dossier",
                                                "dossier administratif")):
            pieces = _liste(corps)
        if not criteres and any(m in tn for m in ("critere", "evaluation des offres", "jugement",
                                                  "admissibilite", "notation")):
            criteres = _liste(corps)
    r["pieces"] = pieces
    r["criteres"] = criteres
    r["bordereau"] = bordereau(texte)
    r["alertes"] = [k for k, v in r.items() if isinstance(v, dict) and v.get("alerte")]
    r["nb_caracteres"] = len(texte or "")
    return r


def analyser(contenu: bytes, nom: str) -> dict:
    """Lit un fichier déposé et rend l'analyse, ou {"erreur": code}."""
    if not contenu:
        return {"erreur": "vide"}
    if len(contenu) > TAILLE_MAX:
        return {"erreur": "taille"}
    try:
        texte, lus = extraire_texte(contenu, nom)
    except Exception:
        return {"erreur": "format"}
    # Un PDF scanné n'a pas de texte: on le dit, plutôt que de rendre une
    # analyse vide qui laisserait croire que le dossier ne pose rien.
    if len(re.sub(r"\s", "", texte)) < 400:
        return {"erreur": "scanne", "fichiers": lus}
    resultat = analyser_texte(texte)
    resultat["fichiers"] = lus
    return resultat
