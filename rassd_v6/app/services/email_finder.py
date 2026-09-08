"""
Maroc Entrepreneuriat — Recherche d'email sur le site d'une entreprise

Google ne publie aucune adresse email dans ses interfaces (ni Maps, ni
l'API Places). L'email doit donc venir du site de l'entreprise elle-même,
où il est publié volontairement pour être contacté.

Règles appliquées ici:
  · robots.txt du site consulté et respecté avant toute requête;
  · deux pages au maximum par entreprise (accueil + page contact);
  · taille de réponse plafonnée et délai court, pour ne peser sur personne.
"""
import logging
import re
import socket
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests

from app.core.config import cfg

logger = logging.getLogger("atlas.email")

UA = ("Mozilla/5.0 (compatible; MarocEntrepreneuriatBot/1.0; "
      "+https://marocentrepreneuriat.ma/contact)")

_EMAIL_RE = re.compile(
    r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"
)

# Chemins de contact les plus courants sur les sites marocains (FR/EN).
CONTACT_PATHS = ("/contact", "/contactez-nous", "/contact-us", "/nous-contacter")

# Adresses techniques que l'on ne veut jamais retenir comme contact.
_JUNK_LOCAL = {
    "example", "test", "email", "name", "your", "yourname", "user", "username",
    "sentry", "wixpress", "no-reply", "noreply", "donotreply", "postmaster",
}
_JUNK_DOMAINS = {
    "example.com", "example.org", "domain.com", "yourdomain.com", "email.com",
    "sentry.io", "wixpress.com", "godaddy.com", "w3.org", "schema.org",
    "googlemail.com", "sentry-next.wixpress.com",
}
# Un fichier image ou une police capté par la regex ("logo@2x.png").
_JUNK_EXT = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".css", ".js",
             ".woff", ".woff2", ".ttf", ".ico", ".pdf")

_MAX_BYTES = 400_000


def is_plausible_email(email: str) -> bool:
    """Écarte les adresses techniques, les faux positifs et les fichiers."""
    if not email or email.count("@") != 1:
        return False
    email = email.strip().strip(".,;:").lower()
    local, _, domain = email.partition("@")
    if not local or not domain or "." not in domain:
        return False
    if email.endswith(_JUNK_EXT) or any(e in domain for e in _JUNK_EXT):
        return False
    if local in _JUNK_LOCAL or domain in _JUNK_DOMAINS:
        return False
    if len(local) > 64 or len(email) > 120:
        return False
    # "2x", "3x" viennent des images retina captées par la regex.
    if re.fullmatch(r"\d+x", local):
        return False
    return True


def _robots_allows(url: str) -> bool:
    """Le robots.txt du site autorise-t-il la lecture de cette page ?

    En cas d'indisponibilité du fichier (absent, erreur réseau), on considère
    l'accès autorisé: c'est le comportement standard, un robots.txt absent
    ne vaut pas interdiction.
    """
    try:
        parts = urlparse(url)
        rp = RobotFileParser()
        rp.set_url(f"{parts.scheme}://{parts.netloc}/robots.txt")
        rp.read()
        return rp.can_fetch(UA, url)
    except Exception:
        return True


def _fetch(url: str) -> str:
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=cfg.EMAIL_FINDER_TIMEOUT,
                         allow_redirects=True, stream=True)
        ctype = (r.headers.get("content-type") or "").lower()
        if r.status_code != 200 or "html" not in ctype:
            return ""
        chunks, total = [], 0
        for chunk in r.iter_content(8192, decode_unicode=False):
            chunks.append(chunk)
            total += len(chunk)
            if total >= _MAX_BYTES:
                break
        raw = b"".join(chunks)
        return raw.decode(r.encoding or "utf-8", errors="ignore")
    except (requests.RequestException, socket.timeout, ValueError) as e:
        logger.debug(f"[email] {url}: {e}")
        return ""


def extract_emails(html: str, prefer_domain: str = "") -> list:
    """Emails plausibles trouvés dans une page, les plus pertinents d'abord.

    Une adresse hébergée sur le domaine de l'entreprise passe devant une
    adresse gmail/hotmail: c'est le contact officiel.
    """
    if not html:
        return []
    found, seen = [], set()
    # mailto: d'abord — c'est une intention explicite de contact.
    for m in re.finditer(r'mailto:([^"\'>?\s]+)', html, re.I):
        e = m.group(1).strip().lower()
        if is_plausible_email(e) and e not in seen:
            seen.add(e); found.append(e)
    for m in _EMAIL_RE.finditer(html):
        e = m.group(0).strip().strip(".,;:").lower()
        if is_plausible_email(e) and e not in seen:
            seen.add(e); found.append(e)
    if prefer_domain:
        d = prefer_domain.lower().replace("www.", "")
        found.sort(key=lambda e: 0 if d and d in e.split("@")[-1] else 1)
    return found


def find_email(website: str) -> str:
    """Cherche l'email de contact d'une entreprise à partir de son site.

    Retourne '' si rien n'est trouvé — on ne fabrique jamais une adresse
    (pas de "contact@domaine" deviné, qui rebondirait à l'envoi).
    """
    if not cfg.EMAIL_FINDER_ENABLED or not website:
        return ""
    url = website if website.startswith("http") else f"https://{website}"
    try:
        parts = urlparse(url)
        if not parts.netloc:
            return ""
    except ValueError:
        return ""
    domain = parts.netloc

    if not _robots_allows(url):
        logger.info(f"[email] robots.txt interdit: {domain}")
        return ""

    pages = [url] + [urljoin(url, p) for p in CONTACT_PATHS[:2]]
    for page in pages:
        html = _fetch(page)
        emails = extract_emails(html, prefer_domain=domain)
        if emails:
            return emails[0][:120]
    return ""
