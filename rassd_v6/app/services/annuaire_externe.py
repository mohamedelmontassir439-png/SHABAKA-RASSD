# -*- coding: utf-8 -*-
"""Rapprochement avec un annuaire professionnel externe (Kerix).

Global Marché ne publie aucun contact d'attributaire. Un annuaire marocain
d'entreprises peut avoir le téléphone de certaines d'entre elles. Reste à
savoir lesquelles, et à poser le lien au bon endroit.

Ce module ne lit **que** les fichiers sitemap que le site publie à
l'intention des robots — ils sont déclarés dans son robots.txt, c'est-à-dire
offerts explicitement à la collecte automatique. Il n'ouvre aucune fiche:
les pages du site répondent 403 aux clients non-navigateurs, et c'est une
protection, pas un obstacle à contourner. On en retire donc la seule chose
que le sitemap contient — l'adresse de la fiche — et le fondateur l'ouvre
lui-même, dans son navigateur, comme n'importe quel visiteur.

À noter aussi: le robots.txt du site interdit `/KerixEmail.asp?pid=*`, le
point de révélation des emails. Rien ici n'y touche.

Mesure du 02/10/2026: 20 265 fiches d'entreprise au sitemap — sur 34 427
adresses, le reste étant des pages de catégorie — dont **39 des 237 gagnants
de marchés** reconnues par nom canonique, soit 16,5 %.
"""
import logging
import re
import urllib.request

from app.core.database import get_db
from app.services.companies import normalize_company_name

logger = logging.getLogger("atlas.annuaire_externe")

SITEMAPS = (
    "https://www.kerix.net/site_map_kerix_01.txt",
    "https://www.kerix.net/site_map_kerix_02.txt",
)

# On préfère la version française de la fiche quand les deux existent.
# Les pages de catégorie se terminent par « .html » — « batiment.html »,
# « abrasives.html » — et ne sont pas des entreprises. Les accepter revenait
# à pouvoir rattacher, à une société nommée BATIMENT, la page de la
# catégorie bâtiment: un lien qui a l'air juste et qui ne mène à personne.
_FICHE = re.compile(r"^https?://[^/]+/(fr|en)/annuaire-entreprise/([^/\s.]+)$")

# Un identifiant courtois: le site doit pouvoir nous reconnaître et nous
# écrire si notre passage le dérange.
_AGENT = "MarocEntrepreneuriat/1.0 (+https://marocentrepreneuriat.com)"


def _lire_sitemap(url: str, log_fn) -> list:
    requete = urllib.request.Request(url, headers={"User-Agent": _AGENT})
    with urllib.request.urlopen(requete, timeout=90) as reponse:
        if reponse.status != 200:
            log_fn(f"\u26a0 {url}: HTTP {reponse.status}")
            return []
        contenu = reponse.read().decode("utf-8", "replace")
    return contenu.splitlines()


def index_annuaire(log_fn=print) -> dict:
    """{clé canonique: URL de la fiche} pour tout l'annuaire externe."""
    par_cle = {}
    for url in SITEMAPS:
        try:
            lignes = _lire_sitemap(url, log_fn)
        except Exception as e:
            log_fn(f"\u26a0 {url}: {str(e)[:90]}")
            continue
        for ligne in lignes:
            m = _FICHE.match(ligne.strip())
            if not m:
                continue
            langue, slug = m.group(1), m.group(2)
            cle = normalize_company_name(slug.replace("-", " "))
            if not cle:
                continue
            # La fiche française passe devant l'anglaise.
            if cle not in par_cle or langue == "fr":
                par_cle[cle] = ligne.strip()
    log_fn(f"{len(par_cle)} entreprise(s) au sitemap de l'annuaire externe.")
    return par_cle


def apparier(log_fn=print, tous: bool = False) -> dict:
    """Pose le lien de la fiche externe sur les entreprises reconnues.

    Par défaut on ne traite que les gagnants de marchés: ce sont eux qui
    arrivent sans contact. `tous=True` étend à l'annuaire entier.

    Le rapprochement se fait sur le nom canonique **exact**. Un lien
    approximatif enverrait le fondateur vers une autre société et lui ferait
    composer un numéro qui n'est pas le bon: on préfère ne rien poser.
    """
    par_cle = index_annuaire(log_fn)
    if not par_cle:
        return {"candidats": 0, "apparies": 0}

    db = get_db()
    stats = {"candidats": 0, "apparies": 0}
    try:
        filtre = "" if tous else "WHERE COALESCE(wins,0) > 0"
        lignes = db.execute(
            f"SELECT id, normalized_name, annuaire_url FROM companies {filtre}").fetchall()
        for ligne in lignes:
            stats["candidats"] += 1
            url = par_cle.get(ligne["normalized_name"] or "")
            if not url or url == (ligne["annuaire_url"] or ""):
                continue
            db.execute("UPDATE companies SET annuaire_url=? WHERE id=?", (url, ligne["id"]))
            stats["apparies"] += 1
        db.commit()
    finally:
        db.close()
    log_fn(f"\u2550\u2550\u2550 {stats['apparies']} fiche(s) externe(s) rattach\u00e9e(s) "
           f"sur {stats['candidats']} \u2550\u2550\u2550")
    return stats
