"""SOURCE — Scraper · marchespublics.gov.ma UNIQUEMENT"""
import re, time, ssl, random, logging, requests, urllib3
from datetime import datetime, date
from bs4 import BeautifulSoup
from app.core.config import cfg
from app.core.stx10 import classify
urllib3.disable_warnings()
logger = logging.getLogger("source.scraper")

BASE = "https://www.marchespublics.gov.ma/bdc/entreprise/consultation"
UA = ["Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0 Safari/537.36",
      "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) Safari/605.1.15",
      "Mozilla/5.0 (Windows NT 10.0; rv:126.0) Gecko/20100101 Firefox/126.0"]
DATE_RE = re.compile(r'(\d{2}/\d{2}/\d{4}|\d{4}-\d{2}-\d{2}|\d{2}-\d{2}-\d{4})')

def _sess():
    s = requests.Session()
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
    s.mount("https://", HTTPAdapter(max_retries=Retry(total=3,backoff_factor=1)))
    s.headers.update({"User-Agent":random.choice(UA),"Accept-Language":"fr-MA,fr;q=0.9"})
    return s

def _parse_date(s):
    s = str(s).strip().split()[0]
    for fmt in ["%d/%m/%Y","%Y-%m-%d","%d-%m-%Y"]:
        try: return datetime.strptime(s,fmt).date()
        except: pass
    return None

def _extract_date(text):
    if not text: return ""
    m = DATE_RE.search(str(text))
    if m:
        d = _parse_date(m.group(1))
        if d: return d.strftime("%d/%m/%Y")
    return ""

def _expired(text):
    if not text or str(text).strip() in ("","N/A","—","-"): return False
    m = DATE_RE.search(str(text))
    if m:
        d = _parse_date(m.group(1))
        if d: return d < date.today()
    return False

def _cell(soup, *labels):
    for row in soup.find_all("tr"):
        cells = row.find_all(["td","th"])
        if len(cells)>=2:
            lbl = cells[0].get_text(" ",strip=True).lower()
            for l in labels:
                if l.lower() in lbl: return cells[1].get_text(" ",strip=True)
    return ""

def _max_id(sess):
    try:
        r = sess.get(f"{BASE}/list", timeout=20)
        ids = [int(m.group(1)) for m in re.finditer(r'/consultation/show/(\d+)', r.text)]
        return max(ids) if ids else 0
    except Exception as e: logger.error(f"[max_id] {e}"); return 0

def _fetch(sess, tid):
    url = f"{BASE}/show/{tid}"
    try:
        r = sess.get(url, timeout=20)
        if r.status_code in (404,403): return None
        if r.status_code!=200: return None
        soup = BeautifulSoup(r.text,"lxml")
        text = soup.get_text(" ",strip=True)
        if len(text)<200: return None
        for skip in ["connexion","liste des avis","se connecter"]:
            if skip in text[:300].lower(): return None
        # Objet
        objet=""
        for tag in soup.find_all(["h1","h2","h3"]):
            t = tag.get_text(" ",strip=True)
            if len(t)>20 and not any(s in t.lower() for s in ["accueil","connexion","portail","retour"]):
                objet=t[:300]; break
        if not objet: objet=_cell(soup,"objet","désignation","intitulé","libellé")
        if not objet or len(objet)<8: return None
        acheteur=_cell(soup,"acheteur","maître d'ouvrage","organisme","administration","ministère","commune")
        date_pub=_extract_date(_cell(soup,"publication","date de publication")) or datetime.now().strftime("%d/%m/%Y")
        date_limite=""
        for lbl in ["date et heure limite","date limite","date de remise","clôture","heure limite"]:
            v=_cell(soup,lbl)
            if v: date_limite=_extract_date(v); break
        if _expired(date_limite): return None
        montant=_cell(soup,"montant","budget","estimation","coût","valeur") or ""
        if len(montant)>60: montant=""
        region=_cell(soup,"région","wilaya","lieu d'exécution","localisation","ville") or ""
        if len(region)>80: region=region[:80]
        stx=classify(f"{objet} {acheteur} {region}")
        return {"id":f"bdc_{tid}","objet":objet[:300],"acheteur":acheteur[:150],
                "stx10_code":stx.get("code","S902"),"stx10_label":stx.get("label",""),
                "region":region[:100],"montant":montant[:80],
                "date_publication":date_pub,"date_limite":date_limite,
                "url":url,"statut":"actif","scraped_at":datetime.now().isoformat()}
    except Exception as e: logger.debug(f"[fetch {tid}] {e}"); return None

def scrape_new(db, last_max=0):
    sess=_sess(); found=[]; t0=time.time()
    cur=_max_id(sess)
    if not cur: logger.warning("[scraper] max_id=0"); return []
    start=max(1,last_max+1 if last_max and last_max<cur else cur-250)
    end=cur+30
    logger.info(f"[scraper] {start}→{end} (max={cur})")
    for tid in range(end,start-1,-1):
        if db.execute("SELECT id FROM tenders WHERE id=?",(f"bdc_{tid}",)).fetchone(): continue
        t=_fetch(sess,tid)
        if t:
            try:
                db.execute("""INSERT OR IGNORE INTO tenders
                    (id,objet,acheteur,stx10_code,stx10_label,region,montant,
                     date_publication,date_limite,url,statut,scraped_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (t["id"],t["objet"],t["acheteur"],t["stx10_code"],t["stx10_label"],
                     t["region"],t["montant"],t["date_publication"],t["date_limite"],
                     t["url"],t["statut"],t["scraped_at"]))
                db.commit(); found.append(t)
                logger.info(f"✅ {t['id']} [{t['stx10_code']}] {t['objet'][:55]}")
            except Exception as e: logger.error(f"[DB] {e}")
        time.sleep(random.uniform(0.8,1.5))
    # Expire
    try:
        for row in db.execute("SELECT id,date_limite FROM tenders WHERE statut='actif' AND date_limite!=''").fetchall():
            if _expired(row["date_limite"]):
                db.execute("UPDATE tenders SET statut='expiré' WHERE id=?",(row["id"],))
        db.commit()
    except: pass
    dur=round(time.time()-t0,1)
    try:
        db.execute("INSERT INTO scrape_log(ts,found,duration) VALUES(?,?,?)",
                   (datetime.now().isoformat(),len(found),dur)); db.commit()
    except: pass
    logger.info(f"[scraper] ✅ {len(found)} en {dur}s")
    return found
