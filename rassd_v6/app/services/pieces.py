# -*- coding: utf-8 -*-
"""Les pièces jointes des marchés, servies depuis la plateforme.

Un membre qui voulait le dossier de consultation ou le procès-verbal d'une
adjudication était redirigé vers l'agrégateur: son navigateur quittait le
domaine, affichait l'adresse de la source dans la barre, et le
téléchargement se faisait ailleurs. Trois conséquences, par ordre de gravité
décroissante: le membre découvrait d'où viennent les données et n'avait plus
besoin de l'abonnement; le parcours se cassait dès que la source exigeait
une session; et le document arrivait avec un nom de fichier illisible.

Le fichier transite désormais par le serveur, qui ouvre sa propre session
chez la source, télécharge et renvoie. Le membre ne voit que
marocentrepreneuriat.com, et reçoit un fichier nommé.

Un cache sur disque évite de retélécharger la même pièce à chaque clic: ces
documents ne changent plus une fois l'adjudication publiée.
"""
import hashlib
import logging
import os
import re
import threading
import unicodedata
import time

import requests

from app.core.config import cfg

logger = logging.getLogger("atlas.pieces")

SOURCE = "https://global-marches.com"
DOSSIER_CACHE = os.path.join(os.path.dirname(cfg.DB_PATH) or "data", "pieces")
# Au-delà, on ne garde pas en cache: un volume Railway n'est pas un entrepôt.
TAILLE_MAX_CACHE = 25 * 1024 * 1024
JOURS_CACHE = 30

# La session chez la source est coûteuse à ouvrir (une authentification par
# requête sinon). Elle est partagée et reconstruite quand elle expire.
_session = None
_session_nee = 0.0
_verrou = threading.Lock()
DUREE_SESSION = 20 * 60


def _ouvrir_session():
    """Session authentifiée chez la source, réutilisée tant qu'elle vit."""
    global _session, _session_nee
    with _verrou:
        if _session is not None and time.time() - _session_nee < DUREE_SESSION:
            return _session
        s = requests.Session()
        s.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        try:
            s.get(SOURCE + "/", timeout=20)
            s.post(SOURCE + "/profile/signin",
                   data={"LOGIN": cfg.GM_USERNAME, "PASSWORD": cfg.GM_PASSWORD,
                         "CONNECT": "Se connecter"}, timeout=20)
        except Exception as e:
            logger.error(f"[pieces] connexion à la source impossible: {e}")
            return None
        _session, _session_nee = s, time.time()
        return s


def _chemin_cache(url: str) -> str:
    return os.path.join(DOSSIER_CACHE, hashlib.sha256(url.encode()).hexdigest() + ".bin")


def nom_fichier(objet: str, genre: str, extension: str = "pdf") -> str:
    """« Travaux d'entretien… » + « pv » -> « PV-travaux-d-entretien.pdf ».

    La source renvoie des noms comme « downoald-pv » ou une suite de chiffres:
    le membre se retrouvait avec vingt fichiers indistinguables dans son
    dossier de téléchargements.
    """
    # Accents mis a plat: l'en-tete Content-Disposition ne transporte
    # sûrement que de l'ASCII, et un accent mal encode produit un nom de
    # fichier illisible ou un telechargement refuse selon le navigateur.
    plat = unicodedata.normalize("NFD", (objet or "document").lower())
    plat = "".join(c for c in plat if unicodedata.category(c) != "Mn")
    base = re.sub(r"[^a-z0-9\s-]", "", plat)
    base = re.sub(r"[\s_]+", "-", base.strip())[:60].strip("-") or "document"
    prefixe = {"dao": "DAO", "pv": "PV"}.get(genre, "PIECE")
    return f"{prefixe}-{base}.{extension}"


def _extension(type_contenu: str, url: str) -> str:
    if "pdf" in (type_contenu or ""):
        return "pdf"
    if "zip" in (type_contenu or ""):
        return "zip"
    for ext in ("pdf", "zip", "doc", "docx", "xls", "xlsx"):
        if url.lower().endswith("." + ext):
            return ext
    return "pdf"


def recuperer(url: str) -> tuple:
    """Télécharge la pièce et la rend: (contenu, type, extension).

    Rend (None, "", "") si la source ne répond pas ou renvoie une page HTML —
    signe que la session a sauté ou que le document n'existe plus. Mieux vaut
    un message clair qu'un fichier de zéro octet nommé en .pdf.
    """
    if not url:
        return None, "", ""

    cache = _chemin_cache(url)
    meta = cache + ".type"
    if os.path.exists(cache) and time.time() - os.path.getmtime(cache) < JOURS_CACHE * 86400:
        try:
            with open(cache, "rb") as f:
                contenu = f.read()
            type_c = open(meta, encoding="utf-8").read().strip() if os.path.exists(meta) else "application/pdf"
            return contenu, type_c, _extension(type_c, url)
        except Exception as e:
            logger.warning(f"[pieces] cache illisible: {e}")

    s = _ouvrir_session()
    if s is None:
        return None, "", ""
    try:
        r = s.get(url, timeout=60, stream=True)
        r.raise_for_status()
        type_c = (r.headers.get("Content-Type") or "").split(";")[0].strip()
        contenu = r.content
    except Exception as e:
        logger.error(f"[pieces] téléchargement impossible ({url[:70]}): {e}")
        return None, "", ""

    # Une page HTML à la place d'un fichier: la session a expiré ou la pièce
    # a disparu. On ne sert pas ça sous un nom de PDF.
    if "html" in type_c.lower() or contenu[:15].lstrip().lower().startswith(b"<!doctype"):
        logger.warning(f"[pieces] la source a renvoyé une page, pas un fichier: {url[:70]}")
        return None, "", ""

    if len(contenu) <= TAILLE_MAX_CACHE:
        try:
            os.makedirs(DOSSIER_CACHE, exist_ok=True)
            with open(cache, "wb") as f:
                f.write(contenu)
            with open(meta, "w", encoding="utf-8") as f:
                f.write(type_c or "application/pdf")
        except Exception as e:
            logger.warning(f"[pieces] mise en cache impossible: {e}")

    return contenu, type_c or "application/pdf", _extension(type_c, url)
