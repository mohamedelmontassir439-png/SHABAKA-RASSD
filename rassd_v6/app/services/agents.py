"""
Modern Business — Agents IA background
ClassifierAgent, ScraperAgent, NotifyAgent,
MonitorAgent, SelfHealingAgent, ChatAgent
"""
import re, json, asyncio, logging, secrets
from datetime import datetime, date
from app.core.config   import cfg
from app.core.database import get_db
from app.core.dates    import is_expired, format_deadline, extract_deadline
from app.services.storage    import save_tender, save_many, expire_old, get_known_ids
from app.notifications.telegram import send as tg_send, notify_admin, build_message as tg_build
from app.notifications.email    import send as email_send, build_email_html
from app.scrapers.marchespublics import run as scrape_marchespublics
from app.scrapers.journaux       import run_all as scrape_journaux
from app.scrapers.ofppt          import run as scrape_ofppt

logger = logging.getLogger(__name__)

class ClassifierAgent:
    @staticmethod
    def clean_objet(text: str) -> str:
        t = re.sub(r'^#\s*0*\d+\s*', '', text.strip())
        t = re.sub(r'^LOT\s*[N°n°#]?\s*\d+\s*[:\-–]?\s*', '', t, flags=re.I)
        t = re.sub(r'^[\d]+\s*[:\-–]\s*', '', t)
        t = re.sub(r'\s+', ' ', t).strip()
        return t[0].upper() + t[1:] if t and t[0].islower() else t

    @staticmethod
    def region(text: str) -> str:
        txt = text.lower()
        for region, kws in REGIONS.items():
            if any(k in txt for k in kws): return region
        return "Maroc"

    @staticmethod
    def secteur(text: str) -> str:
        txt = text.lower()
        scores: dict = defaultdict(int)
        for sect, kws in SECTEURS.items():
            for kw in kws:
                if kw in txt:
                    scores[sect] += 2 if len(kw) > 10 else 1
        return max(scores, key=scores.get) if scores else "P825 - Fournitures Bureau"

    @staticmethod
    def type_marche(text: str) -> str:
        t = text.lower()
        if any(k in t for k in ["travaux","construction","réhabilitation","pose","démolition","rénovation"]): return "Travaux"
        if any(k in t for k in ["fourniture","livraison","achat","acquisition","matériel","équipement"]): return "Fournitures"
        if any(k in t for k in ["service","prestation","maintenance","entretien","gardiennage","nettoyage"]): return "Services"
        if any(k in t for k in ["étude","mission","audit","conseil","formation","expertise"]): return "Études & Conseil"
        return "Fournitures"

    @staticmethod
    def is_expired(d: str) -> bool:
        """Vérifie si date passée. Supporte: DD/MM/YYYY, YYYY-MM-DD, texte mixte"""
        if not d: return False
        d = str(d).strip()
        if d in ("N/A","—","","-","null","Non précisée"): return False
        today = datetime.now().date()
        for pat, fmt in [
            (r"(\d{2}/\d{2}/\d{4})", "%d/%m/%Y"),
            (r"(\d{4}-\d{2}-\d{2})", "%Y-%m-%d"),
            (r"(\d{2}-\d{2}-\d{4})", "%d-%m-%Y"),
            (r"(\d{2}\.\d{2}\.\d{4})", "%d.%m.%Y"),
        ]:
            m = re.search(pat, d)
            if m:
                try: return datetime.strptime(m.group(1), fmt).date() < today
                except: pass
        return False


    @staticmethod
    def extract_date(text: str) -> str:
        """Extrait la date depuis un texte — retourne YYYY-MM-DD"""
        if not text: return ""
        text = str(text)
        # DD/MM/YYYY avec heure optionnelle
        m = re.search(r'(\d{2}/\d{2}/\d{4})', text)
        if m:
            try:
                return datetime.strptime(m.group(1), "%d/%m/%Y").strftime("%Y-%m-%d")
            except: pass
        # YYYY-MM-DD
        m = re.search(r'(\d{4}-\d{2}-\d{2})', text)
        if m: return m.group(1)
        # DD-MM-YYYY ou DD.MM.YYYY
        m = re.search(r'(\d{2}[\-\.]\d{2}[\-\.]\d{4})', text)
        if m:
            d = m.group(1).replace("-","/").replace(".","/")
            try: return datetime.strptime(d, "%d/%m/%Y").strftime("%Y-%m-%d")
            except: pass
        return ""

# ══════════════════════════════════════════════════════
# SCRAPER AGENT
# ══════════════════════════════════════════════════════
class SLog:
    entries: list = []
    @classmethod
    def add(cls, msg):
        e = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
        cls.entries.append(e); logger.info(e)
        if len(cls.entries) > 600: cls.entries = cls.entries[-500:]
    @classmethod
    def last(cls, n=100): return cls.entries[-n:]

class SState:
    running = False; found = 0; saved = 0
    errors = 0; started = ""; current = 0; total = 0

class ScraperAgent:
    BASE = "https://www.marchespublics.gov.ma/bdc/entreprise/consultation"

    @staticmethod
    def _session():
        import requests
        s = requests.Session(); s.verify = False
        s.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
            "Accept-Language": "fr-FR,fr;q=0.9",
        })
        return s

    @staticmethod
    def _save(t: dict) -> bool:
        if not t or not t.get("id") or not t.get("objet"): return False
        try:
            db = get_db()
            db.execute("""INSERT OR IGNORE INTO tenders
                (id,objet,acheteur,region,domaine,type_marche,montant,
                 budget_min,budget_max,date_publication,date_limite,description,
                 statut,url,source,contact,ai_score,ai_category,ai_reason,date_extraction)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                str(t.get("id",""))[:80],         str(t.get("objet",""))[:400],
                str(t.get("acheteur",""))[:200],   str(t.get("region",""))[:100],
                str(t.get("domaine",""))[:80],     str(t.get("type_marche",""))[:40],
                str(t.get("montant",""))[:80],     float(t.get("budget_min",0) or 0),
                float(t.get("budget_max",0) or 0),str(t.get("date_publication",""))[:20],
                str(t.get("date_limite",""))[:20], str(t.get("description",""))[:2000],
                str(t.get("statut","actif")),      str(t.get("url",""))[:400],
                str(t.get("source","marchespublics")),
                str(t.get("contact",""))[:100],
                int(t.get("ai_score",50) or 50),
                str(t.get("ai_category",""))[:80],
                str(t.get("ai_reason",""))[:300],
                datetime.now().strftime("%Y-%m-%d %H:%M"),
            ))
            db.commit()
            changed = db.execute("SELECT changes()").fetchone()[0]
            db.close(); return changed > 0
        except Exception as e:
            logger.error(f"[save] {e}")
            try: db.close()
            except: pass
            return False

    @classmethod
    def _parse(cls, html: str, tid: str) -> Optional[dict]:
        try:
            from bs4 import BeautifulSoup as BS
            soup = BS(html, "html.parser")
            full = soup.get_text(" ", strip=True)

            # ── Cell lookup: cherche valeur dans tableau par label ──
            def cell(*labels):
                for row in soup.find_all("tr"):
                    tds = row.find_all(["td","th"])
                    if len(tds) < 2: continue
                    lbl = tds[0].get_text(strip=True).lower()
                    for label in labels:
                        if label.lower() in lbl:
                            val = " ".join(t.get_text(strip=True) for t in tds[1:])
                            if val.strip(): return val.strip()[:500]
                return ""

            # ── Labels OBJET du marché ──
            OBJET_LABELS = [
                "objet du marché","objet de la consultation","objet",
                "intitulé","désignation","nature des travaux",
                "nature des fournitures","nature des prestations","libellé",
            ]
            # ── Labels DATE LIMITE ──
            DATE_LABELS = [
                "date et heure limite de remise des devis",
                "date et heure limite de remise des offres",
                "date limite de remise des offres",
                "date limite de remise des devis",
                "date limite de réception des offres",
                "date limite de réception des devis",
                "date de remise des offres",
                "date de clôture des offres",
                "heure limite de remise",
                "date limite","heure limite","clôture",
            ]
            # Labels qui NE SONT PAS des objets
            NOT_OBJET = [
                "date","heure","limite","remise","réception","soumission",
                "dépôt","publication","ouverture","montant","budget",
                "maître","organisme","objet du marché :",
            ]

            # ══ 1. OBJET ══
            objet = ""

            # Priorité 1: cellule tableau "objet du marché"
            objet = cell(*OBJET_LABELS)

            # Priorité 2: CSS selectors
            if not objet:
                for sel in [".consultation-objet",".objet-marche",
                            "[class*='objet']","[class*='title']"]:
                    el = soup.select_one(sel)
                    if el:
                        t = el.get_text(strip=True)
                        if len(t) > 10 and not any(n in t.lower() for n in NOT_OBJET):
                            objet = t; break

            # Priorité 3: h1/h2 si pas un label de date
            if not objet:
                for tag in soup.find_all(["h1","h2","h3"])[:5]:
                    t = tag.get_text(strip=True)
                    if (10 < len(t) < 600 and
                        not any(n in t.lower() for n in NOT_OBJET) and
                        not any(n in t.lower() for n in ["accueil","connexion","portail","liste"])):
                        objet = t; break

            if not objet: return None
            objet = ClassifierAgent.clean_objet(objet)

            # Rejeter si objet ressemble à un label de date
            if any(lbl in objet.lower() for lbl in [
                "date et heure","date limite","heure limite",
                "remise des","réception des","clôture"]):
                return None

            # ══ 2. DATE LIMITE ══
            date_lim = ""

            # Chercher dans les cellules du tableau
            raw_dl = cell(*DATE_LABELS)
            if raw_dl:
                m = re.search(r'(\d{2}/\d{2}/\d{4})', raw_dl)
                if m: date_lim = ClassifierAgent.extract_date(m.group(1))

            # Fallback: chercher dans le texte complet
            if not date_lim:
                fl = full.lower()
                for lbl in DATE_LABELS:
                    idx = fl.find(lbl)
                    if idx < 0: continue
                    snippet = full[idx:idx+120]
                    m = re.search(r'(\d{2}/\d{2}/\d{4})', snippet)
                    if m:
                        date_lim = ClassifierAgent.extract_date(m.group(1))
                        break

            # ══ 3. Vérifier expiration ══
            if date_lim and ClassifierAgent.is_expired(date_lim):
                return None  # Ignorer directement

            # ══ 4. Autres champs ══
            acheteur = cell("maître d'ouvrage","maître d ouvrage",
                           "organisme","administration maître","entité").strip()
            date_pub  = ClassifierAgent.extract_date(
                cell("date de publication","date d'ouverture","publication") or "")
            mon_raw   = cell("montant estimé","montant","budget","estimation") or ""
            if not mon_raw:
                m = re.search(r'(\d[\d\s,.]+)\s*(?:DH|MAD)', full, re.I)
                if m: mon_raw = m.group(0)[:80]

            # ══ 5. Log avec date ══
            dl_log = date_lim or "?"
            SLog.add(f"✓ #{tid} │ {ClassifierAgent.secteur(objet)[:4]} │ {objet[:45]} │ ⏰{dl_log}")

            return {
                "id":               f"bdc_{tid}",
                "objet":            objet[:400],
                "acheteur":         acheteur[:200],
                "region":           ClassifierAgent.region(acheteur+" "+full[:400]),
                "domaine":          ClassifierAgent.secteur(objet+" "+full[:300]),
                "type_marche":      ClassifierAgent.type_marche(objet),
                "montant":          mon_raw[:80],
                "date_publication": date_pub,
                "date_limite":      date_lim,
                "description":      full[:2000],
                "statut":           "annule" if "annulé" in full.lower() else "actif",
                "url":              f"{cls.BASE}/show/{tid}",
                "source":           "marchespublics",
            }
        except Exception as e:
            logger.error(f"[parse #{tid}] {e}")
            return None

    @classmethod
    @classmethod
    def run(cls) -> list:
        """Scan séquentiel des IDs — contourne le JS du portail"""
        import random as rnd
        t_start = time.time()
        new_tenders: list = []
        SState.running = True
        SState.found = SState.saved = SState.errors = 0
        SState.started = datetime.now().strftime("%H:%M:%S")
        SState.current = SState.total = 0
        SLog.add("═══ ScraperAgent v6 (20260321_143549) — scan séquentiel marchespublics ═══")

        db = get_db()
        known = set(r[0] for r in db.execute("SELECT id FROM tenders").fetchall())
        db.close()

        # Trouver le plus grand ID bdc_XXXXX connu
        max_id = 310000  # minimum absolu
        for k in known:
            if k.startswith("bdc_"):
                try:
                    n = int(k[4:])
                    if n > max_id: max_id = n
                except: pass

        # Si aucun ID connu récent, commencer à 312000+
        if max_id < 311000:
            max_id = 312000

        # Scan: 30 en arrière (rattrapage) + 500 en avant (nouveaux)
        start_id = max(max_id - 30, 310000)
        end_id   = max_id + 500
        scan_ids = [str(i) for i in range(start_id, end_id + 1)
                    if f"bdc_{i}" not in known]
        SLog.add(f"Max connu: #{max_id} | Scan #{start_id}→#{end_id} ({len(scan_ids)} IDs)")

        SState.total = len(scan_ids)
        SLog.add(f"Max connu: #{max_id} | Scan #{start_id}→#{end_id} ({len(scan_ids)} IDs)")

        s = cls._session()
        consec_errors = 0

        for idx, tid in enumerate(scan_ids):
            SState.current = idx + 1
            try:
                r = s.get(f"{cls.BASE}/show/{tid}", timeout=15)
                if r.status_code != 200 or len(r.text) < 2000:
                    consec_errors += 1
                    if consec_errors > 30 and SState.saved == 0:
                        SLog.add(f"Trop d'erreurs ({consec_errors}), arrêt")
                        break
                    continue
                consec_errors = 0
                SState.found += 1
                t = cls._parse(r.text, tid)
                if not t:
                    known.add(f"bdc_{tid}"); continue
                if t.get("statut") == "annule":
                    SLog.add(f"  ↳ annulé #{tid} — ignoré")
                    known.add(f"bdc_{tid}"); continue
                if cls._save(t):
                    SState.saved += 1
                    known.add(t["id"])
                    SLog.add(f"✓ #{tid} [{t.get('domaine','')[:18]}] {t.get('objet','')[:52]} [{t.get('statut','?')}]")
                    if t.get("statut") == "actif": new_tenders.append(t)
                else:
                    known.add(f"bdc_{tid}")
                time.sleep(rnd.uniform(0.5, 1.1))
            except Exception as e:
                SState.errors += 1; consec_errors += 1
                SLog.add(f"✗ #{tid}: {str(e)[:55]}")

        # Auto-expire tenders passés
        try:
            db = get_db()
            active = db.execute("SELECT id,date_limite FROM tenders WHERE statut='actif' AND date_limite!=''").fetchall()
            expired = [r["id"] for r in active if ClassifierAgent.is_expired(r["date_limite"])]
            if expired:
                db.execute(f"UPDATE tenders SET statut='expire' WHERE id IN ({','.join('?'*len(expired))})", expired)
            db.commit(); db.close()
        except: pass

        duration = time.time() - t_start
        try:
            db = get_db()
            db.execute("INSERT INTO scrape_runs (source,found,saved,errors,duration_sec,started_at,finished_at) VALUES (?,?,?,?,?,?,?)",
                       ("marchespublics",SState.found,SState.saved,SState.errors,duration,SState.started,datetime.now().strftime("%H:%M:%S")))
            db.commit(); db.close()
        except: pass
        SState.running = False
        SLog.add(f"═══ Terminé en {duration:.0f}s | {SState.saved} sauvegardés | {SState.errors} erreurs ═══")
        counter("scrape_runs"); return new_tenders
        counter("scrape_runs"); return new_tenders

# ══════════════════════════════════════════════════════
# NOTIFICATION AGENT
# ══════════════════════════════════════════════════════
class NotifyAgent:
    @staticmethod
    def enqueue(member_id, channel, recipient, subject, body):
        try:
            db = get_db()
            db.execute("INSERT INTO notif_queue (member_id,channel,recipient,subject,body,status,created_at) VALUES (?,?,?,?,?,'pending',?)",
                       (member_id,channel,recipient,subject,body,now_str()))
            db.commit(); db.close()
        except Exception as e: logger.error(f"[enqueue] {e}")

    @staticmethod
    def get_pending() -> list:
        try:
            db = get_db()
            rows = [dict(r) for r in db.execute(
                "SELECT * FROM notif_queue WHERE status='pending' AND attempts < 3 ORDER BY id LIMIT 20"
            ).fetchall()]
            db.close(); return rows
        except: return []

    @staticmethod
    def mark(nid: int, status: str, error: str=""):
        try:
            db = get_db()
            if status == "sent":
                db.execute("UPDATE notif_queue SET status='sent',sent_at=? WHERE id=?", (now_str(),nid))
            else:
                db.execute("UPDATE notif_queue SET status=?,attempts=attempts+1,error=? WHERE id=?",
                           (status,error[:200],nid))
            db.commit(); db.close()
        except: pass

    @staticmethod
    async def send_email(to, subject, html) -> tuple:
        # Method 1: Brevo API (HTTP, no SMTP, works on Railway)
        if BREVO_KEY:
            try:
                import httpx
                async with httpx.AsyncClient(timeout=20) as client:
                    r = await client.post("https://api.brevo.com/v3/smtp/email",
                        headers={"api-key":BREVO_KEY,"Content-Type":"application/json"},
                        json={"sender":{"name":BRAND,"email":GMAIL_USER},
                              "to":[{"email":to}],"subject":subject,"htmlContent":html})
                    if r.status_code in [200,201,202]:
                        counter("emails_sent"); return True, ""
                    logger.error(f"[brevo] {r.status_code}: {r.text[:100]}")
            except Exception as e: logger.error(f"[brevo] {e}")
        # Method 2: Resend
        if RESEND_KEY:
            try:
                import httpx
                async with httpx.AsyncClient(timeout=20) as client:
                    r = await client.post("https://api.resend.com/emails",
                        headers={"Authorization":f"Bearer {RESEND_KEY}","Content-Type":"application/json"},
                        json={"from":f"{BRAND} <onboarding@resend.dev>","to":[to],"subject":subject,"html":html})
                    if r.status_code in [200,201]:
                        counter("emails_sent"); return True, ""
            except Exception as e: logger.error(f"[resend] {e}")
        # Method 3: SMTP (blocked on Railway free)
        if GMAIL_PASS:
            try:
                msg = MIMEMultipart("alternative")
                msg["Subject"] = subject; msg["From"] = f"{BRAND} <{GMAIL_USER}>"; msg["To"] = to
                msg.attach(MIMEText(html, "html", "utf-8"))
                def _smtp():
                    for host,port,ssl in [("smtp.gmail.com",465,True),("smtp.gmail.com",587,False)]:
                        try:
                            srv = smtplib.SMTP_SSL(host,port,timeout=20) if ssl else smtplib.SMTP(host,port,timeout=20)
                            if not ssl: srv.ehlo(); srv.starttls(); srv.ehlo()
                            srv.login(GMAIL_USER, GMAIL_PASS)
                            srv.sendmail(GMAIL_USER,[to],msg.as_string()); srv.quit(); return True,""
                        except smtplib.SMTPAuthenticationError: return False,"Gmail App Password requis"
                        except: continue
                    return False,"SMTP bloqué (Railway)"
                loop = asyncio.get_event_loop()
                ok, err = await loop.run_in_executor(None, _smtp)
                if ok: counter("emails_sent")
                return ok, err
            except Exception as e: return False, str(e)
        return False, "Aucune méthode email configurée"

    @staticmethod
    async def send_telegram(chat_id, text) -> tuple:
        try:
            import httpx
            MAX = 3800
            parts = [text[i:i+MAX] for i in range(0, len(text), MAX)] if len(text) > MAX else [text]
            async with httpx.AsyncClient(timeout=15) as client:
                for part in parts:
                    r = await client.post(
                        f"https://api.telegram.org/bot{TELEGRAM_BOT}/sendMessage",
                        json={"chat_id":chat_id,"text":part,"parse_mode":"HTML","disable_web_page_preview":True}
                    )
                    data = r.json()
                    if not data.get("ok"):
                        return False, data.get("description","error")
                    await asyncio.sleep(0.3)
            counter("tg_sent"); return True, ""
        except Exception as e: return False, str(e)

    @staticmethod
    async def worker():
        logger.info("[NotifyAgent] Worker started")
        while True:
            try:
                for n in NotifyAgent.get_pending():
                    try:
                        if n["channel"] == "email":
                            ok, err = await NotifyAgent.send_email(n["recipient"],n["subject"],n["body"])
                        elif n["channel"] == "telegram":
                            ok, err = await NotifyAgent.send_telegram(n["recipient"],n["body"])
                        else:
                            ok, err = False, f"Unknown: {n['channel']}"
                        if ok:
                            NotifyAgent.mark(n["id"],"sent")
                            logger.info(f"[NotifyAgent] ✅ {n['channel']}→{n['recipient'][:20]}")
                        else:
                            status = "failed" if n["attempts"] >= 2 else "pending"
                            # Fast-fail SMTP network errors
                            if "Network is unreachable" in err or "SMTP bloqué" in err:
                                status = "failed"
                            NotifyAgent.mark(n["id"],status,err)
                        await asyncio.sleep(0.5)
                    except Exception as e:
                        NotifyAgent.mark(n["id"],"pending",str(e))
            except Exception as e:
                logger.error(f"[NotifyAgent:worker] {e}")
            await asyncio.sleep(5)

    @staticmethod
    def build_email(tenders: list, title: str) -> str:
        # ── Dédupliquer ──
        seen_obj = set(); uniq_t = []
        for t in tenders:
            key = (t.get("objet","")[:60]).strip().lower()
            if key not in seen_obj:
                seen_obj.add(key); uniq_t.append(t)
        tenders = uniq_t

        def card(t):
            dl   = t.get("date_limite","—") or "—"
            days = NotifyAgent.days_left(dl)
            sc   = t.get("ai_score",0) or 0
            sc_color = "#5a9e78" if sc>=70 else "#c9a84c" if sc>=40 else "#9e4a4a"
            mon  = f'<tr><td style="color:#888;font-size:11px;padding:3px 0;width:130px">💰 Montant</td><td style="color:#c9a84c;font-size:11px;font-weight:700">{t.get("montant","")}</td></tr>' if t.get("montant") else ""
            days_html = f' <span style="color:#e87070;font-size:10px">({days})</span>' if days else ""
            score_html = f'<div style="display:inline-block;background:{sc_color}22;border:1px solid {sc_color}44;border-radius:99px;padding:2px 8px;font-size:9px;color:{sc_color};font-weight:700;margin-top:8px">Score IA: {sc}/100</div>' if sc else ""
            link = t.get("url") or f"{SITE_URL}/tenders/{t.get('id','')}"
            return f"""<div style="border:1px solid #2a2a2a;border-radius:8px;padding:16px;margin-bottom:12px;background:#141414">
  <div style="font-size:14px;font-weight:700;color:#f0ede6;margin-bottom:10px;line-height:1.35">{(t.get("objet") or "")[:100]}</div>
  {score_html}
  <table style="width:100%;border-collapse:collapse;margin-top:10px">
    <tr><td style="color:#888;font-size:11px;padding:3px 0;width:130px">🏢 Acheteur</td><td style="color:#aaa;font-size:11px">{(t.get("acheteur") or "—")[:60]}</td></tr>
    <tr><td style="color:#888;font-size:11px;padding:3px 0">📍 Région</td><td style="color:#aaa;font-size:11px">{t.get("region","—")}</td></tr>
    <tr><td style="color:#888;font-size:11px;padding:3px 0">🏷 Secteur</td><td style="color:#aaa;font-size:11px">{t.get("domaine","—")}</td></tr>
    {mon}
    <tr><td style="color:#888;font-size:11px;padding:3px 0">⏰ Limite</td><td style="color:#e87070;font-size:11px;font-weight:700">{dl}{days_html}</td></tr>
  </table>
  <a href="{link}" style="display:inline-block;margin-top:12px;padding:7px 16px;background:#c9a84c;color:#000;border-radius:5px;font-weight:700;text-decoration:none;font-size:12px">Voir le marché →</a>
</div>"""
        cards = "".join(card(t) for t in tenders[:12])
        return f"""<!DOCTYPE html><html><head><meta charset="utf-8"></head>
<body style="margin:0;padding:20px;background:#080808;font-family:Georgia,serif">
<div style="max-width:640px;margin:0 auto;background:#0d0d0d;border-radius:12px;padding:32px">
  <div style="border-bottom:2px solid #c9a84c;padding-bottom:16px;margin-bottom:22px">
    <div style="font-size:20px;font-weight:700;color:#c9a84c">◆ Modern Business</div>
    <div style="font-size:11px;color:#555;margin-top:4px">{datetime.now().strftime("%d/%m/%Y à %H:%M")}</div>
  </div>
  <div style="font-size:17px;font-weight:700;color:#f0ede6;margin-bottom:6px">{title}</div>
  <div style="font-size:12px;color:#666;margin-bottom:22px">marchespublics.gov.ma + sources officielles</div>
  {cards}
  <div style="border-top:1px solid #222;padding-top:18px;margin-top:8px;text-align:center">
    <a href="{SITE_URL}" style="padding:10px 24px;background:#c9a84c;color:#000;border-radius:6px;font-weight:700;text-decoration:none;font-size:13px">Accéder à la plateforme →</a>
    <div style="font-size:10px;color:#333;margin-top:12px">Modern Business · <a href="{SITE_URL}/contact" style="color:#555">Se désinscrire</a></div>
  </div>
</div></body></html>"""

    @staticmethod
    def days_left(dl: str) -> str:
        """Retourne '3 jours' ou 'Aujourd\'hui' ou '' """
        if not dl: return ""
        import re as _re
        m = _re.search(r'(\d{2}/\d{2}/\d{4}|\d{4}-\d{2}-\d{2})', str(dl))
        if not m: return ""
        try:
            fmt = "%d/%m/%Y" if "/" in m.group(1) else "%Y-%m-%d"
            d = datetime.strptime(m.group(1), fmt).date()
            delta = (d - datetime.now().date()).days
            if delta < 0:  return "⚠️ Expiré"
            if delta == 0: return "⚡ Aujourd\'hui !"
            if delta == 1: return "⚡ Demain !"
            if delta <= 3: return f"🔥 {delta} jours"
            if delta <= 7: return f"⏳ {delta} jours"
            return f"📅 {delta} jours"
        except: return ""

    @staticmethod
    def build_telegram(tenders: list, header: str) -> str:
        from collections import OrderedDict
        # ── Dédupliquer par objet (premiers 60 chars) ──
        seen_obj = set(); uniq = []
        for t in tenders:
            key = (t.get("objet","")[:60]).strip().lower()
            if key not in seen_obj:
                seen_obj.add(key); uniq.append(t)
        tenders = uniq

        lines = [f"🏛 <b>{header}</b>\n{chr(9472)*28}\n"]
        for t in tenders[:8]:
            dl   = t.get("date_limite","")
            days = NotifyAgent.days_left(dl)
            sc   = t.get("ai_score",0) or 0
            score_ic = "⭐" if sc>=70 else "◑" if sc>=40 else "○"

            b = f"{score_ic} <b>{(t.get('objet') or '')[:70]}</b>\n"
            if t.get("acheteur"):  b += f"   🏢 {t['acheteur'][:50]}\n"
            if t.get("region"):    b += f"   📍 {t['region']}\n"
            if t.get("domaine"):   b += f"   🏷 {t['domaine'][:30]}\n"
            if t.get("montant"):   b += f"   💰 {t['montant']}\n"
            if dl:
                b += f"   ⏰ <b>Limite: {dl}"
                if days: b += f" — {days}"
                b += "</b>\n"
            if sc:                 b += f"   📊 Score: {sc}/100\n"
            b += f"   🔗 {t.get('url') or SITE_URL+'/tenders/'+str(t.get('id',''))}\n"
            lines.append(b)
        lines.append(f"\n🌐 {SITE_URL}/tenders")
        return "\n\n".join(lines)

    @staticmethod
    def match_tenders(tenders, member_id, secteur=""):
        """
        Filtre les marchés selon les préférences du membre.
        Logique:
          1. Lit les filtres DB (secteur/region/keyword)
          2. Ajoute le secteur du profil membre comme fallback
          3. Si AUCUN filtre → envoie TOUT (membre sans préférences)
          4. Si filtres définis → envoie UNIQUEMENT les marchés correspondants
          5. Jamais de fallback "envoyer quand même" — zéro = zéro
        """
        # ── 1. Charger filtres DB ──
        try:
            db = get_db()
            rows = db.execute(
                "SELECT type,value FROM member_filters WHERE member_id=?", (member_id,)
            ).fetchall()
            db.close()
            filters = [dict(r) for r in rows]
        except:
            filters = []

        sect_f   = {r["value"] for r in filters if r["type"] == "secteur"}
        region_f = {r["value"] for r in filters if r["type"] == "region"}
        kw_f     = {r["value"].lower() for r in filters if r["type"] == "keyword"}

        # ── 2. Fallback: secteur du profil membre ──
        if not sect_f and secteur and secteur.strip():
            sect_f = {secteur.strip()}

        # ── 3. Aucun filtre → reçoit tout ──
        if not sect_f and not region_f and not kw_f:
            return tenders

        # ── 4. Filtrage strict ──
        matched = []
        for t in tenders:
            dom  = (t.get("domaine") or "").lower().strip()
            reg  = (t.get("region")  or "").lower().strip()
            obj  = (t.get("objet")   or "").lower()
            desc = (t.get("description") or "").lower()[:300]
            full = obj + " " + dom + " " + desc

            # Keyword match (OR logic — un seul suffit)
            if kw_f:
                if any(kw in full for kw in kw_f):
                    matched.append(t); continue

            # Region match
            if region_f:
                if any(rf.lower() in reg or reg in rf.lower() for rf in region_f):
                    matched.append(t); continue

            # Secteur match — comparaison précise par code T/P/S
            if sect_f:
                added = False
                for s in sect_f:
                    s_code = s[:4].upper()   # ex: "T101"
                    d_code = dom[:4].upper()  # ex: "t101" → "T101"

                    # Match exact du code
                    if s_code == d_code:
                        matched.append(t); added = True; break

                    # Match partiel: même lettre (T=T, P=P, S=S)
                    if s_code and d_code and s_code[0] == d_code[0]:
                        # Vérifier par mots-clés du secteur
                        if s in SECTEURS:
                            kws = SECTEURS[s]
                            if any(kw in full for kw in kws):
                                matched.append(t); added = True; break
                        # Sinon match sur le code complet
                        elif s_code in d_code or d_code in s_code:
                            matched.append(t); added = True; break

                    if added: break

        # ── 5. Retourner uniquement les matches — jamais de fallback ──
        return matched

    @staticmethod
    def notify_instant(tenders: list):
        if not tenders: return
        db = get_db()
        try:
            subs = [dict(r) for r in db.execute(
                "SELECT id,nom,email,telegram,secteur,notif_email,notif_tg FROM members WHERE actif=1"
            ).fetchall()]
        finally: db.close()
        if not subs: SLog.add("[NotifyAgent] Aucun abonné"); return
        eq = tq = skipped = 0
        n = len(tenders)
        for sub in subs:
            sect = sub.get("secteur","").strip()
            matched = NotifyAgent.match_tenders(tenders, sub["id"], sect)

            if not matched:
                skipped += 1
                SLog.add(f"[NotifyAgent] {sub['nom']}: 0 match [{sect or 'aucun filtre défini'}]")
                continue

            sect_lbl = sect or "tous secteurs"
            nm = len(matched)
            SLog.add(f"[NotifyAgent] {sub['nom']} [{sect_lbl}]: {nm}/{n} marchés correspondants")

            subj = f"🏛 {nm} marché(s) [{sect_lbl}] — {datetime.now().strftime('%d/%m/%Y')} — Modern Business"
            email_html = NotifyAgent.build_email(matched, f"🏛 {nm} marché(s) — {sect_lbl}")
            tg_body    = NotifyAgent.build_telegram(matched, f"{nm} marché(s) [{sect_lbl}]")

            if sub.get("notif_email",1) and sub.get("email"):
                NotifyAgent.enqueue(sub["id"],"email",sub["email"],subj,email_html)
                eq += 1
            if sub.get("notif_tg",1) and sub.get("telegram"):
                NotifyAgent.enqueue(sub["id"],"telegram",sub["telegram"],"",tg_body)
                tq += 1

        SLog.add(f"[NotifyAgent] {eq} emails + {tq} TG en file | {skipped} membres sans match")
        counter("notifications_queued")

    @staticmethod
    def notify_digest():
        db = get_db()
        try:
            yesterday = (datetime.now()-timedelta(days=1)).strftime("%Y-%m-%d")
            tenders = [dict(r) for r in db.execute(
                "SELECT * FROM tenders WHERE date_extraction>=? AND statut='actif' ORDER BY ai_score DESC, date_extraction DESC",
                (yesterday,)).fetchall()]
            subs = [dict(r) for r in db.execute(
                "SELECT id,email,telegram,secteur,notif_email,notif_tg FROM members WHERE actif=1"
            ).fetchall()]
        finally: db.close()
        if not tenders: logger.info("[NotifyAgent:digest] Aucun marché"); return
        ds = datetime.now().strftime("%d/%m/%Y")
        for sub in subs:
            matched = NotifyAgent.match_tenders(tenders, sub["id"], sub.get("secteur",""))
            if not matched: continue
            n = len(matched)
            sl = sub.get("secteur") or "tous secteurs"
            subj = f"📋 Résumé {ds} — {n} marché(s) [{sl}] — Modern Business"
            if sub.get("notif_email",1) and sub.get("email"):
                NotifyAgent.enqueue(sub["id"],"email",sub["email"],subj,NotifyAgent.build_email(matched,f"Résumé {ds} — {n} marché(s) [{sl}]"))
            if sub.get("notif_tg",1) and sub.get("telegram"):
                NotifyAgent.enqueue(sub["id"],"telegram",sub["telegram"],"",NotifyAgent.build_telegram(matched,f"Résumé {ds} — {n} marché(s) [{sl}]"))
        logger.info(f"[NotifyAgent:digest] {len(subs)} abonnés notifiés")

    @staticmethod
    def notify_weekly_digest():
        """Weekly top 10 easy-to-win tenders every Monday"""
        db = get_db()
        try:
            tenders = [dict(r) for r in db.execute(
                "SELECT * FROM tenders WHERE statut='actif' AND ai_score>=70 "
                "ORDER BY ai_score DESC LIMIT 10"
            ).fetchall()]
            subs = [dict(r) for r in db.execute(
                "SELECT id,email,telegram,secteur,notif_email,notif_tg,plan FROM members WHERE actif=1"
            ).fetchall()]
        finally: db.close()
        if not tenders: return
        week = datetime.now().strftime("Semaine du %d/%m/%Y")
        for sub in subs:
            # Only pro users get weekly digest
            if sub.get("plan","free") not in ["pro","enterprise"]: continue
            matched = NotifyAgent.match_tenders(tenders, sub["id"], sub.get("secteur",""))
            if not matched: matched = tenders[:5]
            subj = f"📊 Top marchés semaine — {week} — Modern Business"
            if sub.get("notif_email",1) and sub.get("email"):
                NotifyAgent.enqueue(sub["id"],"email",sub["email"],subj,
                    NotifyAgent.build_email(matched,f"🏆 Top {len(matched)} marchés faciles — {week}"))
            if sub.get("notif_tg",1) and sub.get("telegram"):
                NotifyAgent.enqueue(sub["id"],"telegram",sub["telegram"],"",
                    NotifyAgent.build_telegram(matched,f"Top {len(matched)} marchés — {week}"))
        logger.info(f"[NotifyAgent:weekly] Digest hebdo envoyé")

# ══════════════════════════════════════════════════════
# MONITOR AGENT
# ══════════════════════════════════════════════════════


# ════════════════════════════════════════════════════════════════
# SELF-HEALING AGENT — Intelligent Auto-Repair System
# Comprend le projet Modern Business et corrige les erreurs
# automatiquement sans intervention humaine
# ════════════════════════════════════════════════════════════════

class SelfHealingAgent:
    """
    Agent IA de correction automatique pour Modern Business.
    
    Fonctions:
    - Surveille les erreurs en continu (toutes les 10 minutes)
    - Comprend le schéma DB et répare les tables manquantes
    - Détecte les colonnes manquantes et les ajoute
    - Revalide les routes critiques (health check)
    - Nettoie la DB: expire les marchés passés, purge les queues
    - Réinitialise les scrapers bloqués
    - Notifie l'admin via Telegram des actions prises
    - Log toutes les réparations dans agent_repairs table
    """

    # Schéma complet de la base de données
    SCHEMA = {
        "tenders": {
            "id":              "TEXT PRIMARY KEY",
            "objet":           "TEXT NOT NULL DEFAULT ''",
            "acheteur":        "TEXT DEFAULT ''",
            "region":          "TEXT DEFAULT ''",
            "domaine":         "TEXT DEFAULT ''",
            "type_marche":     "TEXT DEFAULT ''",
            "montant":         "TEXT DEFAULT ''",
            "budget_min":      "REAL DEFAULT 0",
            "budget_max":      "REAL DEFAULT 0",
            "date_publication":"TEXT DEFAULT ''",
            "date_limite":     "TEXT DEFAULT ''",
            "description":     "TEXT DEFAULT ''",
            "statut":          "TEXT DEFAULT 'actif'",
            "url":             "TEXT DEFAULT ''",
            "source":          "TEXT DEFAULT 'marchespublics'",
            "contact":         "TEXT DEFAULT ''",
            "ai_score":        "INTEGER DEFAULT 50",
            "ai_category":     "TEXT DEFAULT ''",
            "ai_reason":       "TEXT DEFAULT ''",
            "date_extraction": "TEXT DEFAULT ''",
            "views":           "INTEGER DEFAULT 0",
        },
        "members": {
            "id":           "INTEGER PRIMARY KEY AUTOINCREMENT",
            "nom":          "TEXT DEFAULT ''",
            "entreprise":   "TEXT DEFAULT ''",
            "email":        "TEXT UNIQUE NOT NULL",
            "phone":        "TEXT DEFAULT ''",
            "secteur":      "TEXT DEFAULT ''",
            "ville":        "TEXT DEFAULT ''",
            "region":       "TEXT DEFAULT ''",
            "pw_hash":      "TEXT DEFAULT ''",
            "plan":         "TEXT DEFAULT 'free'",
            "actif":        "INTEGER DEFAULT 0",
            "verify_token": "TEXT DEFAULT ''",
            "telegram":     "TEXT DEFAULT ''",
            "last_login":   "TEXT DEFAULT ''",
            "created_at":   "TEXT DEFAULT ''",
            "notif_email":  "INTEGER DEFAULT 1",
            "notif_tg":     "INTEGER DEFAULT 1",
        },
        "member_filters": {
            "id":         "INTEGER PRIMARY KEY AUTOINCREMENT",
            "member_id":  "INTEGER NOT NULL",
            "type":       "TEXT DEFAULT 'secteur'",
            "value":      "TEXT DEFAULT ''",
            "created_at": "TEXT DEFAULT ''",
        },
        "favoris": {
            "id":         "INTEGER PRIMARY KEY AUTOINCREMENT",
            "member_id":  "INTEGER NOT NULL",
            "tender_id":  "TEXT NOT NULL",
            "created_at": "TEXT DEFAULT ''",
        },
        "api_keys": {
            "id":         "INTEGER PRIMARY KEY AUTOINCREMENT",
            "member_id":  "INTEGER NOT NULL",
            "key":        "TEXT UNIQUE NOT NULL",
            "name":       "TEXT DEFAULT 'API Key'",
            "created_at": "TEXT DEFAULT ''",
            "last_used":  "TEXT DEFAULT ''",
            "active":     "INTEGER DEFAULT 1",
        },
        "posts": {
            "id":           "INTEGER PRIMARY KEY AUTOINCREMENT",
            "titre":        "TEXT NOT NULL DEFAULT ''",
            "contenu":      "TEXT DEFAULT ''",
            "type_post":    "TEXT DEFAULT 'offre'",
            "secteur":      "TEXT DEFAULT ''",
            "region":       "TEXT DEFAULT ''",
            "contact":      "TEXT DEFAULT ''",
            "auteur_email": "TEXT DEFAULT ''",
            "statut":       "TEXT DEFAULT 'actif'",
            "views":        "INTEGER DEFAULT 0",
            "created_at":   "TEXT DEFAULT ''",
        },
        "chats": {
            "id":         "INTEGER PRIMARY KEY AUTOINCREMENT",
            "member_id":  "INTEGER DEFAULT 0",
            "role":       "TEXT DEFAULT 'user'",
            "content":    "TEXT DEFAULT ''",
            "created_at": "TEXT DEFAULT ''",
        },
        "notif_queue": {
            "id":          "INTEGER PRIMARY KEY AUTOINCREMENT",
            "member_id":   "INTEGER NOT NULL",
            "tender_ids":  "TEXT DEFAULT ''",
            "channel":     "TEXT DEFAULT 'email'",
            "status":      "TEXT DEFAULT 'pending'",
            "attempts":    "INTEGER DEFAULT 0",
            "created_at":  "TEXT DEFAULT ''",
            "sent_at":     "TEXT DEFAULT ''",
        },
        "scrape_runs": {
            "id":          "INTEGER PRIMARY KEY AUTOINCREMENT",
            "source":      "TEXT DEFAULT ''",
            "found":       "INTEGER DEFAULT 0",
            "saved":       "INTEGER DEFAULT 0",
            "errors":      "INTEGER DEFAULT 0",
            "duration_s":  "REAL DEFAULT 0",
            "run_at":      "TEXT DEFAULT ''",
        },
        "agent_errors": {
            "id":          "INTEGER PRIMARY KEY AUTOINCREMENT",
            "agent":       "TEXT DEFAULT ''",
            "context":     "TEXT DEFAULT ''",
            "error":       "TEXT DEFAULT ''",
            "count":       "INTEGER DEFAULT 1",
            "resolved":    "INTEGER DEFAULT 0",
            "first_seen":  "TEXT DEFAULT ''",
            "last_seen":   "TEXT DEFAULT ''",
        },
        "agent_repairs": {
            "id":          "INTEGER PRIMARY KEY AUTOINCREMENT",
            "action":      "TEXT DEFAULT ''",
            "detail":      "TEXT DEFAULT ''",
            "success":     "INTEGER DEFAULT 1",
            "repaired_at": "TEXT DEFAULT ''",
        },
        "ratings": {
            "id":          "INTEGER PRIMARY KEY AUTOINCREMENT",
            "post_id":     "INTEGER NOT NULL",
            "member_id":   "INTEGER NOT NULL",
            "score":       "INTEGER DEFAULT 5",
            "created_at":  "TEXT DEFAULT ''",
        },
    }

    # Routes critiques à surveiller
    CRITICAL_ROUTES = ["/health", "/", "/tenders", "/login", "/register"]

    # Sources de scraping et leur statut attendu
    SCRAPER_SOURCES = [
        "marchespublics", "ofppt", "tanmia", "lematin",
        "leconomiste", "lavieeco", "flasheconomie",
    ]

    @classmethod
    def log_repair(cls, db, action: str, detail: str, success: bool = True):
        """Log une réparation dans la DB"""
        try:
            db.execute(
                "INSERT INTO agent_repairs(action,detail,success,repaired_at) VALUES(?,?,?,?)",
                (action, detail[:500], 1 if success else 0, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            )
            db.commit()
        except: pass

    @classmethod
    def notify_admin(cls, msg: str):
        """Notifie l'admin via Telegram"""
        if not TELEGRAM_BOT or not ADMIN_CHAT_ID: return
        try:
            import requests as _r
            _r.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT}/sendMessage",
                json={"chat_id": ADMIN_CHAT_ID,
                      "text": f"🔧 <b>SelfHealingAgent</b>\n{msg}",
                      "parse_mode": "HTML"},
                timeout=5
            )
        except: pass

    @classmethod
    def repair_schema(cls, db) -> list:
        """Vérifie et répare le schéma DB — crée tables et colonnes manquantes"""
        repairs = []
        for table, columns in cls.SCHEMA.items():
            # Créer la table si elle n'existe pas
            col_defs = ", ".join(f"{col} {typ}" for col, typ in columns.items())
            try:
                db.execute(f"CREATE TABLE IF NOT EXISTS {table} ({col_defs})")
                db.commit()
            except Exception as e:
                repairs.append(f"❌ Table {table}: {e}")
                continue

            # Vérifier colonnes manquantes
            try:
                existing = {row[1] for row in db.execute(f"PRAGMA table_info({table})").fetchall()}
                for col, typ in columns.items():
                    if col not in existing and col not in ("id",):
                        try:
                            default = typ.split("DEFAULT")[-1].strip() if "DEFAULT" in typ else "NULL"
                            db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
                            db.commit()
                            repairs.append(f"✅ Colonne ajoutée: {table}.{col}")
                        except Exception as e:
                            if "duplicate" not in str(e).lower():
                                repairs.append(f"⚠️ {table}.{col}: {e}")
            except Exception as e:
                repairs.append(f"❌ PRAGMA {table}: {e}")

        # Index critiques
        indexes = [
            ("idx_t_statut",     "tenders(statut)"),
            ("idx_t_score",      "tenders(ai_score DESC)"),
            ("idx_t_date",       "tenders(date_extraction DESC)"),
            ("idx_t_dl",         "tenders(date_limite)"),
            ("idx_m_email",      "members(email)"),
            ("idx_fav_member",   "favoris(member_id)"),
            ("idx_filters_mem",  "member_filters(member_id)"),
        ]
        for idx_name, idx_on in indexes:
            try:
                db.execute(f"CREATE INDEX IF NOT EXISTS {idx_name} ON {idx_on}")
                db.commit()
            except: pass

        return repairs

    @classmethod
    def expire_tenders(cls, db) -> int:
        """Expire les marchés dont la date limite est passée"""
        today = datetime.now().date()
        expired_ids = []

        # Format ISO: YYYY-MM-DD
        db.execute(
            "UPDATE tenders SET statut='expire' WHERE statut='actif' "
            "AND date_limite!='' AND date_limite NOT LIKE '%/%' "
            "AND date_limite < date('now') AND date_limite NOT IN ('N/A','—','-')"
        )

        # Format DD/MM/YYYY — traitement Python
        rows = db.execute(
            "SELECT id, date_limite FROM tenders WHERE statut='actif' "
            "AND date_limite LIKE '%/%' AND date_limite != ''"
        ).fetchall()

        import re as _re
        for row in rows:
            dl = str(row["date_limite"]).strip()
            m = _re.search(r'(\d{2}/\d{2}/\d{4})', dl)
            if m:
                try:
                    d = datetime.strptime(m.group(1), "%d/%m/%Y").date()
                    if d < today:
                        expired_ids.append(row["id"])
                except: pass

        if expired_ids:
            ph = ",".join(["?"] * len(expired_ids))
            db.execute(f"UPDATE tenders SET statut='expire' WHERE id IN ({ph})", expired_ids)

        db.commit()
        return len(expired_ids)

    @classmethod
    def clean_db(cls, db) -> dict:
        """Nettoie la DB: purge anciens chats, notifs envoyées, doublons"""
        stats = {}

        # Purge chats > 7 jours
        db.execute("DELETE FROM chats WHERE created_at < date('now','-7 days')")
        stats["chats_purged"] = db.execute("SELECT changes()").fetchone()[0]

        # Purge notifs envoyées > 30 jours
        db.execute("DELETE FROM notif_queue WHERE status='sent' AND sent_at < date('now','-30 days')")
        stats["notifs_purged"] = db.execute("SELECT changes()").fetchone()[0]

        # Reset notifs failed > 2h (retry)
        db.execute(
            "UPDATE notif_queue SET status='pending',attempts=0 "
            "WHERE status='failed' AND created_at < datetime('now','-2 hours') AND attempts < 3"
        )
        stats["notifs_reset"] = db.execute("SELECT changes()").fetchone()[0]

        # Résoudre erreurs agent > 7 jours
        db.execute("UPDATE agent_errors SET resolved=1 WHERE last_seen < date('now','-7 days')")

        # Supprimer doublons de tenders (même objet, même source, même jour)
        db.execute("""
            DELETE FROM tenders WHERE rowid NOT IN (
                SELECT MIN(rowid) FROM tenders
                GROUP BY LOWER(SUBSTR(objet,1,60)), source, SUBSTR(date_extraction,1,10)
            )
        """)
        stats["dupes_removed"] = db.execute("SELECT changes()").fetchone()[0]

        db.commit()
        return stats

    @classmethod
    def check_scraper_health(cls, db) -> dict:
        """Vérifie que le scraper a tourné récemment"""
        issues = {}
        last_run = db.execute(
            "SELECT run_at, source, found FROM scrape_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()

        if not last_run:
            issues["scraper"] = "Aucun run enregistré"
        else:
            last_run_dt = None
            try:
                last_run_dt = datetime.strptime(last_run["run_at"][:19], "%Y-%m-%d %H:%M:%S")
                hours_ago = (datetime.now() - last_run_dt).total_seconds() / 3600
                if hours_ago > 6:
                    issues["scraper"] = f"Dernier run il y a {hours_ago:.1f}h — possible blocage"
                else:
                    issues["scraper"] = f"OK ({hours_ago:.1f}h)"
            except:
                issues["scraper"] = "Date run invalide"

        # Vérifier nombre de marchés actifs
        active_count = db.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif'").fetchone()[0]
        if active_count == 0:
            issues["tenders"] = "⚠️ Aucun marché actif — scraper peut-être bloqué"
        elif active_count < 10:
            issues["tenders"] = f"⚠️ Seulement {active_count} marchés actifs"
        else:
            issues["tenders"] = f"OK ({active_count} actifs)"

        return issues

    @classmethod
    async def run(cls):
        """Boucle principale — tourne toutes les 10 minutes"""
        logger.info("[SelfHealingAgent] Démarré")
        await asyncio.sleep(30)  # Attendre que l'app soit prête

        while True:
            try:
                db = get_db()
                repairs_done = []

                # 1. Réparer le schéma DB
                schema_repairs = cls.repair_schema(db)
                for r in schema_repairs:
                    if r.startswith("✅"):
                        repairs_done.append(r)
                        cls.log_repair(db, "schema", r)

                # 2. Expirer les marchés passés
                expired = cls.expire_tenders(db)
                if expired > 0:
                    msg = f"⏰ {expired} marchés expirés"
                    repairs_done.append(msg)
                    cls.log_repair(db, "expire", msg)

                # 3. Nettoyer la DB
                clean_stats = cls.clean_db(db)
                if clean_stats.get("dupes_removed", 0) > 0:
                    msg = f"🗑 {clean_stats['dupes_removed']} doublons supprimés"
                    repairs_done.append(msg)
                    cls.log_repair(db, "dedup", msg)

                # 4. Vérifier santé scraper
                health = cls.check_scraper_health(db)
                for k, v in health.items():
                    if "⚠️" in v:
                        cls.log_repair(db, "health", v, success=False)
                        repairs_done.append(v)

                # 5. Notifier admin si réparations importantes
                important = [r for r in repairs_done if any(x in r for x in ["❌","⚠️","doublons","expirés"])]
                if important:
                    cls.notify_admin("\n".join(important[:5]))

                db.close()

                if repairs_done:
                    logger.info(f"[SelfHealingAgent] {len(repairs_done)} actions: {repairs_done[:3]}")

            except Exception as e:
                logger.error(f"[SelfHealingAgent] Erreur boucle: {e}")

            await asyncio.sleep(600)  # toutes les 10 minutes

    @classmethod
    def get_report(cls) -> dict:
        """Retourne un rapport de l'état du système"""
        db = get_db()
        try:
            repairs = db.execute(
                "SELECT action,detail,success,repaired_at FROM agent_repairs ORDER BY id DESC LIMIT 20"
            ).fetchall()
            errors = db.execute(
                "SELECT agent,error,count,last_seen FROM agent_errors WHERE resolved=0 ORDER BY count DESC LIMIT 10"
            ).fetchall()
            schema_ok = True
            for table in cls.SCHEMA:
                try: db.execute(f"SELECT COUNT(*) FROM {table}")
                except: schema_ok = False; break
            return {
                "schema_ok":    schema_ok,
                "repairs":      [dict(r) for r in repairs],
                "errors":       [dict(e) for e in errors],
                "active_tenders": db.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif'").fetchone()[0],
                "members":      db.execute("SELECT COUNT(*) FROM members").fetchone()[0],
                "last_repair":  repairs[0]["repaired_at"] if repairs else None,
            }
        finally:
            db.close()


class MonitorAgent:
    @staticmethod
    def log_error(agent, route, error):
        try:
            db = get_db()
            ex = db.execute("SELECT id FROM agent_errors WHERE agent=? AND route=? AND resolved=0",(agent,route)).fetchone()
            if ex: db.execute("UPDATE agent_errors SET count=count+1,last_seen=?,error=? WHERE id=?",(now_str(),error[:300],ex["id"]))
            else:  db.execute("INSERT INTO agent_errors (agent,route,error,count,first_seen,last_seen) VALUES (?,?,?,1,?,?)",(agent,route,error[:300],now_str(),now_str()))
            db.commit(); db.close()
        except: pass

    @staticmethod
    async def run():
        logger.info("[MonitorAgent] Started")
        while True:
            try:
                db = get_db()
                db.execute("DELETE FROM chats WHERE created_at < date('now','-7 days')")
                db.execute("DELETE FROM notif_queue WHERE status='sent' AND sent_at < date('now','-30 days')")
                db.execute("UPDATE notif_queue SET status='pending',attempts=0 WHERE status='failed' AND created_at < datetime('now','-1 hour') AND attempts < 3")
                # Auto-expire tenders — handles all date formats
                today_dt = datetime.now().date()
                # Format ISO YYYY-MM-DD
                db.execute(
                    "UPDATE tenders SET statut='expire' WHERE statut='actif' "
                    "AND date_limite!='' AND date_limite NOT LIKE '%/%' "
                    "AND date_limite < date('now') AND date_limite NOT IN ('N/A','—','-')"
                )
                # Format DD/MM/YYYY
                rows = db.execute(
                    "SELECT id, date_limite FROM tenders "
                    "WHERE statut='actif' AND date_limite LIKE '%/%'"
                ).fetchall()
                exp_ids = []
                for row in rows:
                    dl = str(row["date_limite"]).strip()
                    m = re.search(r'(\d{2}/\d{2}/\d{4})', dl)
                    if m:
                        try:
                            if datetime.strptime(m.group(1), "%d/%m/%Y").date() < today_dt:
                                exp_ids.append(row["id"])
                        except: pass
                if exp_ids:
                    ph = ",".join(["?"] * len(exp_ids))
                    db.execute(f"UPDATE tenders SET statut='expire' WHERE id IN ({ph})", exp_ids)
                db.commit(); db.close()
            except Exception as e: logger.error(f"[MonitorAgent] {e}")
            await asyncio.sleep(3600)

    @staticmethod
    def get_stats() -> dict:
        db = get_db()
        try:
            return {
                "tenders_total":  db.execute("SELECT COUNT(*) FROM tenders").fetchone()[0],
                "tenders_active": db.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif'").fetchone()[0],
                "tenders_expire": db.execute("SELECT COUNT(*) FROM tenders WHERE statut='expire'").fetchone()[0],
                "easy_to_win":    db.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif' AND ai_score>=70").fetchone()[0],
                "members":        db.execute("SELECT COUNT(*) FROM members WHERE actif=1").fetchone()[0],
                "members_tg":     db.execute("SELECT COUNT(*) FROM members WHERE telegram!='' AND actif=1").fetchone()[0],
                "posts":          db.execute("SELECT COUNT(*) FROM posts WHERE status='actif'").fetchone()[0],
                "notif_pending":  db.execute("SELECT COUNT(*) FROM notif_queue WHERE status='pending'").fetchone()[0],
                "notif_sent":     db.execute("SELECT COUNT(*) FROM notif_queue WHERE status='sent'").fetchone()[0],
                "notif_failed":   db.execute("SELECT COUNT(*) FROM notif_queue WHERE status='failed'").fetchone()[0],
                "errors":         db.execute("SELECT COUNT(*) FROM agent_errors WHERE resolved=0").fetchone()[0],
            }
        finally: db.close()

# ══════════════════════════════════════════════════════
# CHAT AGENT
# ══════════════════════════════════════════════════════
CHAT_SYS = f"""Tu es l'assistant IA de {BRAND}, plateforme marocaine de veille marchés publics.
Aide les PME sur: procédures AO, Décret 2-22-431, CPS, CCAG, qualification BTP, codes T/P/S.
Réponds en français ou arabe. Max 300 mots sauf si complexe. Renvoie vers marchespublics.gov.ma.
Site: {SITE_URL}"""

class ChatAgent:
    @staticmethod
    async def respond(messages: list) -> str:
        if not ANTHROPIC_KEY:
            return f"🤖 Assistant IA non configuré.\n📞 Contactez-nous: {SITE_URL}/contact"
        try:
            import httpx
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={"x-api-key":ANTHROPIC_KEY,"anthropic-version":"2023-06-01","content-type":"application/json"},
                    json={"model":"claude-haiku-4-5-20251001","max_tokens":600,
                          "system":CHAT_SYS,"messages":messages[-12:]}
                )
                if r.status_code == 200:
                    return r.json()["content"][0]["text"]
                return f"Erreur API ({r.status_code}). Réessayez."
        except Exception as e:
            logger.error(f"[ChatAgent] {e}")
            return "Service temporairement indisponible."

# ══════════════════════════════════════════════════════
# SCHEDULERS
# ══════════════════════════════════════════════════════
LAST_SCRAPE = 0.0
RESET_TOKENS: dict = {}

async def scrape_scheduler():
    await asyncio.sleep(90)
    global LAST_SCRAPE
    while True:
        try:
            if time.time() - LAST_SCRAPE >= SCRAPE_HOURS * 3600:
                LAST_SCRAPE = time.time()
                loop = asyncio.get_event_loop()
                all_new = []
                # Official scraper
                official = await loop.run_in_executor(None, ScraperAgent.run)
                all_new.extend(official)
                # Multi-source
                if HAS_MULTI:
                    db = get_db()
                    try: known = set(r[0] for r in db.execute("SELECT id FROM tenders").fetchall())
                    finally: db.close()
                    extra = [s for s in MULTI_SRC.keys() if s != "marchespublics"]
                    def run_multi(): return run_all_scrapers(known, extra, SLog.add)
                    multi = await loop.run_in_executor(None, run_multi)
                    if multi and ANTHROPIC_KEY:
                        multi = await AIClassifier.batch_classify(multi, ANTHROPIC_KEY, max_b=8)
                    saved = 0
                    for t in multi:
                        td = {"id":t.id,"objet":t.objet,"acheteur":t.acheteur,
                              "region":t.region,"domaine":t.domaine,"type_marche":t.type_marche,
                              "montant":t.montant,"date_publication":t.date_publication,
                              "date_limite":t.date_limite,"description":t.description,
                              "statut":t.statut,"url":t.source_url,"source":t.source,
                              "contact":t.contact,"budget_min":t.budget_min,"budget_max":t.budget_max,
                              "ai_score":t.ai_score,"ai_category":t.ai_category,"ai_reason":t.ai_reason}
                        if ScraperAgent._save(td):
                            saved += 1
                            if t.statut == "actif": all_new.append(td)
                    SLog.add(f"Multi-source: {saved}/{len(multi)} sauvegardés")
                if all_new: NotifyAgent.notify_instant(all_new)
        except Exception as e:
            SState.running = False; logger.error(f"[scheduler:scrape] {e}")
        await asyncio.sleep(600)

async def digest_scheduler():
    while True:
        now_ = datetime.now()
        next_ = now_.replace(hour=8, minute=0, second=0, microsecond=0)
        if now_ >= next_: next_ += timedelta(days=1)
        await asyncio.sleep((next_ - now_).total_seconds())
        try: NotifyAgent.notify_digest()
        except Exception as e: logger.error(f"[scheduler:digest] {e}")

# ══════════════════════════════════════════════════════
# APP
# ══════════════════════════════════════════════════════
@asynccontextmanager
async def lifespan(app):
    for d in ["static","data","templates"]:
        os.makedirs(d, exist_ok=True)
    try: init_db()
    except Exception as e: logger.error(f"[init_db] {e}")
    asyncio.create_task(NotifyAgent.worker())
    asyncio.create_task(MonitorAgent.run())
    asyncio.create_task(SelfHealingAgent.run())
    asyncio.create_task(scrape_scheduler())
    asyncio.create_task(digest_scheduler())
    logger.info(f"✅ {BRAND} v5.0 — All agents started")
    yield

