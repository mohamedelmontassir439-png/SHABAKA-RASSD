# -*- coding: utf-8 -*-
"""Comment répondre à un marché de la source privée, et à qui s'adresser.

La liste de la source privée ne donne que l'intitulé, l'acheteur, le budget
et le jour limite. La fiche de chaque avis en dit bien plus — relevé le
25/10/2026: l'heure limite, la soumission électronique ou non, l'adresse de
retrait du dossier, le contact chez l'acheteur (nom, téléphone, email), la
caution, la visite, le délai d'exécution, les observations de l'acheteur
(« réservé aux PME », « date reportée ») et le dossier (DAO) à télécharger.

On lit cette fiche une fois par avis, et on réécrit ses champs avec les
étiquettes des avis du portail national (app/core/conditions.py): les cases
« Conditions de l'avis » et l'encadré « Comprendre cet avis » les lisent
alors sans rien changer d'autre. Les coordonnées restent réservées aux
membres: les pages publiques n'existent que pour le portail national.
"""
import logging
import re
import time
from datetime import datetime
from html import unescape

import requests

from app.core.database import get_db

logger = logging.getLogger("atlas.fiches_privees")

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
BASE = "https://global-marches.com"
PAUSE = 1.5
# Version de la lecture, préfixée à fiche_lue: une fiche lue par une
# version antérieure est relue une fois. v2 (25/10/2026): le portail
# national n'est plus supposé quand l'avis ne le nomme pas.
# v3 (29/10/2026): les bons de commande (/share-po/) sont lus aussi, avec
# l'allotissement et le journal où l'annonce a paru.
VERSION = "v3"

# Les étiquettes de la fiche, dans leur ordre. La valeur court jusqu'à la
# suivante. « D.réunion » n'a pas de deux-points sur la page.
_ETIQUETTES = (
    ("ordre", r"N d'ordre\s*:"), ("reference", r"Référence\s*:"),
    ("limite", r"Date/Heure limite\s*:"), ("organisme", r"Organisme\s*:"),
    ("objet", r"Objet\s*:"), ("ville", r"Ville d'exécution\s*:"),
    ("lots", r"Allotissement\s*:"),
    ("retrait", r"Adresse retrait\s*:"), ("contact", r"Contact\s*:"),
    ("montant_retrait", r"Montant retrait\s*:"), ("ouverture", r"D\.ouvr\.Plis\s*:"),
    ("paiement", r"Mode paiement\s*:"), ("echantillons", r"D\.Dépot\.D'ech\s*:"),
    ("caution", r"Mt caution\s*:"), ("reunion", r"D\.réunion\s*:?"),
    ("budget", r"Budget\s*:"), ("delai", r"Délais D'exécution\s*:"),
    ("visite", r"Visite des lieux\s*:"), ("dao", r"Télécharger D\.A\.O"),
    ("image", r"Image Intégral+e"),
    ("type", r"Type\s*:"), ("observation", r"Obsérvation\s*:"),
    ("electronique", r"Soumission électronique\s*:"), ("fin", r"Cliquer ici|Support SUPPORT"),
)
_MOTIF = re.compile("|".join(f"(?P<{c}>{m})" for c, m in _ETIQUETTES))
_VIDE = {"", "-", "--", "---", "----", "------"}


def _texte(html: str) -> str:
    t = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html or "", flags=re.S | re.I)
    t = unescape(re.sub(r"<[^>]+>", " ", t))
    return re.sub(r"\s+", " ", t).strip()


def lire_fiche(html: str) -> dict:
    """Les champs de la fiche, nettoyés. {} si la page n'est pas une fiche."""
    texte = _texte(html)
    reperes = [(m.start(), m.end(), m.lastgroup) for m in _MOTIF.finditer(texte)]
    if not any(r[2] == "reference" for r in reperes):
        return {}
    champs = {}
    for n, (_, fin, cle) in enumerate(reperes):
        if cle in champs or cle == "fin":
            continue
        borne = reperes[n + 1][0] if n + 1 < len(reperes) else len(texte)
        valeur = texte[fin:borne].strip(" :-–—")
        if valeur not in _VIDE:
            champs[cle] = valeur[:600]
    # Le journal où l'annonce a paru: « SUPPORT DU PAGE/COLONNE Le matin 27/04/2019 ».
    journal = re.search(r"SUPPORT DU PAGE/COLONNE\s+(.+?)\s+\d{1,2}/\d{1,2}/\d{2,4}", texte)
    if journal and len(journal.group(1)) < 60:
        champs["journal"] = journal.group(1).strip()
    dao = re.search(r'href="(/downoaldcps/[^"]+)"', html or "")
    if dao:
        champs["dao_url"] = BASE + dao.group(1)
    return champs


def _contact(brut: str) -> str:
    """« sara Daoudi - Téléphone: +2125… - Email: x@y - Télécopieur: … »
    -> « sara Daoudi x@y +2125… » (le fax n'aide pas à joindre)."""
    b = re.split(r"T[ée]l[ée]copieur\s*:", brut or "", flags=re.I)[0]
    b = re.sub(r"\b(T[ée]l[ée]phone|Email|E-mail|Tél)\s*:", " ", b, flags=re.I)
    return re.sub(r"\s*-\s*", " ", re.sub(r"\s+", " ", b)).strip(" -")


def description(acheteur: str, objet: str, f: dict) -> str:
    """La fiche réécrite avec les étiquettes du portail national."""
    p = [f"{acheteur} {objet}".strip()]
    if f.get("limite"):
        p.append(f"Date et heure limite de remise des plis : {f['limite']}")
    if f.get("reference"):
        p.append(f"Référence {f['reference']}")
    electronique = (f.get("electronique") or "").lower().startswith("oui")
    # La source dit « Soumission électronique : Oui » sans dire où. On ne
    # nomme le portail national que si l'avis le nomme: certaines sociétés
    # ont leur propre plateforme (relevé du 25/10/2026 sur 24 fiches).
    portail = bool(re.search(r"portail des march[ée]s publics|marchespublics\.gov\.ma",
                             (f.get("observation") or "") + " " + (f.get("retrait") or ""), re.I))
    if f.get("retrait"):
        p.append(f"Adresse de retrait des dossiers : {f['retrait']}")
    elif electronique and portail:
        p.append("Adresse de retrait des dossiers : www.marchespublics.gov.ma")
    if electronique and portail:
        p.append("Adresse de dépôt des offres : dépôt électronique sur www.marchespublics.gov.ma")
    elif electronique:
        p.append("Adresse de dépôt des offres : dépôt électronique — plateforme indiquée dans l'avis "
                 "ou le DAO (le plus souvent le portail des marchés publics)")
    elif f.get("electronique"):
        p.append("Adresse de dépôt des offres : dépôt papier auprès de l'acheteur — "
                 + (f.get("retrait") or "voir l'avis"))
    elif f.get("journal") and not f.get("retrait"):
        # Bons de commande d'acheteurs particuliers: la fiche ne donne pas
        # d'adresse, l'annonce de presse si.
        p.append("Adresse de dépôt des offres : auprès de l'acheteur, à l'adresse indiquée "
                 f"dans l'annonce parue dans le journal « {f['journal'].title()} »")
    if f.get("lots"):
        p.append(f"Allotissement : {f['lots']}")
    if f.get("ouverture"):
        p.append(f"Lieu d'ouverture des plis : {f['ouverture']}")
    if f.get("montant_retrait"):
        p.append(f"Prix d'acquisition des plans : {f['montant_retrait']}")
    if f.get("caution"):
        p.append(f"Caution provisoire : {f['caution']}")
    if f.get("echantillons"):
        p.append(f"Prospectus, notices ou autres documents : Date et heure limite : {f['echantillons']}")
    if f.get("reunion"):
        p.append(f"Réunion : Date et heure : {f['reunion']}")
    if f.get("visite"):
        p.append(f"Visites des lieux : {f['visite']}")
    if f.get("delai"):
        p.append(f"Délai d'exécution prévu : {f['delai']}")
    if f.get("type"):
        p.append(f"Type de consultation : {f['type']}")
    # « plus de détaille ( voir image intégrale ) » renvoie à une image de la
    # source, pas à l'acheteur: rien à en dire au membre.
    if f.get("observation") and not re.fullmatch(r"[^.]{0,40}image int[ée]gral+e\s*\)?\s*", f["observation"], re.I):
        p.append(f"Observations de l'acheteur : {f['observation']}")
    if f.get("contact"):
        p.append(f"Contact Administratif : {_contact(f['contact'])}")
    return " ".join(p)[:3000]


def enrichir(limite: int = 60, session=None, pause: float = PAUSE, log_fn=None) -> int:
    """Lit la fiche des avis ouverts de la source privée qui ne l'ont pas été.

    Une fiche lue est marquée (`fiche_lue`), qu'elle ait donné quelque chose
    ou non: on ne la redemande pas à chaque collecte.
    """
    db = get_db()
    try:
        a_lire = [dict(r) for r in db.execute(
            """SELECT id, objet, acheteur, url, description FROM tenders
               WHERE source='global-marches' AND statut='actif'
                 AND COALESCE(fiche_lue,'') NOT LIKE ?
                 AND (url LIKE '%/share/%' OR url LIKE '%/share-po/%')
               ORDER BY COALESCE(fiche_lue,'') = '' DESC, scraped_at DESC LIMIT ?""",
            (VERSION + ":%", limite)).fetchall()]
    finally:
        db.close()
    if not a_lire:
        return 0
    s = session or requests.Session()
    s.headers.update({"User-Agent": UA})
    lues = 0
    for t in a_lire:
        champs = {}
        try:
            r = s.get(t["url"], timeout=25)
            if r.status_code == 200:
                champs = lire_fiche(r.text)
        except requests.RequestException as e:
            logger.warning(f"[fiches_privees] {t['id']}: {e}")
            continue
        maintenant = VERSION + ":" + datetime.now().isoformat(timespec="seconds")
        db = get_db()
        try:
            if champs:
                db.execute("UPDATE tenders SET description=?, dao_url=?, fiche_lue=? WHERE id=?",
                           (description(t["acheteur"] or "", t["objet"] or "", champs),
                            champs.get("dao_url", ""), maintenant, t["id"]))
                lues += 1
            else:
                db.execute("UPDATE tenders SET fiche_lue=? WHERE id=?", (maintenant, t["id"]))
            db.commit()
        finally:
            db.close()
        if pause:
            time.sleep(pause)
    if log_fn:
        log_fn(f"✓ Fiches de la source privée lues: {lues}/{len(a_lire)}")
    return lues
