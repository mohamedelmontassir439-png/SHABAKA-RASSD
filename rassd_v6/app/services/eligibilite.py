# -*- coding: utf-8 -*-
"""Les marchés auxquels l'entreprise a le droit de répondre.

Un appel d'offres de travaux exige une qualification (« A.2 Travaux
courants en béton armé ») et une classe minimale. Sans elles, l'offre est
écartée avant d'être lue — et l'entreprise a perdu le temps de la monter.
Le membre déclare ses qualifications une fois; chaque avis du portail dit
ce qu'il exige (app/core/conditions.py); le rapprochement dit le reste.

**L'ordre des classes.** La classification marocaine va de la classe S
(spéciale, la plus haute) à la classe 1, puis 2, et ainsi de suite: plus
le chiffre est petit, plus l'entreprise peut porter de gros marchés. Une
entreprise classée 2 répond donc à un marché qui exige la classe 3, pas
l'inverse.

Quand l'avis liste plusieurs qualifications, on les considère toutes
exigées — c'est le cas courant. L'entreprise lit l'avis pour les cas où
l'acheteur écrit « ou »: on affiche chaque ligne, jamais un verdict seul.
"""
import re
from datetime import datetime

from app.core.conditions import conditions_avis
from app.core.database import get_db

CLASSES = ("S", "1", "2", "3", "4", "5", "6")


def rang(classe: str) -> int:
    c = (classe or "").strip().upper()
    return CLASSES.index(c) if c in CLASSES else 99


def exigences(texte_avis: str) -> list:
    """[{"code", "libelle", "classe"}] lues dans le champ Qualifications."""
    q = re.sub(r"\s+", " ", conditions_avis(texte_avis or "").get("qualifications", ""))
    if not q:
        return []
    morceaux = re.split(r"\s*/\s*Classe\s*(\w+)\s*", q)
    vues, liste = set(), []
    for segment, classe in zip(morceaux[0::2], morceaux[1::2]):
        libelle = segment.split("/")[-1].strip()
        m = re.match(r"^([A-Z]{1,2}\.\d+(?:\.\d+)?|\d+(?:\.\d+)+)\s*[-.]?\s*(.*)$", libelle)
        code = m.group(1) if m else libelle[:40]
        if code in vues:
            continue
        vues.add(code)
        liste.append({"code": code, "libelle": (m.group(2) if m else libelle).strip(" .")[:160],
                      "classe": classe.upper()})
    return liste


def mes_qualifications(member_id: int) -> list:
    db = get_db()
    try:
        return [dict(r) for r in db.execute(
            "SELECT * FROM qualifs_membre WHERE member_id=? ORDER BY code", (member_id,)).fetchall()]
    finally:
        db.close()


def ajouter(member_id: int, code: str, classe: str, libelle: str = "") -> bool:
    code = re.sub(r"\s+", "", code or "").upper()[:12]
    classe = (classe or "").strip().upper()
    if not re.match(r"^([A-Z]{1,2}\.\d+(?:\.\d+)?|\d+(?:\.\d+)+)$", code) or classe not in CLASSES:
        return False
    db = get_db()
    try:
        db.execute("""INSERT INTO qualifs_membre(member_id,code,libelle,classe,created_at)
                      VALUES(?,?,?,?,?)
                      ON CONFLICT(member_id, code) DO UPDATE SET classe=excluded.classe,
                         libelle=excluded.libelle""",
                   (member_id, code, (libelle or "")[:160], classe,
                    datetime.now().isoformat(timespec="seconds")))
        db.commit()
    finally:
        db.close()
    return True


def retirer(member_id: int, code: str):
    db = get_db()
    try:
        db.execute("DELETE FROM qualifs_membre WHERE member_id=? AND code=?", (member_id, code))
        db.commit()
    finally:
        db.close()


def verdict(miennes: list, exigees: list) -> dict:
    """{"etat": "libre" | "eligible" | "non_eligible" | "inconnu", "lignes": [...]}.

    « inconnu »: le membre n'a déclaré aucune qualification — on ne le
    déclare pas inéligible pour autant, on l'invite à compléter.
    """
    if not exigees:
        return {"etat": "libre", "lignes": []}
    if not miennes:
        return {"etat": "inconnu", "lignes": [dict(e, ok=None) for e in exigees]}
    par_code = {q["code"]: q for q in miennes}
    lignes = []
    for e in exigees:
        q = par_code.get(e["code"])
        ok = bool(q) and rang(q["classe"]) <= rang(e["classe"])
        lignes.append(dict(e, ok=ok, ma_classe=q["classe"] if q else ""))
    return {"etat": "eligible" if all(l["ok"] for l in lignes) else "non_eligible", "lignes": lignes}


def pour_marche(member_id: int, t: dict) -> dict:
    if not (t.get("id") or "").startswith("ao_"):
        return {"etat": "libre", "lignes": []}
    return verdict(mes_qualifications(member_id), exigences(t.get("description") or ""))


def catalogue() -> list:
    """Les qualifications vues dans les avis, pour la liste de choix."""
    db = get_db()
    try:
        textes = [r[0] for r in db.execute(
            "SELECT description FROM tenders WHERE id LIKE 'ao_%' AND description LIKE '%Classe%'").fetchall()]
    finally:
        db.close()
    vues = {}
    for t in textes:
        for e in exigences(t):
            vues.setdefault(e["code"], e["libelle"])
    return sorted(({"code": c, "libelle": l} for c, l in vues.items()),
                  key=lambda x: [(0, int(p), "") if p.isdigit() else (1, 0, p)
                                 for p in x["code"].split(".")])
