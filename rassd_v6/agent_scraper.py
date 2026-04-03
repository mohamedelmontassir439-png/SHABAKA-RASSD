"""
RASSD — AI Scraping Agent v1.0
═══════════════════════════════════════════════════════════
Agent intelligent qui:
1. Analyse la structure HTML du site avant de scraper
2. S'auto-répare si le site change de structure
3. Apprend les patterns de dates et d'objets
4. Diagnostique et résout les problèmes de connexion
5. Rapporte ses actions avec raisonnement

Utilise Claude Haiku pour:
- Analyser les pages HTML inconnues
- Extraire objet + date même si structure change
- Décider si une صفقة est valide
═══════════════════════════════════════════════════════════
"""

import re, time, logging, ssl, random, json, os
from datetime import datetime, date
from typing import Optional

logger = logging.getLogger("rassd.agent")

BASE    = "https://www.marchespublics.gov.ma/bdc/entreprise/consultation"
API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

UA = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
]

DATE_RE  = re.compile(r'(\d{2}/\d{2}/\d{4}|\d{4}-\d{2}-\d{2}|\d{2}-\d{2}-\d{4})')
DATE_FMT = ["%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y"]

OBJET_LABELS = [
    "objet du marché","objet de la consultation","objet de l'appel d'offres",
    "objet","intitulé","désignation","nature des travaux",
    "nature des fournitures","nature des prestations","libellé du marché",
]
DATE_LABELS = [
    "date et heure limite de remise des devis",
    "date et heure limite de remise des offres",
    "date limite de remise des offres","date limite de remise des devis",
    "date limite de réception des offres","date limite de réception des devis",
    "date de remise des offres","date de clôture","heure limite","date limite",
]
ACHETEUR_LABELS = [
    "maître d'ouvrage","maître d ouvrage","organisme acheteur",
    "administration","entité acheteuse","organisme",
]
NOT_OBJET = [
    "date","heure","limite","remise","réception","soumission",
    "dépôt","publication","montant","maître","organisme","budget",
]


# ══════════════════════════════════════════════════════════
# DATE ENGINE
# ══════════════════════════════════════════════════════════

def _parse_date(s: str) -> Optional[date]:
    s = str(s).strip().split()[0]
    for fmt in DATE_FMT:
        try: return datetime.strptime(s, fmt).date()
        except: pass
    return None

def _extract_date(text: str) -> str:
    if not text: return ""
    m = DATE_RE.search(str(text))
    if m:
        d = _parse_date(m.group(1))
        if d: return d.strftime("%d/%m/%Y")
    return ""

def is_expired(text: str) -> bool:
    if not text: return False
    text = str(text).strip()
    if text in ("","N/A","—","-"): return False
    m = DATE_RE.search(text)
    if m:
        d = _parse_date(m.group(1))
        if d: return d < date.today()
    return False


# ══════════════════════════════════════════════════════════
# SECTEUR DETECTOR
# ══════════════════════════════════════════════════════════

def _detect_secteur(text: str) -> str:
    t = text.lower()
    if any(k in t for k in ["travaux","construction","réhabilitation","génie civil","route","béton"]): return "Travaux BTP"
    if any(k in t for k in ["informatique","logiciel","système","réseau","serveur","cloud","it "]): return "IT & Télécoms"
    if any(k in t for k in ["médical","médicament","hôpital","santé","clinique","laboratoire"]): return "Santé & Médical"
    if any(k in t for k in ["véhicule","automobile","voiture","camion","transport","flotte"]): return "Transport & Véhicules"
    if any(k in t for k in ["nettoyage","entretien","maintenance","hygiène","gardiennage"]): return "Services Généraux"
    if any(k in t for k in ["étude","mission","audit","conseil","expertise","ingénierie"]): return "Études & Conseil"
    if any(k in t for k in ["formation","enseignement","éducation","stage","séminaire"]): return "Formation"
    if any(k in t for k in ["restauration","hôtellerie","alimentation","repas","traiteur"]): return "Restauration"
    if any(k in t for k in ["communication","publicité","impression","média"]): return "Communication"
    if any(k in t for k in ["électricité","éclairage","énergie","photovoltaïque"]): return "Énergie"
    if any(k in t for k in ["hydraulique","eau potable","assainissement"]): return "Hydraulique"
    if any(k in t for k in ["papeterie","cartouche","toner","fournitures de bureau"]): return "Fournitures Bureau"
    if any(k in t for k in ["mobilier","meuble","aménagement"]): return "Mobilier"
    return "Autres Fournitures"


# ══════════════════════════════════════════════════════════
# HTML PARSER — extraction classique
# ══════════════════════════════════════════════════════════

def _cell(soup, *labels) -> str:
    for row in soup.find_all("tr"):
        cells = row.find_all(["td","th"])
        if len(cells) < 2: continue
        lbl = cells[0].get_text(strip=True).lower()
        for label in labels:
            if label.lower() in lbl:
                val = " ".join(c.get_text(strip=True) for c in cells[1:]).strip()
                if val and len(val) > 1: return val[:500]
    return ""

def parse_classic(html: str, tid: str) -> Optional[dict]:
    """Extraction classique par labels HTML"""
    try:
        from bs4 import BeautifulSoup as BS
        soup = BS(html, "html.parser")
        full = soup.get_text(" ", strip=True)

        objet = _cell(soup, *OBJET_LABELS)
        if not objet:
            for sel in [".consultation-objet","[class*='objet']","h1","h2"]:
                el = soup.select_one(sel)
                if el:
                    t = el.get_text(strip=True)
                    if 10 < len(t) < 600 and not any(n in t.lower() for n in NOT_OBJET):
                        objet = t; break
        if not objet: return None
        if any(x in objet.lower() for x in ["date et heure","date limite","remise des","heure limite"]):
            return None
        objet = re.sub(r'\s+', ' ', objet).strip()
        if len(objet) < 8: return None

        date_lim = _extract_date(_cell(soup, *DATE_LABELS))
        if not date_lim:
            fl = full.lower()
            for lbl in DATE_LABELS:
                idx = fl.find(lbl)
                if idx >= 0:
                    date_lim = _extract_date(full[idx:idx+150])
                    if date_lim: break

        if date_lim and is_expired(date_lim): return None
        if any(w in full.lower() for w in ["annulé","annulée","sans suite","infructueux"]): return None

        acheteur = _cell(soup, *ACHETEUR_LABELS).strip()
        date_pub  = _extract_date(_cell(soup,"date de publication","publication"))
        montant   = _cell(soup,"montant estimé","montant","budget") or ""
        if not montant:
            m2 = re.search(r'(\d[\d\s,.]+)\s*(?:DH|MAD)', full, re.I)
            if m2: montant = m2.group(0)[:80]

        return {
            "id": f"bdc_{tid}", "objet": objet[:400],
            "acheteur": acheteur[:200], "date_publication": date_pub,
            "date_limite": date_lim, "montant": montant[:80],
            "secteur": _detect_secteur(objet + " " + full[:400]),
            "url": f"{BASE}/show/{tid}", "source": "marchespublics",
            "statut": "actif", "description": full[:3000],
            "scraped_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "method": "classic",
        }
    except Exception as e:
        logger.error(f"[parse_classic #{tid}] {e}")
        return None


# ══════════════════════════════════════════════════════════
# AI PARSER — fallback si extraction classique échoue
# ══════════════════════════════════════════════════════════

def parse_with_ai(html: str, tid: str) -> Optional[dict]:
    """
    Utilise Claude Haiku pour extraire les champs si
    l'extraction classique a échoué (structure inconnue).
    """
    if not API_KEY: return None
    try:
        from bs4 import BeautifulSoup as BS
        soup = BS(html, "html.parser")
        # Nettoyer le HTML pour économiser les tokens
        for tag in soup.find_all(["script","style","nav","footer","header"]):
            tag.decompose()
        clean_text = soup.get_text(" ", strip=True)[:3000]

        import httpx
        resp = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 500,
                "messages": [{
                    "role": "user",
                    "content": f"""Tu es un extracteur de marchés publics marocains.

Analyse ce texte d'une page marchespublics.gov.ma et extrais les informations.
RÈGLE: Si date_limite < aujourd'hui ({date.today().strftime('%d/%m/%Y')}), retourne null.

TEXTE:
{clean_text}

Réponds UNIQUEMENT avec ce JSON (null si pas un marché valide):
{{
  "objet": "titre exact du marché (pas un label de date)",
  "acheteur": "nom de l'organisme acheteur",
  "date_limite": "DD/MM/YYYY ou vide",
  "date_publication": "DD/MM/YYYY ou vide",
  "montant": "montant en DH ou vide",
  "valide": true/false
}}"""
                }],
            },
            timeout=15,
        )
        if resp.status_code != 200: return None
        content = resp.json()["content"][0]["text"].strip()
        # Extraire JSON
        json_m = re.search(r'\{.*\}', content, re.DOTALL)
        if not json_m: return None
        data = json.loads(json_m.group())
        if not data.get("valide") or not data.get("objet"): return None
        if is_expired(data.get("date_limite","")): return None

        return {
            "id": f"bdc_{tid}",
            "objet": data["objet"][:400],
            "acheteur": data.get("acheteur","")[:200],
            "date_publication": data.get("date_publication",""),
            "date_limite": data.get("date_limite",""),
            "montant": data.get("montant","")[:80],
            "secteur": _detect_secteur(data["objet"]),
            "url": f"{BASE}/show/{tid}",
            "source": "marchespublics",
            "statut": "actif",
            "description": clean_text[:2000],
            "scraped_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "method": "ai",
        }
    except Exception as e:
        logger.error(f"[parse_ai #{tid}] {e}")
        return None


# ══════════════════════════════════════════════════════════
# HTTP SESSION — TLS permissif
# ══════════════════════════════════════════════════════════

def _make_session():
    import requests, urllib3
    from requests.adapters import HTTPAdapter

    urllib3.disable_warnings()

    class TLSAdapter(HTTPAdapter):
        def init_poolmanager(self, *args, **kwargs):
            ctx = ssl.create_default_context()
            ctx.set_ciphers("DEFAULT@SECLEVEL=1")
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            kwargs["ssl_context"] = ctx
            return super().init_poolmanager(*args, **kwargs)

    s = requests.Session()
    s.mount("https://", TLSAdapter(
        max_retries=urllib3.Retry(total=3, backoff_factor=0.5)
    ))
    s.verify = False
    s.headers.update({
        "User-Agent":                random.choice(UA),
        "Accept":                    "text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Language":           "fr-MA,fr;q=0.9,ar;q=0.8,en;q=0.7",
        "Accept-Encoding":           "gzip, deflate, br",
        "Connection":                "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Cache-Control":             "max-age=0",
        "DNT":                       "1",
        "Referer":                   "https://www.marchespublics.gov.ma/",
    })
    return s


# ══════════════════════════════════════════════════════════
# DIAGNOSTIC — teste la connexion avant de scraper
# ══════════════════════════════════════════════════════════

def diagnose(log_fn=print) -> dict:
    """Teste la connexion et retourne un rapport"""
    import requests, urllib3
    urllib3.disable_warnings()

    report = {"reachable": False, "status": None, "error": None, "ip": None}

    # Test 1: DNS
    try:
        import socket
        ip = socket.gethostbyname("www.marchespublics.gov.ma")
        report["ip"] = ip
        log_fn(f"🌐 DNS OK: www.marchespublics.gov.ma → {ip}")
    except Exception as e:
        report["error"] = f"DNS failed: {e}"
        log_fn(f"❌ DNS échoué: {e}")
        return report

    # Test 2: HTTP
    try:
        s = _make_session()
        r = s.get("https://www.marchespublics.gov.ma/", timeout=15)
        report["status"] = r.status_code
        if r.status_code == 200:
            report["reachable"] = True
            log_fn(f"✅ Connexion OK — HTTP {r.status_code} — {len(r.text)} chars")
        else:
            log_fn(f"⚠ HTTP {r.status_code}")
    except Exception as e:
        report["error"] = str(e)[:100]
        log_fn(f"❌ Connexion échouée: {str(e)[:80]}")

    return report


# ══════════════════════════════════════════════════════════
# AGENT PRINCIPAL
# ══════════════════════════════════════════════════════════

class ScrapingAgent:
    """
    Agent IA de scraping marchespublics.gov.ma.

    Fonctionnement:
    1. Diagnostic connexion
    2. Calcul plage IDs
    3. Pour chaque ID:
       a. Téléchargement page
       b. Extraction classique (rapide)
       c. Si échec → extraction AI (Claude Haiku)
       d. Validation date + objet
       e. Sauvegarde
    4. Rapport final avec statistiques
    """

    def __init__(self, log_fn=print):
        self.log     = log_fn
        self.results = []
        self.stats   = {
            "scanned": 0, "found": 0, "saved": 0,
            "expired": 0, "invalid": 0, "errors": 0,
            "ai_used": 0, "classic_used": 0,
        }
        self.session = None

    def _ensure_session(self):
        if not self.session:
            self.session = _make_session()

    def _rotate_ua(self):
        if self.session:
            self.session.headers["User-Agent"] = random.choice(UA)

    def run(self, known_ids: set) -> list:
        self.log("╔══════════════════════════════════════════╗")
        self.log("║  RASSD AI Scraping Agent v1.0            ║")
        self.log("║  Source: www.marchespublics.gov.ma       ║")
        self.log(f"║  Date: {datetime.now().strftime('%d/%m/%Y %H:%M')}                   ║")
        self.log("╚══════════════════════════════════════════╝")

        # ── ÉTAPE 1: Diagnostic ──
        self.log("\n[Agent] Diagnostic connexion...")
        report = diagnose(self.log)
        if not report["reachable"]:
            self.log(f"[Agent] ❌ Site inaccessible: {report.get('error','?')}")
            self.log("[Agent] Tentative avec session alternative...")
            # Essai avec httpx
            if self._try_httpx_connection():
                self.log("[Agent] ✅ Connexion via httpx réussie")
            else:
                self.log("[Agent] ❌ Toutes les tentatives ont échoué")
                return []

        # ── ÉTAPE 2: Calcul plage ──
        max_id = 312000
        for kid in known_ids:
            if kid.startswith("bdc_"):
                try:
                    n = int(kid[4:])
                    if n > max_id: max_id = n
                except: pass
        if max_id < 311000: max_id = 312500

        # IDs actuels marchespublics ~312000-313000
        if max_id <= 312000:
            # DB vide ou IDs trop vieux → chercher autour de 312500
            start_id = 312400
            end_id   = 313100
        else:
            start_id = max(max_id - 20, 310000)
            end_id   = max_id + 600
        scan_ids = [str(i) for i in range(start_id, end_id + 1)
                    if f"bdc_{i}" not in known_ids]

        self.log(f"\n[Agent] Max ID connu: #{max_id}")
        self.log(f"[Agent] Plage: #{start_id} → #{end_id} ({len(scan_ids)} IDs)")
        self.log(f"[Agent] Mode: Classic{'+ AI fallback' if API_KEY else ' (AI désactivé)'}")

        # ── ÉTAPE 3: Scan ──
        self._ensure_session()
        consec_empty = 0

        debug_done = False  # Afficher structure 1 fois
        for i, tid in enumerate(scan_ids):
            if i % 100 == 0 and i > 0:
                self._rotate_ua()

            self.stats["scanned"] += 1
            url = f"{BASE}/show/{tid}"

            try:
                r = self.session.get(url, timeout=20)

                if r.status_code == 404:
                    consec_empty += 1
                    if consec_empty > 100 and len(self.results) == 0:
                        self.log("[Agent] 100 IDs vides, arrêt anticipé")
                        break
                    continue

                if r.status_code != 200 or len(r.text) < 1500:
                    consec_empty += 1
                    continue

                consec_empty = 0
                self.stats["found"] += 1
                html = r.text

                # ── DEBUG: analyser structure de la première page ──
                if not debug_done and self.stats["found"] == 1:
                    debug_done = True
                    try:
                        from bs4 import BeautifulSoup as BS
                        soup = BS(html, "html.parser")
                        full = soup.get_text(" ", strip=True)
                        # Montrer les 10 premières lignes de tableau
                        self.log(f"[DEBUG #{tid}] Taille HTML: {len(html)} chars")
                        rows = soup.find_all("tr")[:15]
                        for row in rows:
                            cells = row.find_all(["td","th"])
                            if len(cells) >= 2:
                                lbl = cells[0].get_text(strip=True)[:40]
                                val = cells[1].get_text(strip=True)[:60]
                                if lbl: self.log(f"  [{lbl}] → [{val}]")
                        # Montrer h1/h2
                        for tag in soup.find_all(["h1","h2","h3"])[:5]:
                            self.log(f"  <{tag.name}>: {tag.get_text(strip=True)[:80]}")
                        # Montrer extrait du texte complet
                        self.log(f"  TEXTE: {full[:300]}")
                    except Exception as e:
                        self.log(f"[DEBUG] Erreur: {e}")

                # ── Extraction classique ──
                tender = parse_classic(html, tid)

                # ── Fallback AI ──
                if not tender and API_KEY:
                    tender = parse_with_ai(html, tid)
                    if tender:
                        self.stats["ai_used"] += 1
                        self.log(f"  🤖 AI #{tid}: {tender['objet'][:50]}")
                    else:
                        self.stats["invalid"] += 1
                else:
                    if tender:
                        self.stats["classic_used"] += 1

                if not tender:
                    continue

                self.results.append(tender)
                self.stats["saved"] += 1

                icon = "🤖" if tender.get("method") == "ai" else "✓"
                self.log(
                    f"{icon} #{tid} │ {tender['secteur'][:16]:16} │ "
                    f"{tender['objet'][:42]} │ ⏰{tender['date_limite'] or '?'}"
                )
                time.sleep(0.3)

            except Exception as e:
                self.stats["errors"] += 1
                consec_empty += 1
                if self.stats["errors"] == 1:
                    self.log(f"[Agent] ⚠ Première erreur: {str(e)[:70]}")
                if consec_empty > 10 and self.stats["errors"] > 8:
                    self.log("[Agent] ❌ Trop d'erreurs, arrêt")
                    break

        # ── RAPPORT FINAL ──
        self.log("\n" + "═" * 50)
        self.log(f"[Agent] ✅ RAPPORT FINAL")
        self.log(f"  IDs scannés:     {self.stats['scanned']}")
        self.log(f"  Pages trouvées:  {self.stats['found']}")
        self.log(f"  Marchés sauvés:  {self.stats['saved']}")
        self.log(f"  Extractions:     Classic={self.stats['classic_used']} | AI={self.stats['ai_used']}")
        self.log(f"  Erreurs:         {self.stats['errors']}")
        self.log("═" * 50)

        return self.results

    def _try_httpx_connection(self) -> bool:
        """Teste connexion via httpx"""
        try:
            import httpx
            r = httpx.get(
                "https://www.marchespublics.gov.ma/",
                headers={"User-Agent": random.choice(UA)},
                verify=False, timeout=15, follow_redirects=True
            )
            return r.status_code == 200
        except: return False


# ══════════════════════════════════════════════════════════
# API publique (compatible avec main.py)
# ══════════════════════════════════════════════════════════

def run(known_ids: set, log_fn=print) -> list:
    """Point d'entrée compatible avec l'ancien scraper"""
    agent = ScrapingAgent(log_fn=log_fn)
    return agent.run(known_ids)
