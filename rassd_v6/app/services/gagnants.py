# -*- coding: utf-8 -*-
"""Les gagnants de marchés, transformés en liste d'appel.

Une entreprise qui vient de remporter un marché public est le meilleur
prospect que la plateforme puisse produire: elle a de l'argent, elle a du
travail devant elle, et elle a un besoin immédiat de veille pour le marché
suivant. Elle est aussi la plus difficile à joindre, car **Global Marché ne
publie aucun contact**: les pages de résultats donnent la référence, l'objet,
l'acheteur, le nom de l'attributaire, le montant et les dates — rien d'autre.
Les téléphones doivent donc venir d'ailleurs, et c'est tout l'objet de la
deuxième moitié de ce module.

Trois opérations, dans cet ordre:

1. `noms_gagnants` lit le champ « adjudicataire » tel que la source l'écrit,
   y compris quand il contient plusieurs sociétés et des lots déclarés
   infructueux, et rend la liste des entreprises réellement attributaires.
2. `inscrire` les verse dans l'annuaire, en comptant les marchés gagnés.
3. `enrichir` cherche le contact de chacune, nom par nom.
"""
import logging
import re

from app.core.database import get_db
from app.services.companies import (_PROCEDURE_RE, normalize_company_name,
                                    strip_accents, upsert_company)

logger = logging.getLogger("atlas.gagnants")

# « LOT 1 », « lot n° 2 », « Lot N 3 »: la frontière entre deux attributaires.
_MARQUEUR_LOT = re.compile(r"\blots?\s*(?:n\s*[\u00b0o]?\s*)?\d+", re.IGNORECASE)

# Un point-virgule sépare aussi deux sociétés: « TRAKTERM SARL; MICRO FAST ».
_SEPARATEUR = re.compile(r"[;]")

# « LOT 1 & 2 & 3: M2M SERVICES »: le marqueur retiré, il reste « 2 & 3: »
# collé devant le nom. La clé canonique n'en souffre pas, elle écarte les
# nombres; le nom lisible, si — le fondateur lirait « 2 :STE BAICHOU TRAV
# SARL » dans sa liste d'appels. On ne retire donc qu'un nombre **isolé** ou
# un connecteur, jamais un chiffre collé au nom: « 2SBT » et « 2LL HMI SARL »
# sont de vraies raisons sociales.
_DEBRIS = re.compile(r"^(?:\d+|&|et)(?=[\s&:.,;–-]|$)[\s&:.,;–-]*", re.IGNORECASE)

# Ponctuation de découpage, aux deux extrémités d'un segment.
_BORDS = " \t:.,&()[]«»\"'-•"


def _nettoyer(segment: str) -> str:
    """Retire la ponctuation de découpage et les restes de numéros de lot."""
    propre = segment.strip(_BORDS)
    while propre:
        reduit = _DEBRIS.sub("", propre, count=1)
        if reduit == propre:
            break
        propre = reduit
    return propre.strip(_BORDS)


def noms_gagnants(brut: str) -> list:
    """Les entreprises attributaires d'une ligne de résultat.

    La source empile parfois plusieurs lots dans une seule case:

        « ENTREPRISE OKACHA ABDERRAHIM SARL AU (lot 1) STE BAICHOU TRAV SARL »
        « NS DENTAL (lot 1) infructueux (lot 2) »
        « lot 1: expert pin lot 2; damana kit »

    La normalisation de l'annuaire rejette tout nom contenant un marqueur de
    procédure — à juste titre, car « Annulé » n'est pas une entreprise. Mais
    « lot » est l'un de ces marqueurs, si bien que les trois lignes ci-dessus
    rendaient une clé vide: vingt-et-un libellés distincts, dont **douze
    contenant de vraies sociétés**, sortaient de l'annuaire sans laisser de
    trace. Mesure du 01/10/2026.

    On découpe donc sur les marqueurs de lot avant de normaliser, on jette les
    segments qui ne décrivent qu'un état de procédure, et on garde les autres.
    Les noms déjà propres ne passent pas par ce découpage: aucun risque de
    régression sur les deux cents libellés qui fonctionnaient.
    """
    texte = (brut or "").strip()
    if not texte:
        return []
    # Chemin court: un nom que l'annuaire accepte déjà tel quel.
    direct = normalize_company_name(texte)
    if direct:
        return [texte]
    # Sinon, le libellé est soit un état de procédure, soit un empilement de
    # lots. On le découpe sur les marqueurs et on examine chaque morceau.
    segments = []
    for morceau in _MARQUEUR_LOT.split(texte):
        segments.extend(_SEPARATEUR.split(morceau))
    noms, vus = [], set()
    for segment in segments:
        segment = _nettoyer(segment)
        if not segment:
            continue
        # « infructueux », « annulé », « voir PV »: un lot sans attributaire.
        if _PROCEDURE_RE.search(strip_accents(segment).lower()):
            continue
        cle = normalize_company_name(segment)
        if cle and cle not in vus:
            vus.add(cle)
            noms.append(segment)
    return noms


def inscrire(log_fn=print) -> dict:
    """Verse tous les attributaires dans l'annuaire et compte leurs marchés.

    Deux réparations au passage, sur des colonnes calculées à la collecte et
    jamais recalculées depuis:

    `adjudicataire_norm` est la clé qui relie un attributaire à son
    téléphone. Vide, la place de marché de sous-traitance ne peut rien
    afficher pour cette ligne. Elle l'était pour cent douze lignes.

    `montant_num` sert à trier par montant. Une ligne portait 4 186 896 012
    dirhams pour un marché de 418 689,60 — l'ancien analyseur collait les
    chiffres des lots bout à bout — et ressortait donc en tête de tout
    classement par montant.
    """
    from app.services.soustraitance import parse_montant

    db = get_db()
    stats = {"lignes": 0, "gagnants": 0, "creees": 0, "fusionnees": 0,
             "cles_reparees": 0, "montants_repares": 0, "noms_nettoyes": 0}
    try:
        lignes = [dict(r) for r in db.execute(
            """SELECT id, adjudicataire, adjudicataire_norm, secteur, region,
                      montant, montant_num
               FROM tender_results WHERE adjudicataire != ''""").fetchall()]
        victoires = {}
        for ligne in lignes:
            stats["lignes"] += 1
            noms = noms_gagnants(ligne["adjudicataire"])

            # La clé de rapprochement: le premier attributaire de la ligne.
            cle = normalize_company_name(noms[0]) if noms else ""
            if cle and cle != (ligne["adjudicataire_norm"] or ""):
                db.execute("UPDATE tender_results SET adjudicataire_norm=? WHERE id=?",
                           (cle, ligne["id"]))
                stats["cles_reparees"] += 1

            correct = parse_montant(ligne["montant"])
            if abs(correct - float(ligne["montant_num"] or 0)) > 1:
                db.execute("UPDATE tender_results SET montant_num=? WHERE id=?",
                           (correct, ligne["id"]))
                stats["montants_repares"] += 1

            for nom in noms:
                cid, action = upsert_company(db, {
                    "legal_name": nom,
                    "sector": ligne["secteur"] or "",
                    "region": ligne["region"] or "",
                    "source": "tender_results",
                    "source_type": "gagnant",
                })
                if not cid:
                    continue
                stats["gagnants"] += 1
                stats["creees"] += 1 if action == "created" else 0
                stats["fusionnees"] += 1 if action.startswith("merged") else 0
                victoires[cid] = victoires.get(cid, 0) + 1

        # `wins` dit combien de marchés l'entreprise a remportés: c'est le
        # seul critère de priorité d'appel qui vienne des faits.
        for cid, n in victoires.items():
            db.execute("UPDATE companies SET wins=? WHERE id=?", (n, cid))

        # Les noms déjà écrits avant l'ajout du nettoyage gardaient leurs
        # restes de numéros de lot: on les reprend ici, la clé canonique
        # étant inchangée, aucune fiche ne se dédouble.
        for cid, nom in db.execute(
                "SELECT id, legal_name FROM companies WHERE COALESCE(wins,0) > 0").fetchall():
            propre = _nettoyer(nom or "")
            if propre and propre != nom:
                db.execute("UPDATE companies SET legal_name=? WHERE id=?", (propre, cid))
                stats["noms_nettoyes"] = stats.get("noms_nettoyes", 0) + 1
        db.commit()
    finally:
        db.close()
    log_fn(f"═══ {stats['gagnants']} attributaire(s) · "
           f"{stats['creees']} créée(s) · {stats['fusionnees']} fusionnée(s) · "
           f"{stats['cles_reparees']} clé(s) réparée(s) · "
           f"{stats['montants_repares']} montant(s) réparé(s) ═══")
    return stats


def a_joindre(limite: int = 0) -> list:
    """Les entreprises gagnantes dont on n'a encore ni téléphone ni email.

    Triées par nombre de marchés remportés: une entreprise qui en a gagné
    quatre vaut quatre fois l'effort de recherche d'une qui en a gagné un.
    """
    db = get_db()
    try:
        sql = """SELECT id, legal_name, normalized_name, city, region, wins
                 FROM companies
                 WHERE COALESCE(wins,0) > 0 AND phone='' AND email=''
                 ORDER BY wins DESC, legal_name"""
        if limite:
            sql += f" LIMIT {int(limite)}"
        return [dict(r) for r in db.execute(sql).fetchall()]
    finally:
        db.close()


def enrichir(limite: int = 0, log_fn=print) -> dict:
    """Cherche le contact de chaque gagnant par son nom, via l'API Places.

    Global Marché ne publie pas les contacts: il faut les chercher ailleurs.
    L'annuaire déjà constitué l'a été par secteur et par ville — « entreprise
    de travaux publics Casablanca » — ce qui ramène des sociétés du bon métier
    mais presque jamais celles qui ont gagné. D'où le résultat mesuré le
    01/10/2026: sur 193 gagnants présents dans l'annuaire, **un seul avait un
    téléphone**. La recherche doit donc porter sur le nom.

    On passe par l'API Places de Google, qui est le canal prévu pour cet
    usage et qui autorise la conservation du téléphone. Le module
    `maps_scraper` du projet fait la même chose en pilotant un navigateur
    masqué: ce n'est pas la voie retenue ici.

    La vérification du nom est le cœur de cette fonction, pas un détail.
    Chercher « STE BAICHOU TRAV » ramène toujours quelque chose, et ce
    quelque chose n'est pas forcément la bonne société. Une fiche n'est donc
    retenue que si son nom canonique est exactement celui du gagnant.
    Attacher un numéro approximatif serait pire que n'en avoir aucun: le
    fondateur appellerait un inconnu en lui parlant d'un marché qu'il n'a
    jamais remporté.
    """
    import time

    from app.core.config import cfg
    from app.services.email_finder import find_email
    from app.services.places_scraper import place_vers_entreprise, recherche_texte

    stats = {"cherchees": 0, "trouvees": 0, "ecartees": 0, "telephones": 0,
             "emails": 0, "erreurs": 0}
    if not cfg.GOOGLE_PLACES_API_KEY:
        log_fn("\u274c GOOGLE_PLACES_API_KEY absente: ajoutez une cl\u00e9 Places "
               "(Text Search) dans .env, puis relancez.")
        stats["erreurs"] = 1
        return stats

    cibles = a_joindre(limite)
    if not cibles:
        log_fn("Aucun gagnant sans contact.")
        return stats
    log_fn(f"{len(cibles)} gagnant(s) \u00e0 joindre.")

    db = get_db()
    try:
        for cible in cibles:
            stats["cherchees"] += 1
            lieu = cible.get("city") or cible.get("region") or ""
            try:
                places, _ = recherche_texte(f"{cible['legal_name']} {lieu} Maroc".strip())
            except RuntimeError as e:
                # Clé refusée ou quota dépassé: inutile d'enchaîner 200 appels
                # qui échoueront tous, et qui sont facturés.
                log_fn(f"\u26d4 {e}")
                stats["erreurs"] += 1
                break
            except Exception as e:
                log_fn(f"\u26a0 {cible['legal_name'][:40]}: {str(e)[:70]}")
                stats["erreurs"] += 1
                continue

            fiche = {}
            for place in places[:5]:
                candidate = place_vers_entreprise(place, cible.get("sector") or "", "")
                if not candidate:
                    continue
                if normalize_company_name(candidate["legal_name"]) != cible["normalized_name"]:
                    continue
                if not (candidate.get("phone") or candidate.get("website")):
                    continue
                # Le nom retenu reste celui du marché: c'est sous ce nom que
                # l'entreprise figure dans l'avis d'attribution.
                candidate["legal_name"] = cible["legal_name"]
                candidate["source_type"] = "gagnant"
                fiche = candidate
                break

            if not fiche:
                stats["ecartees"] += 1
                time.sleep(cfg.PLACES_DELAY_MS / 1000)
                continue

            if fiche.get("website") and not fiche.get("email"):
                try:
                    fiche["email"] = find_email(fiche["website"]) or ""
                except Exception:
                    pass
            upsert_company(db, fiche)
            db.commit()
            stats["trouvees"] += 1
            stats["telephones"] += 1 if fiche.get("phone") else 0
            stats["emails"] += 1 if fiche.get("email") else 0
            log_fn(f"\u2713 {cible['legal_name'][:44]} \u2014 "
                   f"{fiche.get('phone') or 'sans t\u00e9l\u00e9phone'}"
                   f"{' \u00b7 ' + fiche['email'] if fiche.get('email') else ''}")
            time.sleep(cfg.PLACES_DELAY_MS / 1000)
    finally:
        db.close()
    log_fn(f"\u2550\u2550\u2550 {stats['telephones']} t\u00e9l\u00e9phone(s) \u00b7 "
           f"{stats['emails']} email(s) \u00b7 {stats['ecartees']} non identifi\u00e9(s) "
           f"sur {stats['cherchees']} \u2550\u2550\u2550")
    return stats


def semer_prospection(log_fn=print) -> dict:
    """Inscrit les gagnants joignables dans la file d'appel.

    Sans cette ligne dans `prospection`, une entreprise reste invisible sur
    la page d'appel: celle-ci n'affiche que ce qui y figure ou ce qui s'y
    rattache par défaut. On ne touche jamais une fiche déjà suivie — un
    « Pas intéressé » ou un « Ne plus contacter » ne doit pas redevenir
    « À appeler » parce qu'un nouveau marché a été gagné.
    """
    from datetime import datetime

    db = get_db()
    stats = {"ajoutees": 0, "deja_suivies": 0, "sans_contact": 0}
    try:
        gagnants = [dict(r) for r in db.execute(
            """SELECT c.id, c.legal_name, c.phone, c.email, c.wins,
                      p.company_id AS suivie
               FROM companies c
               LEFT JOIN prospection p ON p.company_id = c.id
               WHERE COALESCE(c.wins,0) > 0
               ORDER BY c.wins DESC""").fetchall()]
        maintenant = datetime.now().isoformat()
        for g in gagnants:
            if g["suivie"]:
                stats["deja_suivies"] += 1
                continue
            if not (g["phone"] or g["email"]):
                stats["sans_contact"] += 1
                continue
            db.execute(
                """INSERT INTO prospection(company_id, statut, canal, notes,
                       dernier_contact, prochain_contact, appels, created_at, updated_at)
                   VALUES(?,'a_appeler','', ?, '', '', 0, ?, ?)""",
                (g["id"], f"Gagnant de {g['wins']} march\u00e9(s) public(s).",
                 maintenant, maintenant))
            stats["ajoutees"] += 1
        db.commit()
    finally:
        db.close()
    log_fn(f"\u2550\u2550\u2550 {stats['ajoutees']} ajout\u00e9e(s) \u00e0 la file d'appel \u00b7 "
           f"{stats['deja_suivies']} d\u00e9j\u00e0 suivie(s) \u00b7 "
           f"{stats['sans_contact']} sans contact \u2550\u2550\u2550")
    return stats
