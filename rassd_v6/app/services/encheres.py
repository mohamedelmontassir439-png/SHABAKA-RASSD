# -*- coding: utf-8 -*-
"""Ventes de la douane (douane.gov.ma): ventes sur appel d'offres de prix
(plis fermés) et ventes aux enchères publiques.

Repris de l'outil local « douane_radar » (08/11/2026), adapté au site:
- les PDF sont lus en mémoire et jamais gardés: le disque du serveur est
  compté (panne du 15/11/2026);
- les catégories et les pièces demandées portent une clé, traduite à
  l'affichage (fr/ar);
- la collecte tourne sur le relais au Maroc, comme celle du portail des
  marchés, et sur le serveur quand le site de la douane lui répond.

Pièges de lecture constatés sur les avis:
- le « (jj.mm) » de la liste est le jour d'ouverture des plis, pas la date
  limite de dépôt;
- les dates s'écrivent 05/11/2026, 24-11-2026, 17.11.2026 ou « 09 Novembre 2026 »;
- la mention CNDP porte une date (17/03/2023) qu'il faut ignorer;
- une caution peut se coller à la quantité qui la précède (« 230 300.000,00 »);
- certains avis (ventes judiciaires) sont des PDF scannés sans texte.
"""
import html
import io
import json
import logging
import re
import time
from datetime import date, datetime

logger = logging.getLogger("encheres")
logging.getLogger("pypdf").setLevel(logging.ERROR)

BASE = "https://www.douane.gov.ma"
PAGES = {
    "aop": BASE + "/web/guest/ventes-sur-appel-offres-prix",   # plis fermés
    "ep": BASE + "/web/guest/ventes-aux-encheres-publiques",   # enchère publique
}
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) MarocEntrepreneuriat/1"}
DELAI_PDF = 1.5        # politesse envers le serveur de la douane
MAX_PDF = 8_000_000    # un avis fait quelques centaines de Ko

KINDS = {
    "aop": {"fr": "Vente sur appel d'offres de prix (plis fermés)",
            "ar": "بيع بطلب عروض الأثمان (أظرفة مغلقة)"},
    "ep": {"fr": "Vente aux enchères publiques", "ar": "مزاد علني"},
}

# (clé, emoji, fr, ar, mots-clés) — le premier qui correspond l'emporte:
# le particulier avant le général.
CATEGORIES = [
    ("immobilier", "🏠", "Immobilier (vente judiciaire)", "عقار (بيع قضائي)",
     ["judiciaire", "immeuble", "bien à", "terrain", "appartement"]),
    ("telephones", "📱", "Téléphones et électronique", "هواتف وإلكترونيات",
     ["téléphone", "telephone", "smartphone", "portable", "tablette", "électronique",
      "iphone", "samsung", "galaxy", "redmi", "xiaomi", "huawei", "oppo", "infinix", "tecno", "ipad"]),
    ("or", "💍", "Or et bijoux", "ذهب ومجوهرات", [" or ", "bijou", "lingot"]),
    ("montres", "⌚", "Montres", "ساعات", ["montre"]),
    ("parfums", "🧴", "Parfums et cosmétiques", "عطور ومستحضرات", ["parfum", "cosmét"]),
    ("lunettes", "🕶️", "Lunettes", "نظارات", ["lunette"]),
    ("habillement", "👕", "Habillement et chaussures", "ملابس وأحذية",
     ["vestimentaire", "chaussant", "vêtement", "textile", "tissu", "chemise", "pantalon",
      "jean", "robe", "veste", "chaussure", "t-shirt", "pull", "sac "]),
    ("bateaux", "🚤", "Bateaux", "قوارب", ["bateau", "jetski", "jet ski", "embarcation"]),
    ("engins", "🚜", "Engins et matériel", "آليات وعتاد",
     ["tractopelle", "engin", "matériel", "materiel", "machine"]),
    ("ferraille", "♻️", "Ferraille", "خردة", ["ferraille", "feraille"]),
    ("vehicules", "🚗", "Véhicules et motos", "سيارات ودراجات",
     ["véhicule", "vehicule", "motocycle", "moto", "transport", "trottinette", "voiture"]),
    ("divers", "📦", "Marchandises diverses", "بضائع متنوعة", ["marchandise", "article", "lot"]),
]
ANNULATION = ("annulation", "❌", "Avis d'annulation", "إلغاء بيع")
_PAR_CLE = {c[0]: c for c in CATEGORIES + [ANNULATION + ([],)]}

PIECES = [
    ("registre de commerce", "rc"),
    ("quitus", "quitus"),
    ("attestation fiscale", "quitus"),
    ("ferrailleur", "ferrailleur"),
    ("agréé", "agree"),
    ("agrée", "agree"),
    ("comptabilit", "comptabilite"),
    ("pièce d’identité", "cin"),
    ("pièce d'identité", "cin"),
]
PIECES_LIBELLES = {
    "rc": {"fr": "Registre de commerce", "ar": "سجل تجاري"},
    "quitus": {"fr": "Attestation fiscale (quitus)", "ar": "شهادة الإبراء الضريبي"},
    "ferrailleur": {"fr": "Activité de ferrailleur", "ar": "مهنة الخردة"},
    "agree": {"fr": "Professionnel agréé dans l'activité", "ar": "مهني معتمد في النشاط"},
    "comptabilite": {"fr": "Entreprise tenant une comptabilité", "ar": "مقاولة ممسكة للمحاسبة"},
    "cin": {"fr": "Pièce d'identité", "ar": "بطاقة التعريف"},
}

MOIS = {"janvier": 1, "fevrier": 2, "février": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6,
        "juillet": 7, "aout": 8, "août": 8, "septembre": 9, "octobre": 10, "novembre": 11,
        "decembre": 12, "décembre": 12}

COLONNES = ("doc_id", "kind", "region", "title", "short_date", "url", "date_iso", "heure",
            "visite", "ouverture", "cautions", "pieces", "lots", "apercu", "categorie", "texte_len")


# Sur le site, les icônes du jeu de la marque (app/core/marque.py): pas
# d'emoji en couleur dans les pages (tests/test_icones.py). Les emoji
# restent dans les publications WhatsApp.
ICONES = {"immobilier": "immeuble", "telephones": "telephone", "or": "couronne", "lunettes": "loupe",
          "bateaux": "drapeau", "engins": "outils", "ferraille": "echange", "vehicules": "lieu",
          "divers": "dossiers", "annulation": "croix"}


def categorie(cle: str, lang: str = "fr") -> dict:
    c = _PAR_CLE.get(cle) or _PAR_CLE["divers"]
    return {"cle": c[0], "emoji": c[1], "icone": ICONES.get(c[0], "etiquette"),
            "nom": c[3] if lang == "ar" else c[2]}


def categories(lang: str = "fr") -> list:
    return [categorie(c[0], lang) for c in CATEGORIES]


def piece(cle: str, lang: str = "fr") -> str:
    p = PIECES_LIBELLES.get(cle)
    return (p.get(lang) or p["fr"]) if p else cle


def nature(kind: str, lang: str = "fr") -> str:
    k = KINDS.get(kind) or KINDS["aop"]
    return k.get(lang) or k["fr"]


# ── Liste des avis ─────────────────────────────────────────────────────────

def lire_liste(page_html: str, kind: str) -> list:
    """La page est une suite de <h3>direction</h3><ul><li><a href=doc>titre (jj.mm)</a></li>…"""
    corps = page_html.split('class="BlocCentent"', 1)[-1]
    out = []
    for bloc in re.split(r"<h3>", corps)[1:]:
        region = html.unescape(re.sub(r"<[^>]+>", "", bloc.split("</h3>", 1)[0])).strip()
        for href, inner in re.findall(r'<a href="(/dms/loadDocument\?documentId=\d+)">(.*?)</a>', bloc, re.S):
            texte = html.unescape(re.sub(r"<[^>]+>", " ", inner))
            texte = re.sub(r"\s+", " ", texte).strip()
            m = re.search(r"\((\d{1,2})\.(\d{1,2})\)", texte)
            court = f"{int(m.group(1)):02d}/{int(m.group(2)):02d}" if m else ""
            titre = re.sub(r"\s*\(\d{1,2}\.\d{1,2}\)\s*\.?\s*$", "", texte).strip()
            out.append({"doc_id": int(href.rsplit("=", 1)[1]), "kind": kind, "region": region[:200],
                        "title": titre[:500], "short_date": court, "url": BASE + href})
    return out


# ── Lecture de l'avis (PDF) ────────────────────────────────────────────────

def texte_pdf(contenu: bytes) -> str:
    try:
        import pypdf
        lecteur = pypdf.PdfReader(io.BytesIO(contenu))
        return "\n".join((p.extract_text() or "") for p in lecteur.pages)
    except Exception as e:  # un PDF abîmé ne doit pas arrêter la collecte
        logger.warning(f"[encheres] PDF illisible: {e}")
        return ""


def _plat(t: str) -> str:
    return re.sub(r"\s+", " ", t)


def trouver_dates(s: str) -> list:
    """Toutes les dates de s, en (position, date)."""
    vues = []
    for m in re.finditer(r"(\d{1,2})\s*[/.\-]\s*(\d{1,2})\s*[/.\-]\s*(\d{4})", s):
        try:
            vues.append((m.start(), date(int(m.group(3)), int(m.group(2)), int(m.group(1)))))
        except ValueError:
            pass
    for m in re.finditer(r"(\d{1,2})\s*(?:er)?\s+([A-Za-zéûÉ][A-Za-zéû ]{2,12}?)\s+(\d{4})", s):
        mois = MOIS.get(m.group(2).replace(" ", "").lower())
        if mois:
            try:
                vues.append((m.start(), date(int(m.group(3)), mois, int(m.group(1)))))
            except ValueError:
                pass
    return sorted(vues)


def date_apres(s: str, mots: list, fenetre: int = 220):
    bas = s.lower()
    for mot in mots:
        i = bas.find(mot)
        if i >= 0:
            for pos, d in trouver_dates(s[i:i + fenetre]):
                return d, s[i + pos:i + pos + 90]
    return None, ""


def lire_heure(extrait: str) -> str:
    m = re.search(r"(\d{1,2})\s*(?:heures?|h)\s*(\d{2})?", extrait)
    return f"{int(m.group(1)):02d}:{m.group(2) or '00'}" if m else ""


def lire_cautions(s: str) -> list:
    montants = []
    for m in re.finditer(r"caution", s.lower()):
        seg = s[m.start():m.start() + 400]
        for a in re.findall(r"\d{1,3}(?:[ . ]\d{3})+\s*,\s*\d{2}|\d{3,9}\s*,\s*\d{2}", seg):
            groupes = re.split(r"[ . ]", a.split(",")[0].strip())
            # « 230 300.000,00 » = quantité (230) puis caution (300.000,00):
            # une caution reste loin sous 20 M DH.
            while len(groupes) > 1 and int("".join(groupes)) > 20_000_000:
                groupes = groupes[1:]
            v = int("".join(groupes)) if groupes and all(g.isdigit() for g in groupes) else 0
            if v >= 500:
                montants.append(f"{v:,}".replace(",", " "))
    vus = []
    for a in montants:
        if a not in vus:
            vus.append(a)
    return vus[:4]


def lire_lots(texte: str) -> list:
    """Lignes du type « Téléphone portable de marque IPHONE 17 PRO MAX 256 GB  39 Neuf »."""
    lots = []
    for ligne in texte.splitlines():
        ligne = re.sub(r"\s+", " ", ligne).strip()
        m = re.search(r"([A-Za-zÀ-ÿ][\w\s/.+\-’'()]{5,90}?)\s+(\d{1,6})\s+(Neufs?|Usag[ée]e?s?|Occasion)\b", ligne, re.I)
        if m:
            nom = re.sub(r"^(Lot\s+\S+\s+)?(T[ée]l[ée]phone portable de marque\s+)?", "", m.group(1), flags=re.I).strip()
            lots.append({"nom": nom, "qte": int(m.group(2)),
                         "etat": "neuf" if m.group(3).lower().startswith("neuf") else "usage"})
    return lots


def apercu_lots(s: str) -> str:
    """Premiers mots du tableau des lots, pour les avis dont les lignes ne se lisent pas."""
    m = re.search(r"d[ée]signation", s, re.I)
    if not m:
        return ""
    seg = s[m.end():m.end() + 260]
    seg = re.split(r"L[’']ouverture|Conditions|Les offres", seg)[0]
    entete = r"(des\s+)?marchandises?|qt[ée]\s*\(u\)|quantit[ée]|etat|caution(\s*en)?(\s*\(?dh[s]?\s*\)?)?|lot(\s+unique)?|\(dh\s*\)"
    avant = None
    while avant != seg:
        avant = seg
        seg = re.sub(rf"^[\s:()\d/.\-]*(?:{entete})?[\s:()\d/.\-]*", "", seg, flags=re.I)
    return seg.strip(" :-")[:200]


def _norm(s: str) -> str:
    # ponctuation → espaces: « en or. » correspond à " or ", pas « ordinateur »
    return " " + re.sub(r"[^\wà-ÿ’']+", " ", s.lower()) + " "


def classer(titre: str, detail: str = "") -> str:
    """Catégorie d'après le titre; si le titre est générique, d'après les lots."""
    bas = titre.lower()
    if bas.startswith("avis d'annulation") or bas.startswith("avis d’annulation"):
        return "annulation"
    t = _norm(titre)
    for c in CATEGORIES[:-1]:
        if any(k in t for k in c[4]):
            return c[0]
    d = _norm(detail)
    meilleure = max(CATEGORIES[1:-1], key=lambda c: sum(d.count(k) for k in c[4]))
    if sum(d.count(k) for k in meilleure[4]) > 0:
        return meilleure[0]
    return "divers"


def date_courte(court: str, aujourdhui: date) -> str:
    """« 24/11 » → date ISO, dans l'année la plus proche."""
    if not court:
        return ""
    j, m = map(int, court.split("/"))
    annee = aujourdhui.year + (1 if m < aujourdhui.month - 6 else 0)
    try:
        return date(annee, m, j).isoformat()
    except ValueError:
        return ""


def analyser(avis: dict, texte: str, aujourdhui: date = None) -> dict:
    """Ajoute à l'avis (ligne de la liste) ce que dit son PDF."""
    aujourdhui = aujourdhui or date.today()
    kind, titre = avis["kind"], avis.get("title", "")
    s = _plat(texte)
    s_dates = re.sub(r"CNDP.{0,200}?\d{4}", " ", s)
    if kind == "aop":
        d, extrait = date_apres(s_dates, ["jusqu", "date limite", "au plus tard"])
    else:
        d, extrait = date_apres(s_dates, ["procédera le", "procedera le", "aura lieu le", "aura lieu"])
    if not d:  # PDF scanné: le titre porte parfois la date
        d, extrait = date_apres(titre, ["lieu le", "le "], fenetre=len(titre))
    ouverture, _ = date_apres(s_dates, ["ouverture des plis"], fenetre=200)
    visite, _ = date_apres(s_dates, ["visit"], fenetre=200)
    bas = s.lower()
    pieces = []
    for mot, cle in PIECES:
        if mot in bas and cle not in pieces:
            pieces.append(cle)
    lots = lire_lots(texte)[:40]
    apercu = apercu_lots(s)
    r = dict(avis)
    r.update({
        "texte_len": len(texte),
        "date_iso": d.isoformat() if d else date_courte(avis.get("short_date", ""), aujourdhui),
        "heure": lire_heure(extrait) if (d and extrait) else "",
        "visite": visite.isoformat() if visite else "",
        "ouverture": (ouverture.isoformat() if ouverture else
                      (date_courte(avis.get("short_date", ""), aujourdhui) if kind == "aop" else "")),
        "cautions": lire_cautions(s),
        "pieces": pieces,
        "lots": lots,
        "apercu": apercu,
        "categorie": classer(titre, " ".join(l["nom"] for l in lots) + " " + apercu),
    })
    return r


# ── Collecte ───────────────────────────────────────────────────────────────

def collecter(connus: set, log=lambda m: None, session=None) -> tuple:
    """Lit les deux pages de la douane et les PDF des avis inconnus.

    Renvoie (avis nouveaux analysés, identifiants présents sur le site).
    Lève ConnectionError si le site de la douane ne répond pas.
    """
    import requests
    s = session or requests.Session()
    s.headers.update(HEADERS)
    presents, nouveaux = [], []
    for kind, url in PAGES.items():
        try:
            r = s.get(url, timeout=30)
            r.raise_for_status()
        except requests.RequestException as e:
            raise ConnectionError(f"douane.gov.ma injoignable: {e}") from e
        r.encoding = "utf-8"
        lignes = lire_liste(r.text, kind)
        if not lignes and "BlocCentent" not in r.text:
            raise ConnectionError("douane.gov.ma: page des ventes méconnaissable")
        log(f"Douane · {kind}: {len(lignes)} avis en ligne")
        for ligne in lignes:
            presents.append(ligne["doc_id"])
            if ligne["doc_id"] in connus:
                continue
            time.sleep(DELAI_PDF)
            try:
                p = s.get(ligne["url"], timeout=60)
                p.raise_for_status()
                contenu = p.content[:MAX_PDF]
            except requests.RequestException as e:
                log(f"  ⚠ PDF {ligne['doc_id']} non téléchargé: {e}")
                continue
            avis = analyser(ligne, texte_pdf(contenu))
            nouveaux.append(avis)
            connus.add(ligne["doc_id"])
            log(f"  + {avis['doc_id']} {avis['categorie']} | {avis['date_iso']} | {avis['title'][:70]}")
    return nouveaux, presents


# ── Base ───────────────────────────────────────────────────────────────────

def ids_connus(db) -> set:
    return {r[0] for r in db.execute("SELECT doc_id FROM encheres")}


def valide(a: dict) -> bool:
    try:
        return (int(a.get("doc_id", 0)) > 0 and a.get("kind") in KINDS
                and str(a.get("url", "")).startswith(BASE + "/dms/loadDocument?documentId=")
                and bool(str(a.get("title", "")).strip()))
    except (TypeError, ValueError):
        return False


def enregistrer(db, avis: list, presents: list = None) -> list:
    """Insère les avis inconnus; renvoie ceux qui sont nouveaux.

    `presents`: identifiants vus sur le site de la douane à cet instant —
    les autres sont marqués retirés (gardés, mais plus montrés).
    """
    maintenant = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    nouveaux = []
    for a in avis:
        if not valide(a):
            continue
        ligne = {k: a.get(k, "") for k in COLONNES}
        ligne["doc_id"] = int(ligne["doc_id"])
        for k in ("cautions", "pieces", "lots"):
            v = a.get(k) or []
            ligne[k] = json.dumps(v if isinstance(v, list) else [], ensure_ascii=False)[:20000]
        for k in ("region", "title", "short_date", "url", "date_iso", "heure", "visite",
                  "ouverture", "apercu", "categorie"):
            ligne[k] = str(ligne[k] or "")[:600]
        if ligne["categorie"] not in _PAR_CLE:
            ligne["categorie"] = "divers"
        ligne["texte_len"] = int(a.get("texte_len") or 0)
        cur = db.execute(
            f"INSERT OR IGNORE INTO encheres ({','.join(COLONNES)}, vu_le) "
            f"VALUES ({','.join('?' * len(COLONNES))}, ?)",
            [ligne[k] for k in COLONNES] + [maintenant])
        if cur.rowcount:
            nouveaux.append(ligne)
    if presents:
        ids = sorted({int(i) for i in presents if str(i).isdigit() or isinstance(i, int)})
        if ids:
            marque = ",".join("?" * len(ids))
            db.execute(f"UPDATE encheres SET retire=1 WHERE doc_id NOT IN ({marque})", ids)
            db.execute(f"UPDATE encheres SET retire=0 WHERE doc_id IN ({marque})", ids)
    db.commit()
    return nouveaux


def pour_affichage(r, lang: str = "fr", aujourdhui: date = None) -> dict:
    """Une ligne de la table prête pour les gabarits."""
    aujourdhui = aujourdhui or date.today()
    d = dict(r)
    for k in ("cautions", "pieces", "lots"):
        try:
            d[k] = json.loads(d.get(k) or "[]")
        except ValueError:
            d[k] = []
    d["cat"] = categorie(d.get("categorie") or "divers", lang)
    d["nature"] = nature(d.get("kind"), lang)
    d["lieu"] = lieu(d.get("region", ""), d.get("title", ""))
    d["pieces_txt"] = [piece(p, lang) for p in d["pieces"]]
    try:
        d["jours"] = (date.fromisoformat(d["date_iso"]) - aujourdhui).days if d.get("date_iso") else None
    except ValueError:
        d["jours"] = None
    d["date_txt"] = _jjmmaaaa(d.get("date_iso", ""))
    d["ouverture_txt"] = _jjmmaaaa(d.get("ouverture", ""))
    d["visite_txt"] = _jjmmaaaa(d.get("visite", ""))
    d["total_lots"] = sum(int(l.get("qte") or 0) for l in d["lots"])
    return d


def _jjmmaaaa(iso: str) -> str:
    try:
        return date.fromisoformat(iso).strftime("%d/%m/%Y") if iso else ""
    except ValueError:
        return ""


def lieu(region: str, titre: str) -> str:
    m = re.search(r"Bureau d[e'’]\s*([A-ZÀ-Ý][\w\- ]+?)(?:\s+d[eu]|\s+de lots|\s*$|,|\s+divers|\s+un|\s+des)", titre)
    if m:
        return m.group(1).strip()
    return re.sub(r"^Direction (Régionale|des Douanes)( du| de| de la| d')?\s*", "", region).strip()


def a_venir_sql() -> str:
    """Condition SQL: avis encore en ligne et dont la date n'est pas passée."""
    return "retire=0 AND (date_iso='' OR date_iso>=?)"


def message_whatsapp(d: dict, lang: str = "ar") -> str:
    """Publication prête à coller (canal WhatsApp), comme le faisait l'outil local."""
    ar = lang == "ar"
    lignes = [f"{d['cat']['emoji']} *{d['cat']['nom']}* — {d['lieu']}", d["nature"], f"📝 {d['title']}"]
    if d["kind"] == "aop":
        etiquette = "⏰ آخر أجل لإيداع العروض" if ar else "⏰ Date limite de dépôt"
    else:
        etiquette = "📅 تاريخ المزاد" if ar else "📅 Date de l'enchère"
    quand = d["date_txt"] or ("غير محدد" if ar else "non précisée")
    if d.get("heure"):
        quand += (" على " if ar else " à ") + d["heure"]
    if d.get("jours") is not None and d["jours"] >= 0:
        if d["jours"] == 0:
            quand += " (اليوم)" if ar else " (aujourd'hui)"
        else:
            quand += f" (بعد {d['jours']} يوم)" if ar else f" (dans {d['jours']} j)"
    lignes.append(f"{etiquette}: {quand}")
    if d["kind"] == "aop" and d.get("ouverture_txt"):
        lignes.append(("📂 فتح الأظرفة: " if ar else "📂 Ouverture des plis : ") + d["ouverture_txt"])
    if d.get("visite_txt"):
        lignes.append(("👀 المعاينة ابتداءً من: " if ar else "👀 Visite à partir du : ") + d["visite_txt"])
    if d["cautions"]:
        unite = " درهم" if ar else " DH"
        lignes.append(("💰 الضمان: " if ar else "💰 Caution : ") + " / ".join(c + unite for c in d["cautions"]))
    if d["lots"]:
        top = sorted(d["lots"], key=lambda l: -int(l.get("qte") or 0))[:5]
        lignes.append(f"🔎 أبرز الحصص ({d['total_lots']} قطعة في المجموع):" if ar
                      else f"🔎 Principaux lots ({d['total_lots']} pièces au total) :")
        for l in top:
            etat = ("جديد" if l.get("etat") == "neuf" else "مستعمل") if ar else ("neuf" if l.get("etat") == "neuf" else "usagé")
            lignes.append(f"   • {l['nom']} × {l['qte']} ({etat})")
    elif d.get("apercu"):
        lignes.append(("🔎 من لائحة الحصص: " if ar else "🔎 Extrait des lots : ") + d["apercu"] + "…")
    if d["pieces_txt"]:
        lignes.append(("📋 الوثائق المطلوبة: " if ar else "📋 Pièces demandées : ") + "، ".join(d["pieces_txt"]))
    lignes.append(("📄 الإعلان الرسمي: " if ar else "📄 Avis officiel : ") + d["url"])
    return "\n".join(lignes)
