# -*- coding: utf-8 -*-
"""Rapprochement avec les annuaires professionnels marocains.

Global Marché publie qui a gagné un marché, jamais comment le joindre. Au
03/10/2026, 1120 attributaires sur 1133 n'avaient aucun contact: une liste
de noms qu'on ne peut pas appeler.

Deux annuaires publics comblent une partie du trou. Mesures du 04/10/2026,
faites sur nos propres noms, pas sur la promesse des sites:

    Télécontact   266 946 fiches. Sur un index de 55 % de sa base, 48 de nos
                  289 entreprises sans contact reconnues (16,6 %), et 8 des
                  12 fiches ouvertes portaient un téléphone (66 %).
    Charika     ~1 500 000 fiches. Sur un index de 7 % de sa base, 24 des 289
                  reconnues (8,3 %). Moins de téléphones, mais des emails et
                  le **nom du dirigeant** — ce qui change la première phrase
                  d'un appel.

Ce que ce module s'interdit:

- **Le rapprochement est exact.** Même règle que pour Kerix: on reconnaît le
  nom canonique à l'identique ou on ne pose rien. Un à-peu-près ferait
  composer au fondateur le numéro d'une autre société.
- **On n'écrase jamais un contact existant.** Un numéro saisi à la main pendant
  un appel vaut mieux que tout annuaire; on ne remplit que le vide.
- **On ne lit que ce que le site offre.** Les sitemaps sont déclarés dans les
  robots.txt. Télécontact interdit `/trouver/` (sa recherche) et laisse
  `/annonceur/` — ce sont les fiches, et elles sont dans son sitemap. Charika
  n'interdit rien. Aucune des deux ne demande de compte pour ces pages.

Note de méthode: on n'indexe pas les annuaires, on indexe **nos** entreprises
— quelques milliers de clés — et on fait couler les sitemaps devant. Mettre
les deux millions de fiches de Charika en mémoire tiendrait mal dans un
conteneur, et n'apprendrait rien de plus.
"""
import logging
import re
import time
import urllib.request
from datetime import datetime

from app.core.database import get_db
from app.services.companies import normalize_company_name, normalize_phone

logger = logging.getLogger("atlas.annuaires")

# Un identifiant courtois: le site doit pouvoir nous reconnaître, et nous
# écrire si notre passage le dérange.
_AGENT = ("Mozilla/5.0 (compatible; MarocEntrepreneuriat/1.0; "
          "+https://marocentrepreneuriat.com)")

_DELAI = 1.2          # secondes entre deux fiches ouvertes
_PLAFOND_FICHES = 400  # par exécution, pour ne pas peser sur le site


# ─── Les deux annuaires ──────────────────────────────────────────────────

class Annuaire:
    """Un annuaire: où trouver ses adresses, comment en tirer un nom."""

    def __init__(self, cle, libelle, index, motif, lire_fiche, note):
        self.cle = cle
        self.libelle = libelle
        self.index = index            # sitemap d'index
        self.motif = motif            # extrait le slug d'une adresse de fiche
        self.lire_fiche = lire_fiche  # extracteur de contacts
        self.note = note


def _lire(url: str, timeout: int = 90) -> str:
    requete = urllib.request.Request(url, headers={"User-Agent": _AGENT})
    with urllib.request.urlopen(requete, timeout=timeout) as reponse:
        return reponse.read().decode("utf-8", "replace")


def _texte(brut: str) -> str:
    """Débarrasse un fragment HTML de ses balises et de ses blancs."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", brut or "")).strip()


# ─── Télécontact (Pages Jaunes Maroc) ────────────────────────────────────

_TC_TEL = re.compile(r'href="tel:([^"]{8,24})"')
_TC_TITRE = re.compile(r"<title>([^<|]+)")

# On ne lit ni l'adresse ni la ville de ces pages. Elles portent un bloc
# d'autres annonceurs, avec leurs propres `itemprop="streetAddress"` et
# `addressLocality`: la fiche de Tabarak Travaux, à Aït Ourir, rendait
# « 611 bd Aba Chouaïb Doukali - Casablanca ». Le téléphone, lui, est sûr:
# un seul `href="tel:"` par page, celui de l'entreprise.


def _fiche_telecontact(html: str) -> dict:
    """Les fiches portent des microdonnées schema.org: on s'y tient.

    Une expression qui chasserait « 0[567]… » dans toute la page ramènerait
    des fragments de tracés SVG — « 062.078.098.115 » en était un.
    """
    tels = []
    for brut in _TC_TEL.findall(html):
        num = normalize_phone(brut)
        if num and num not in tels:
            tels.append(num)
    titre = _TC_TITRE.search(html)
    activite = ""
    if titre:
        # « Tabarak Travaux - Electricité générale à Aït Ourir »
        m = re.search(r"-\s*([^-]+?)\s+à\s+", titre.group(1))
        activite = m.group(1).strip() if m else ""
    return {
        "phone": tels[0] if tels else "",
        "mobile": tels[1] if len(tels) > 1 else "",
        "email": "",
        "address": "",
        "city": "",
        "activite": activite,
        "manager": "",
    }


# ─── Charika ─────────────────────────────────────────────────────────────

_CK_TEL = re.compile(r'class="marketingInfoTelFax"[^>]*>\s*([0-9 .\-]{9,20})')
_CK_MAIL = re.compile(r'href="mailto:([^"@]+@[^"]+)"')
_CK_SITE = re.compile(r'href="(https?://(?!www\.charika)[^"]{6,120})"[^>]*>\s*www\.')
_CK_CHEF = re.compile(r'<b class="text-color">\s*(M\.|Mme|Mlle)\s*([^<:]{3,60}?)\s*:\s*</b>'
                      r'\s*</span>\s*<span>\s*([^<]{3,60})')

# Le formulaire de contact de Charika porte un gabarit vide. Pris pour un
# email d'entreprise, il aurait rempli quatorze fiches sur quatorze.
_MAILS_DU_SITE = ("charika.ma", "inforisk", "exemple.com", "example.com")


def _fiche_charika(html: str) -> dict:
    tels = []
    for brut in _CK_TEL.findall(html):
        num = normalize_phone(brut)
        if num and num not in tels:
            tels.append(num)
    mails = [m.strip().lower() for m in _CK_MAIL.findall(html)]
    mails = [m for m in mails if not any(d in m for d in _MAILS_DU_SITE)]
    site = _CK_SITE.search(html)
    chef = _CK_CHEF.search(html)
    return {
        "phone": tels[0] if tels else "",
        "mobile": tels[1] if len(tels) > 1 else "",
        "email": mails[0] if mails else "",
        "address": "",
        "city": "",
        "activite": "",
        "manager": (f"{chef.group(1)} {_texte(chef.group(2))} — {_texte(chef.group(3))}"
                    if chef else ""),
    }


ANNUAIRES = {
    "telecontact": Annuaire(
        cle="telecontact",
        libelle="Télécontact — Pages Jaunes Maroc",
        index="https://www.telecontact.ma/sitemap_index.xml",
        motif=re.compile(r"/annonceur/([^/]+)/\d+/[^/]+\.php$"),
        lire_fiche=_fiche_telecontact,
        note="Le meilleur pour les téléphones. Pas d'email.",
    ),
    "charika": Annuaire(
        cle="charika",
        libelle="Charika",
        index="https://www.charika.ma/sitemap.xml",
        motif=re.compile(r"/societe-(.+?)$"),
        lire_fiche=_fiche_charika,
        note="Emails et nom du dirigeant. Moins de téléphones.",
    ),
}


# ─── Index et rapprochement ──────────────────────────────────────────────

def _sous_sitemaps(annuaire: Annuaire, log_fn) -> list:
    """Les sitemaps de fiches, lus dans l'index plutôt qu'écrits en dur.

    Les deux sites en ajoutent au fil de leur croissance; une liste figée
    cesserait silencieusement de voir les nouvelles entreprises.
    """
    try:
        index = _lire(annuaire.index, timeout=60)
    except Exception as e:
        log_fn(f"⚠ index de {annuaire.libelle}: {str(e)[:90]}")
        return []
    urls = re.findall(r"<loc>\s*([^<]+?)\s*</loc>", index)
    if annuaire.cle == "telecontact":
        urls = [u for u in urls if "annonceur" in u]
    else:
        urls = [u for u in urls if re.search(r"sitemap-\d+\.xml$", u)]
    log_fn(f"{annuaire.libelle}: {len(urls)} sitemap(s) de fiches.")
    return urls


def _cle_du_slug(annuaire: Annuaire, url: str) -> str:
    m = annuaire.motif.search(url)
    if not m:
        return ""
    slug = m.group(1)
    if annuaire.cle == "charika":
        # « societe-france-agencement--150436 » → l'identifiant n'est pas le nom.
        slug = re.sub(r"-{1,2}\d+$", "", slug)
    return normalize_company_name(slug.replace("-", " "))


def _nos_entreprises(db, tous: bool) -> dict:
    """{clé canonique: id}. Par défaut, celles qu'on ne peut pas joindre."""
    filtre = ("" if tous else
              "WHERE (phone IS NULL OR phone='') AND (email IS NULL OR email='')")
    par_cle = {}
    for ligne in db.execute(
            f"SELECT id, normalized_name FROM companies {filtre}").fetchall():
        cle = ligne["normalized_name"] or ""
        if cle:
            par_cle.setdefault(cle, ligne["id"])
    return par_cle


def apparier(source: str, log_fn=print, tous: bool = False) -> dict:
    """Reconnaît nos entreprises dans les sitemaps et note l'adresse de leur fiche."""
    annuaire = ANNUAIRES[source]
    db = get_db()
    try:
        nos = _nos_entreprises(db, tous)
        log_fn(f"{len(nos)} entreprise(s) à retrouver.")
        if not nos:
            return {"lus": 0, "apparies": 0}

        # Un ensemble, pas un compteur: Charika publie plusieurs adresses pour
        # la même société, et les additionner annonçait 390 reconnaissances
        # pour 289 entreprises cherchées — un chiffre que personne ne peut croire.
        vus, reconnues = 0, set()
        for sm in _sous_sitemaps(annuaire, log_fn):
            try:
                contenu = _lire(sm)
            except Exception as e:
                log_fn(f"⚠ {sm.rsplit('/', 1)[-1]}: {str(e)[:70]}")
                continue
            for url in re.findall(r"<loc>\s*([^<]+?)\s*</loc>", contenu):
                vus += 1
                cle = _cle_du_slug(annuaire, url)
                cid = nos.get(cle)
                if not cid:
                    continue
                if cid in reconnues:
                    continue   # première adresse trouvée, on s'y tient
                db.execute(
                    """INSERT INTO annuaire_fiches(company_id,source,url,trouve_le)
                       VALUES(?,?,?,?)
                       ON CONFLICT(company_id,source) DO UPDATE SET url=excluded.url""",
                    (cid, source, url, datetime.now().isoformat(timespec="seconds")))
                reconnues.add(cid)
            db.commit()
            log_fn(f"  {sm.rsplit('/', 1)[-1]}: {len(reconnues)} reconnue(s) "
                   f"sur {vus} adresses lues.")
        log_fn(f"═══ {len(reconnues)} entreprise(s) retrouvée(s) chez {annuaire.libelle} "
               f"sur {len(nos)} cherchée(s) ═══")
        return {"lus": vus, "apparies": len(reconnues)}
    finally:
        db.close()


# ─── Lecture des fiches ──────────────────────────────────────────────────

def enrichir(source: str, log_fn=print, limite: int = _PLAFOND_FICHES) -> dict:
    """Ouvre les fiches rattachées et en tire ce qui manque.

    On ne remplit que les cases vides: un numéro noté pendant un appel vaut
    mieux que celui d'un annuaire, et rien ne dit que l'annuaire est à jour.
    """
    annuaire = ANNUAIRES[source]
    db = get_db()
    stats = {"ouvertes": 0, "telephones": 0, "emails": 0, "dirigeants": 0, "erreurs": 0}
    try:
        cibles = db.execute(
            """SELECT f.id, f.url, c.id AS cid, c.legal_name, c.phone, c.email,
                      c.address, c.website
                 FROM annuaire_fiches f JOIN companies c ON c.id = f.company_id
                WHERE f.source = ? AND (f.lue_le IS NULL OR f.lue_le = '')
                ORDER BY c.wins DESC, c.id
                LIMIT ?""", (source, limite)).fetchall()
        log_fn(f"{len(cibles)} fiche(s) à ouvrir chez {annuaire.libelle}.")

        for cible in cibles:
            try:
                html = _lire(cible["url"], timeout=30)
            except Exception as e:
                stats["erreurs"] += 1
                log_fn(f"  ⚠ {cible['legal_name'][:36]}: {str(e)[:50]}")
                db.execute("UPDATE annuaire_fiches SET lue_le=?, erreur=? WHERE id=?",
                           (datetime.now().isoformat(timespec="seconds"),
                            str(e)[:120], cible["id"]))
                db.commit()
                time.sleep(_DELAI)
                continue

            f = annuaire.lire_fiche(html)
            stats["ouvertes"] += 1

            db.execute(
                """UPDATE annuaire_fiches SET lue_le=?, phone=?, email=?, address=?,
                          activite=?, manager=?, erreur='' WHERE id=?""",
                (datetime.now().isoformat(timespec="seconds"), f["phone"], f["email"],
                 f["address"], f["activite"], f["manager"], cible["id"]))

            # On ne comble que le vide.
            champs, valeurs = [], []
            if f["phone"] and not (cible["phone"] or "").strip():
                champs.append("phone=?"); valeurs.append(f["phone"]); stats["telephones"] += 1
            if f["email"] and not (cible["email"] or "").strip():
                champs.append("email=?"); valeurs.append(f["email"]); stats["emails"] += 1
            if f["address"] and not (cible["address"] or "").strip():
                champs.append("address=?"); valeurs.append(f["address"])
            if f["manager"]:
                stats["dirigeants"] += 1
            if champs:
                champs.append("last_verified_at=?")
                valeurs.append(datetime.now().isoformat(timespec="seconds"))
                valeurs.append(cible["cid"])
                db.execute(f"UPDATE companies SET {', '.join(champs)} WHERE id=?", valeurs)

            db.commit()
            marque = []
            if f["phone"]:
                marque.append(f["phone"])
            if f["email"]:
                marque.append(f["email"])
            log_fn(f"  {'✓' if marque else '·'} {cible['legal_name'][:38]:40s} "
                   f"{' · '.join(marque) if marque else 'rien à prendre'}")
            time.sleep(_DELAI)

        log_fn(f"═══ {stats['telephones']} téléphone(s), {stats['emails']} email(s) "
               f"ajoutés sur {stats['ouvertes']} fiche(s) lue(s) ═══")
        return stats
    finally:
        db.close()


# ─── État, pour la page d'administration ─────────────────────────────────

def etat() -> dict:
    """De quoi classer la prospection: couverture par annuaire, et ce qui reste."""
    db = get_db()
    try:
        def un(sql, *a):
            r = db.execute(sql, a).fetchone()
            return r[0] if r else 0

        total = un("SELECT COUNT(*) FROM companies")
        gagnants = un("SELECT COUNT(*) FROM companies WHERE COALESCE(wins,0) > 0")
        joignables = un("SELECT COUNT(*) FROM companies WHERE "
                        "(phone IS NOT NULL AND phone != '') OR (email IS NOT NULL AND email != '')")
        sources = []
        for cle, a in ANNUAIRES.items():
            sources.append({
                "cle": cle,
                "libelle": a.libelle,
                "note": a.note,
                "rattachees": un("SELECT COUNT(*) FROM annuaire_fiches WHERE source=?", cle),
                "lues": un("SELECT COUNT(*) FROM annuaire_fiches WHERE source=? "
                           "AND lue_le IS NOT NULL AND lue_le != ''", cle),
                "telephones": un("SELECT COUNT(*) FROM annuaire_fiches WHERE source=? "
                                 "AND phone IS NOT NULL AND phone != ''", cle),
                "emails": un("SELECT COUNT(*) FROM annuaire_fiches WHERE source=? "
                             "AND email IS NOT NULL AND email != ''", cle),
                "dirigeants": un("SELECT COUNT(*) FROM annuaire_fiches WHERE source=? "
                                 "AND manager IS NOT NULL AND manager != ''", cle),
                "en_attente": un("SELECT COUNT(*) FROM annuaire_fiches WHERE source=? "
                                 "AND (lue_le IS NULL OR lue_le='')", cle),
            })
        # Kerix reste un lien seul: son site refuse les clients automatiques.
        kerix = un("SELECT COUNT(*) FROM companies WHERE annuaire_url IS NOT NULL "
                   "AND annuaire_url != ''")
        return {
            "total": total, "gagnants": gagnants, "joignables": joignables,
            "injoignables": total - joignables, "sources": sources, "kerix": kerix,
        }
    finally:
        db.close()


def dernieres_trouvailles(limite: int = 40) -> list:
    """Ce que les annuaires viennent de rendre, pour le vérifier à l'œil."""
    db = get_db()
    try:
        return [dict(r) for r in db.execute(
            """SELECT c.id, c.legal_name, c.city, c.sector, c.wins,
                      f.source, f.url, f.phone, f.email, f.manager, f.activite, f.lue_le
                 FROM annuaire_fiches f JOIN companies c ON c.id = f.company_id
                WHERE f.lue_le IS NOT NULL AND f.lue_le != ''
                  AND ((f.phone IS NOT NULL AND f.phone != '')
                    OR (f.email IS NOT NULL AND f.email != ''))
                ORDER BY f.lue_le DESC LIMIT ?""", (limite,)).fetchall()]
    finally:
        db.close()
