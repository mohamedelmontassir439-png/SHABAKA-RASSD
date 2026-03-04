"""شبكة رصد v5 — نسخة نهائية مع ثيم بني/أسود"""
from fastapi import FastAPI, Request, Form, BackgroundTasks, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from contextlib import asynccontextmanager
import sqlite3, json, re, time, random, os, asyncio, smtplib, hashlib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from pathlib import Path
import httpx, urllib3
urllib3.disable_warnings()

GMAIL_USER   = os.getenv("GMAIL_USER",   "mohamedelmontassir439@gmail.com")
GMAIL_PASS   = os.getenv("GMAIL_PASS",   "nvzdanptagoovjxr")
TELEGRAM_BOT = os.getenv("TELEGRAM_BOT", "7849539613:AAFZTtMNEo92UqE3OIcXPdX65OCm8DrvgAA")
ADMIN_PASS   = os.getenv("ADMIN_PASS",   "rassd2026")
DB_PATH      = os.getenv("DB_PATH",      "data/rassd.db")
BASE_URL     = "https://www.marchespublics.gov.ma"
SHOW_URL     = f"{BASE_URL}/bdc/entreprise/consultation/show/"
LIST_URL     = f"{BASE_URL}/bdc/entreprise/consultation/"

CANCEL_KEYWORDS = ["annulé","annulation","infructueux","infructueuse","sans suite","résiliation","ملغى","إلغاء"]
GOODS_DOMAINS   = ["Mobilier & Équipements","Alimentation","Transport","Équipements médicaux","Informatique"]

SUPPLIERS = {
    "Mobilier & Équipements": [
        {"nom":"KITEA Maroc","ville":"جميع المدن","tel":"0801 000 444","site":"kitea.com","desc":"أثاث ومعدات مكتبية"},
        {"nom":"Mobilia","ville":"الدار البيضاء، الرباط","tel":"0522 340 000","site":"mobilia.ma","desc":"أثاث عصري"},
        {"nom":"Bureau Vallée","ville":"الدار البيضاء، الرباط","tel":"0522 394 545","site":"bureauvallee.ma","desc":"لوازم مكتبية"},
    ],
    "Alimentation": [
        {"nom":"Marjane Holding","ville":"جميع المدن","tel":"0522 570 000","site":"marjane.ma","desc":"توريد مواد غذائية"},
        {"nom":"Metro Cash & Carry","ville":"الدار البيضاء، الرباط، فاس","tel":"0522 666 000","site":"metro.ma","desc":"بيع بالجملة"},
        {"nom":"Label'Vie","ville":"الرباط، الدار البيضاء","tel":"0537 718 800","site":"labelvie.ma","desc":"توريد غذائي"},
    ],
    "Transport": [
        {"nom":"Toyota Maroc","ville":"جميع المدن","tel":"0522 548 800","site":"toyota.ma","desc":"سيارات ومركبات"},
        {"nom":"Iveco Maroc","ville":"الدار البيضاء","tel":"0522 351 900","site":"iveco.com","desc":"شاحنات تجارية"},
        {"nom":"Peugeot Citroën Maroc","ville":"جميع المدن","tel":"0522 547 000","site":"psa-maroc.com","desc":"سيارات وعربات"},
    ],
    "Équipements médicaux": [
        {"nom":"Pharma 5","ville":"الرباط","tel":"0537 688 500","site":"pharma5.ma","desc":"معدات طبية"},
        {"nom":"Medimaroc","ville":"الدار البيضاء","tel":"0522 402 020","site":"medimaroc.ma","desc":"أجهزة طبية"},
        {"nom":"Saidal Distribution","ville":"الدار البيضاء","tel":"0522 244 500","site":"saidal.ma","desc":"مستلزمات صحية"},
    ],
    "Informatique": [
        {"nom":"Maghreb Systems","ville":"الدار البيضاء، الرباط","tel":"0522 944 500","site":"maghrebsystems.com","desc":"حلول تقنية"},
        {"nom":"Maroc Telecom Business","ville":"جميع المدن","tel":"0537 719 700","site":"iam.ma","desc":"شبكات واتصالات"},
        {"nom":"Dell Technologies Maroc","ville":"الدار البيضاء","tel":"0522 958 000","site":"dell.com/ma","desc":"أجهزة وخوادم"},
    ],
}

REGIONS = {
    "Tanger-Tétouan-Al Hoceïma": {"ar":"طنجة-تطوان-الحسيمة","villes":["TANGER","TETOUAN","AL HOCEIMA","LARACHE","CHEFCHAOUEN","MDIQ","FNIDEQ","OUEZZANE"]},
    "Oriental":                   {"ar":"الشرق","villes":["OUJDA","NADOR","BERKANE","TAOURIRT","JERADA","DRIOUCH","GUERCIF"]},
    "Fès-Meknès":                 {"ar":"فاس-مكناس","villes":["FES","MEKNES","TAZA","IFRANE","SEFROU","BOULEMANE","EL HAJEB"]},
    "Rabat-Salé-Kénitra":         {"ar":"الرباط-سلا-القنيطرة","villes":["RABAT","SALE","KENITRA","KHEMISSET","SIDI KACEM","SIDI SLIMANE"]},
    "Béni Mellal-Khénifra":       {"ar":"بني ملال-خنيفرة","villes":["BENI MELLAL","KHOURIBGA","FQUIH BEN SALAH","AZILAL","MIDELT"]},
    "Casablanca-Settat":          {"ar":"الدار البيضاء-سطات","villes":["CASABLANCA","SETTAT","BERRECHID","EL JADIDA","MOHAMMEDIA","BENSLIMANE"]},
    "Marrakech-Safi":             {"ar":"مراكش-آسفي","villes":["MARRAKECH","SAFI","ESSAOUIRA","EL KELAÂ DES SRAGHNA","CHICHAOUA"]},
    "Drâa-Tafilalet":             {"ar":"درعة-تافيلالت","villes":["ERRACHIDIA","OUARZAZATE","TINGHIR","ZAGORA"]},
    "Souss-Massa":                {"ar":"سوس-ماسة","villes":["AGADIR","TIZNIT","TAROUDANT","INEZGANE","CHTOUKA AIT BAHA","TATA"]},
    "Guelmim-Oued Noun":          {"ar":"كلميم-واد نون","villes":["GUELMIM","TAN-TAN","SIDI IFNI","ASSA"]},
    "Laâyoune-Sakia El Hamra":    {"ar":"العيون-الساقية الحمراء","villes":["LAAYOUNE","BOUJDOUR","TARFAYA","ES-SEMARA"]},
    "Dakhla-Oued Ed-Dahab":       {"ar":"الداخلة-وادي الذهب","villes":["DAKHLA","AOUSSERD"]},
}

DOMAINS_FR = {
    "Travaux routiers":       ["voirie","route","piste","bitum","chaussée","autoroute","asphalte"],
    "Construction":           ["construction","bâtiment","réhabilitation","rénovation","aménagement","génie civil"],
    "Eau & Assainissement":   ["assainissement","eau potable","réseau","canalisation","hydraulique","forage","barrage"],
    "Électricité":            ["électricité","éclairage","réseau électrique","groupe électrogène","énergie solaire"],
    "Informatique":           ["informatique","logiciel","système","serveur","réseau","numérique","application"],
    "Équipements médicaux":   ["médical","pharmaceutique","laboratoire","hospitalier","médicament","santé","clinique"],
    "Études & Conseil":       ["étude","ingénierie","architecture","topographie","audit","conseil","expertise"],
    "Nettoyage & Sécurité":   ["nettoyage","gardiennage","entretien","maintenance","sécurité","surveillance"],
    "Mobilier & Équipements": ["mobilier","bureau","fourniture","équipement","matériel","outillage"],
    "Transport":              ["transport","véhicule","camion","bus","pièces de rechange","carburant"],
    "Alimentation":           ["alimentaire","restauration","produit alimentaire","traiteur","catering"],
}
DOMAINS_AR = {
    "Travaux routiers":"أشغال الطرق","Construction":"البناء والتشييد",
    "Eau & Assainissement":"الماء والتطهير","Électricité":"الكهرباء",
    "Informatique":"المعلوميات","Équipements médicaux":"المعدات الطبية",
    "Études & Conseil":"الدراسات","Nettoyage & Sécurité":"النظافة والحراسة",
    "Mobilier & Équipements":"الأثاث","Transport":"النقل","Alimentation":"الأغذية",
    "Autres services":"خدمات أخرى",
}

def classify_domain(text):
    t = text.lower()
    for d, kws in DOMAINS_FR.items():
        if any(k in t for k in kws): return d
    return "Autres services"

def classify_region(text):
    u = text.upper()
    for region, data in REGIONS.items():
        if any(v in u for v in data["villes"]): return region
    return ""

def is_cancelled(text):
    t = text.lower()
    return any(k in t for k in CANCEL_KEYWORDS)

def generate_summary(text, objet, domaine, lang='fr'):
    qty_m = re.search(r'(\d+[\s]*(?:unités?|lots?|pièces?|kits?))', text, re.I)
    qty = qty_m.group(1) if qty_m else ""
    dur_m = re.search(r'(\d+[\s]*(?:mois|ans?|jours?))', text, re.I)
    dur = dur_m.group(1) if dur_m else ""
    if lang == 'ar':
        domain_ar = DOMAINS_AR.get(domaine, domaine)
        s = f"تطلب هذه الصفقة {domain_ar}"
        if qty: s += f" بكمية {qty}"
        if dur:  s += f" لمدة {dur}"
        s += ". يُنصح بالتحقق من المتطلبات الفنية في وثيقة الدعوة."
    else:
        s = f"Ce marché porte sur {domaine.lower()}"
        if qty: s += f" ({qty})"
        if dur:  s += f" pour {dur}"
        s += ". Vérifiez les spécifications dans le dossier d'appel d'offres."
    return s

def extract_clauses(text):
    clauses = []
    patterns = [
        r'(?:capacité|expérience|référence|attestation|certificat|agrément|qualification)[^.]{5,80}',
        r'(?:dossier|document|pièce justificative)[^.]{5,60}',
        r'(?:caution|garantie)[^.]{5,60}',
        r'(?:délai|durée)[^.]{5,60}',
        r'(?:critère|évaluation)[^.]{5,60}',
    ]
    for p in patterns:
        for m in re.findall(p, text, re.I)[:2]:
            m = m.strip()[:100]
            if len(m) > 20 and m not in clauses:
                clauses.append(m)
    return clauses[:6]

def extract_date(text):
    for p in [r'\d{2}/\d{2}/\d{4}', r'\d{4}-\d{2}-\d{2}']:
        m = re.search(p, str(text))
        if m: return m.group(0)
    return ""

def get_suppliers(domaine):
    return SUPPLIERS.get(domaine, [])

# ── DB ───────────────────────────────────────────────────────────────
def init_db():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.executescript("""
    CREATE TABLE IF NOT EXISTS tenders (
        id TEXT PRIMARY KEY, objet TEXT, acheteur TEXT,
        region TEXT, ville TEXT, domaine TEXT, montant TEXT,
        date_publication TEXT, date_limite TEXT, description TEXT,
        clauses TEXT, summary TEXT, statut TEXT DEFAULT 'actif',
        url TEXT, date_extraction TEXT
    );
    CREATE TABLE IF NOT EXISTS contractors (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nom TEXT NOT NULL, entreprise TEXT,
        phone TEXT UNIQUE NOT NULL, email TEXT,
        whatsapp TEXT, telegram TEXT,
        domaines TEXT DEFAULT '[]', regions TEXT DEFAULT '[]',
        langue TEXT DEFAULT 'fr', plan TEXT DEFAULT 'free',
        actif INTEGER DEFAULT 1, token TEXT UNIQUE,
        created_at TEXT, notif_count INTEGER DEFAULT 0, last_login TEXT
    );
    CREATE TABLE IF NOT EXISTS notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        contractor_id INTEGER, tender_id TEXT,
        channel TEXT, sent_at TEXT, status TEXT DEFAULT 'sent'
    );
    CREATE TABLE IF NOT EXISTS payment_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        phone TEXT, email TEXT, method TEXT,
        amount INTEGER DEFAULT 99, status TEXT DEFAULT 'pending', created_at TEXT
    );
    """)
    try: db.execute("ALTER TABLE tenders ADD COLUMN summary TEXT")
    except: pass
    try: db.execute("ALTER TABLE tenders ADD COLUMN statut TEXT DEFAULT 'actif'")
    except: pass
    db.commit()
    return db

DB = init_db()

def make_token(phone):
    return hashlib.md5(f"{phone}rassd2026".encode()).hexdigest()[:16]

# ── Scraper ──────────────────────────────────────────────────────────
UAS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
]

def parse_tender(html, tid):
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, 'html.parser')
    full = soup.get_text(' ', strip=True)
    statut = 'annule' if is_cancelled(full) else 'actif'
    def fv(labels):
        for l in labels:
            el = soup.find(string=re.compile(l, re.I))
            if el:
                p = el.parent
                if p:
                    n = p.find_next_sibling()
                    if n: return n.get_text(strip=True)[:200]
                    t = p.get_text(strip=True)
                    if ':' in t: return t.split(':',1)[-1].strip()[:200]
        return ''
    objet    = fv(['Objet','intitulé','Désignation']) or f"Consultation #{tid}"
    acheteur = fv(['Acheteur','organisme','Pouvoir adjudicateur'])
    lim_m    = re.search(r'[Dd]ate\s+limite[^:]*?(\d{2}[/\-]\d{2}[/\-]\d{4})', full)
    date_lim = lim_m.group(1) if lim_m else extract_date(full[200:600])
    domaine  = classify_domain(f"{objet} {full[:400]}")
    region   = classify_region(f"{acheteur} {full[:500]}")
    ville    = ""
    for r, data in REGIONS.items():
        u = full.upper()
        for v in data["villes"]:
            if v in u:
                ville = v.title()
                if not region: region = r
                break
        if ville: break
    desc_parts = [s.strip() for s in full.split('  ') if len(s.strip()) > 30]
    description = ' | '.join(desc_parts[:4])[:500]
    return {
        'id': str(tid), 'objet': objet, 'acheteur': acheteur,
        'region': region, 'ville': ville, 'domaine': domaine,
        'montant': fv(['Montant','Budget','Estimation']),
        'date_publication': extract_date(full[:400]),
        'date_limite': date_lim, 'description': description,
        'clauses': json.dumps(extract_clauses(full), ensure_ascii=False),
        'summary': generate_summary(full, objet, domaine, 'fr'),
        'statut': statut, 'url': f"{SHOW_URL}{tid}",
        'date_extraction': datetime.now().strftime("%Y-%m-%d %H:%M"),
    }

def save_tender(t):
    try:
        DB.execute("""INSERT OR IGNORE INTO tenders
            (id,objet,acheteur,region,ville,domaine,montant,date_publication,
             date_limite,description,clauses,summary,statut,url,date_extraction)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (t['id'],t['objet'],t['acheteur'],t['region'],t['ville'],t['domaine'],
             t['montant'],t['date_publication'],t['date_limite'],t['description'],
             t['clauses'],t.get('summary',''),t.get('statut','actif'),t['url'],t['date_extraction']))
        DB.commit()
        return DB.execute("SELECT changes()").fetchone()[0] > 0
    except Exception as e:
        print(f"DB error: {e}")
        return False

def scrape_sync():
    import requests
    from bs4 import BeautifulSoup
    s = requests.Session()
    s.verify = False
    s.headers.update({"User-Agent": random.choice(UAS), "Accept-Language": "fr-FR,fr;q=0.9"})
    try: s.get(BASE_URL, timeout=10)
    except: pass
    new_tenders = []
    known = set(r[0] for r in DB.execute("SELECT id FROM tenders"))
    max_id = DB.execute("SELECT MAX(CAST(id AS INTEGER)) FROM tenders").fetchone()[0] or 300000
    for page in range(1, 5):
        url = LIST_URL if page == 1 else f"{LIST_URL}?page={page}"
        try:
            r = s.get(url, timeout=20)
            if r.status_code != 200: break
            soup = BeautifulSoup(r.text, 'html.parser')
            ids = []
            for a in soup.find_all('a', href=re.compile(r'/consultation/show/(\d+)')):
                m = re.search(r'/show/(\d+)', a['href'])
                if m: ids.append(m.group(1))
            for tid in set(ids):
                if tid not in known:
                    try:
                        resp = s.get(f"{SHOW_URL}{tid}", timeout=15)
                        if resp.status_code == 200:
                            t = parse_tender(resp.text, tid)
                            if save_tender(t):
                                known.add(tid)
                                if t.get('statut') == 'actif':
                                    new_tenders.append(t)
                        time.sleep(random.uniform(0.5, 1.5))
                    except: pass
        except: pass
        time.sleep(random.uniform(2, 4))
    fail, cur = 0, max_id + 1
    while fail < 8 and len(new_tenders) < 25:
        try:
            r = s.get(f"{SHOW_URL}{cur}", timeout=10)
            if r.status_code == 404: fail += 1
            elif r.status_code == 200:
                fail = 0
                if str(cur) not in known:
                    t = parse_tender(r.text, str(cur))
                    if save_tender(t):
                        known.add(str(cur))
                        if t.get('statut') == 'actif':
                            new_tenders.append(t)
        except: fail += 1
        cur += 1
        time.sleep(random.uniform(0.3, 1.0))
    return new_tenders

# ── Notifications ────────────────────────────────────────────────────
async def send_email(to_email, subject, html):
    if not to_email or not GMAIL_USER: return
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = f"شبكة رصد <{GMAIL_USER}>"
        msg["To"]      = to_email
        msg.attach(MIMEText(html, "html", "utf-8"))
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(GMAIL_USER, GMAIL_PASS.replace(" ", ""))
            s.send_message(msg)
    except Exception as e:
        print(f"Email error: {e}")

async def send_telegram(chat_id, msg):
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT}/sendMessage",
                json={"chat_id": chat_id, "text": msg, "parse_mode": "Markdown"})
        except: pass

def build_suppliers_html(domaine, lang='fr'):
    suppliers = get_suppliers(domaine)
    if not suppliers: return ""
    title = "🏪 موردون مقترحون" if lang=='ar' else "🏪 Fournisseurs recommandés"
    rows = ""
    for sup in suppliers[:3]:
        rows += f"""<tr>
          <td style="padding:10px;border-bottom:1px solid #f5efe6"><strong style="color:#8B4513">{sup['nom']}</strong><br>
          <span style="font-size:11px;color:#888">📍 {sup['ville']}</span></td>
          <td style="padding:10px;border-bottom:1px solid #f5efe6;font-size:12px">{sup['desc']}</td>
          <td style="padding:10px;border-bottom:1px solid #f5efe6;font-size:11px">📞 {sup['tel']}<br>🌐 {sup['site']}</td>
        </tr>"""
    return f"""<div style="margin-top:20px;background:#fdf6ee;border-radius:10px;padding:16px;border:1px solid #e8d5b7">
      <h3 style="margin:0 0 12px;font-size:14px;color:#8B4513">{title}</h3>
      <table style="width:100%;border-collapse:collapse;font-size:12px"><tr style="background:#f5efe6">
        <th style="padding:8px;text-align:right;font-size:11px;color:#5D2E0C">المورد</th>
        <th style="padding:8px;text-align:right;font-size:11px;color:#5D2E0C">الوصف</th>
        <th style="padding:8px;text-align:right;font-size:11px;color:#5D2E0C">التواصل</th>
      </tr>{rows}</table></div>"""

def build_email_html(contractor, tender, lang):
    clauses = []
    try: clauses = json.loads(tender['clauses'] or '[]')
    except: pass
    region_ar = REGIONS.get(tender['region'], {}).get('ar', tender['region'])
    domain_ar = DOMAINS_AR.get(tender['domaine'], tender['domaine'])
    token     = contractor['token']
    summary   = tender.get('summary') or ''
    grad      = "linear-gradient(135deg,#1a0a00,#8B4513)"

    clauses_html = ""
    if clauses:
        items = "".join(f"<li style='padding:4px 0;font-size:12px'>{c}</li>" for c in clauses)
        title = "📋 البنود والمتطلبات" if lang=='ar' else "📋 Clauses"
        clauses_html = f"""<div style='margin-top:16px;background:#fdf6ee;padding:14px;border-radius:8px;border:1px solid #e8d5b7'>
            <strong style='font-size:13px;color:#8B4513'>{title}:</strong>
            <ul style='margin:8px 0 0 20px;color:#374151'>{items}</ul></div>"""

    summary_html = ""
    if summary:
        title = "💡 ملخص" if lang=='ar' else "💡 Résumé"
        summary_html = f"""<div style='margin-top:16px;background:#f0ece8;padding:14px;border-radius:8px;border:1px solid #d4c5b0'>
            <strong style='font-size:13px;color:#5D2E0C'>{title}:</strong>
            <p style='margin:6px 0 0;font-size:12px;color:#374151'>{summary}</p></div>"""

    suppliers_html = build_suppliers_html(tender['domaine'], lang) if tender['domaine'] in GOODS_DOMAINS else ""

    if lang == 'ar':
        return f"""<div dir="rtl" style="font-family:Cairo,Arial,sans-serif;max-width:620px;margin:0 auto;background:#f9f5f0;padding:20px">
          <div style="background:{grad};color:white;padding:24px;border-radius:14px 14px 0 0;text-align:center">
            <h1 style="margin:0;font-size:22px">📡 شبكة رصد</h1>
            <p style="margin:6px 0 0;opacity:.85;font-size:13px">صفقة جديدة مناسبة لملفك</p>
          </div>
          <div style="background:white;padding:24px;border-radius:0 0 14px 14px;border:1px solid #e8d5b7">
            <h2 style="font-size:15px;color:#1a0a00;margin-bottom:16px">{tender['objet']}</h2>
            <table style="width:100%;border-collapse:collapse;font-size:13px">
              <tr><td style="padding:9px;color:#888;border-bottom:1px solid #f5efe6;width:35%">الجهة المشترية</td><td style="padding:9px;font-weight:700;border-bottom:1px solid #f5efe6">{tender['acheteur'] or '—'}</td></tr>
              <tr><td style="padding:9px;color:#888;border-bottom:1px solid #f5efe6">الجهة</td><td style="padding:9px;font-weight:700;border-bottom:1px solid #f5efe6">{region_ar or '—'}</td></tr>
              <tr><td style="padding:9px;color:#888;border-bottom:1px solid #f5efe6">المجال</td><td style="padding:9px;font-weight:700;border-bottom:1px solid #f5efe6">{domain_ar}</td></tr>
              <tr><td style="padding:9px;color:#888;border-bottom:1px solid #f5efe6">الميزانية</td><td style="padding:9px;font-weight:700;border-bottom:1px solid #f5efe6">{tender['montant'] or 'غير محدد'}</td></tr>
              <tr><td style="padding:9px;color:#dc2626">آخر أجل</td><td style="padding:9px;font-weight:900;color:#dc2626">{tender['date_limite'] or '—'}</td></tr>
            </table>
            {summary_html}{clauses_html}{suppliers_html}
            <a href="{tender['url']}" style="display:block;background:{grad};color:white;text-align:center;padding:13px;border-radius:9px;text-decoration:none;font-weight:700;margin-top:20px">🔗 فتح الصفقة في البوابة الرسمية</a>
            <a href="/dashboard/{token}" style="display:block;background:#f5efe6;color:#1a0a00;text-align:center;padding:10px;border-radius:9px;text-decoration:none;font-size:13px;margin-top:8px">📊 ملفك الشخصي</a>
          </div>
          <p style="text-align:center;font-size:11px;color:#aaa;margin-top:12px">شبكة رصد — مراقبة الصفقات العمومية المغربية</p>
        </div>"""
    else:
        return f"""<div style="font-family:Inter,Arial,sans-serif;max-width:620px;margin:0 auto;background:#f9f5f0;padding:20px">
          <div style="background:{grad};color:white;padding:24px;border-radius:14px 14px 0 0;text-align:center">
            <h1 style="margin:0;font-size:22px">📡 Shabaka Rassd</h1>
            <p style="margin:6px 0 0;opacity:.85;font-size:13px">Nouveau marché correspondant à votre profil</p>
          </div>
          <div style="background:white;padding:24px;border-radius:0 0 14px 14px;border:1px solid #e8d5b7">
            <h2 style="font-size:15px;color:#1a0a00;margin-bottom:16px">{tender['objet']}</h2>
            <table style="width:100%;border-collapse:collapse;font-size:13px">
              <tr><td style="padding:9px;color:#888;border-bottom:1px solid #f5efe6;width:35%">Acheteur</td><td style="padding:9px;font-weight:700;border-bottom:1px solid #f5efe6">{tender['acheteur'] or '—'}</td></tr>
              <tr><td style="padding:9px;color:#888;border-bottom:1px solid #f5efe6">Région</td><td style="padding:9px;font-weight:700;border-bottom:1px solid #f5efe6">{tender['region'] or '—'}</td></tr>
              <tr><td style="padding:9px;color:#888;border-bottom:1px solid #f5efe6">Secteur</td><td style="padding:9px;font-weight:700;border-bottom:1px solid #f5efe6">{tender['domaine']}</td></tr>
              <tr><td style="padding:9px;color:#888;border-bottom:1px solid #f5efe6">Budget</td><td style="padding:9px;font-weight:700;border-bottom:1px solid #f5efe6">{tender['montant'] or 'Non précisé'}</td></tr>
              <tr><td style="padding:9px;color:#dc2626">Date limite</td><td style="padding:9px;font-weight:900;color:#dc2626">{tender['date_limite'] or '—'}</td></tr>
            </table>
            {summary_html}{clauses_html}{suppliers_html}
            <a href="{tender['url']}" style="display:block;background:{grad};color:white;text-align:center;padding:13px;border-radius:9px;text-decoration:none;font-weight:700;margin-top:20px">🔗 Voir le marché sur le portail officiel</a>
            <a href="/dashboard/{token}" style="display:block;background:#f5efe6;color:#1a0a00;text-align:center;padding:10px;border-radius:9px;text-decoration:none;font-size:13px;margin-top:8px">📊 Mon tableau de bord</a>
          </div>
          <p style="text-align:center;font-size:11px;color:#aaa;margin-top:12px">Shabaka Rassd — Veille des marchés publics marocains</p>
        </div>"""

def match(contractor, tender):
    if tender.get('statut') == 'annule': return False
    c_domains = json.loads(contractor['domaines'] or '[]')
    c_regions  = json.loads(contractor['regions']  or '[]')
    if c_regions and tender['region'] and tender['region'] not in c_regions: return False
    if c_domains and tender['domaine'] not in c_domains and tender['domaine'] != 'Autres services': return False
    return True

async def notify_all(new_tenders):
    if not new_tenders: return
    contractors = DB.execute("SELECT * FROM contractors WHERE plan='premium' AND actif=1 AND email IS NOT NULL AND email!=''").fetchall()
    for c in contractors:
        c = dict(c)
        lang = c.get('langue', 'fr')
        for t in new_tenders:
            t = dict(t) if not isinstance(t, dict) else t
            if not match(c, t): continue
            html    = build_email_html(c, t, lang)
            subject = f"📡 {'صفقة جديدة' if lang=='ar' else 'Nouveau marché'}: {t['objet'][:50]}"
            await send_email(c['email'], subject, html)
            if c.get('telegram'):
                await send_telegram(c['telegram'],
                    f"🔔 *شبكة رصد*\n\n📋 *{t['objet'][:80]}*\n📅 {t['date_limite'] or '—'}\n🔗 {t['url']}")
            DB.execute("INSERT INTO notifications (contractor_id,tender_id,channel,sent_at) VALUES(?,?,?,?)",
                       (c['id'], t['id'], 'email', datetime.now().strftime("%Y-%m-%d %H:%M")))
            DB.execute("UPDATE contractors SET notif_count=notif_count+1 WHERE id=?", (c['id'],))
    DB.commit()

@asynccontextmanager
async def lifespan(app):
    asyncio.create_task(daily_scrape())
    yield

async def daily_scrape():
    while True:
        await asyncio.sleep(86400)
        print("[Scheduler] Running daily scrape...")
        new = await asyncio.get_event_loop().run_in_executor(None, scrape_sync)
        await notify_all(new)

app = FastAPI(lifespan=lifespan)
for d in ["static","static/css","static/js"]:
    Path(d).mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# ── Routes ───────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    stats = {
        "tenders":     DB.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif' OR statut IS NULL").fetchone()[0],
        "contractors": DB.execute("SELECT COUNT(*) FROM contractors").fetchone()[0],
        "cancelled":   DB.execute("SELECT COUNT(*) FROM tenders WHERE statut='annule'").fetchone()[0],
        "regions":     len(REGIONS),
    }
    recent      = DB.execute("SELECT * FROM tenders WHERE statut='actif' OR statut IS NULL ORDER BY date_extraction DESC LIMIT 6").fetchall()
    top_regions = DB.execute("SELECT region, COUNT(*) as cnt FROM tenders WHERE region!='' GROUP BY region ORDER BY cnt DESC LIMIT 12").fetchall()
    return templates.TemplateResponse("landing.html", {
        "request": request, "stats": stats,
        "recent": recent, "top_regions": top_regions,
        "REGIONS": REGIONS, "DOMAINS_FR": DOMAINS_FR,
    })

@app.get("/tenders", response_class=HTMLResponse)
async def tenders_list(request: Request, region: str="", domaine: str="",
    q: str="", statut: str="actif", page: int=1):
    per_page = 20
    offset   = (page-1)*per_page
    conds, params = ["1=1"], []
    if statut == "actif":  conds.append("(statut='actif' OR statut IS NULL)")
    elif statut == "annule": conds.append("statut='annule'")
    if region:  conds.append("region=?");  params.append(region)
    if domaine: conds.append("domaine=?"); params.append(domaine)
    if q:       conds.append("(objet LIKE ? OR acheteur LIKE ?)"); params += [f"%{q}%",f"%{q}%"]
    where = " AND ".join(conds)
    total = DB.execute(f"SELECT COUNT(*) FROM tenders WHERE {where}", params).fetchone()[0]
    rows  = DB.execute(f"SELECT * FROM tenders WHERE {where} ORDER BY date_extraction DESC LIMIT ? OFFSET ?",
                       params+[per_page,offset]).fetchall()
    pages = (total+per_page-1)//per_page
    return templates.TemplateResponse("tenders_public.html", {
        "request": request, "tenders": rows,
        "region": region, "domaine": domaine, "q": q, "statut": statut,
        "page": page, "pages": pages, "total": total,
        "REGIONS": REGIONS, "DOMAINS_FR": DOMAINS_FR, "DOMAINS_AR": DOMAINS_AR,
    })

@app.get("/tender/{tid}", response_class=HTMLResponse)
async def tender_detail(request: Request, tid: str):
    t = DB.execute("SELECT * FROM tenders WHERE id=?", (tid,)).fetchone()
    if not t: raise HTTPException(404)
    t = dict(t)
    clauses   = []
    try: clauses = json.loads(t['clauses'] or '[]')
    except: pass
    suppliers = get_suppliers(t['domaine']) if t['domaine'] in GOODS_DOMAINS else []
    return templates.TemplateResponse("tender_public.html", {
        "request": request, "tender": t, "clauses": clauses,
        "suppliers": suppliers, "REGIONS": REGIONS, "DOMAINS_AR": DOMAINS_AR,
    })

@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    return templates.TemplateResponse("register.html", {
        "request": request, "REGIONS": REGIONS,
        "DOMAINS_FR": DOMAINS_FR, "DOMAINS_AR": DOMAINS_AR,
    })

@app.post("/register")
async def register_submit(request: Request,
    nom: str=Form(...), entreprise: str=Form(""),
    phone: str=Form(...), email: str=Form(""),
    whatsapp: str=Form(""), telegram: str=Form(""), langue: str=Form("fr")):
    form     = await request.form()
    domaines = json.dumps(form.getlist("domaines"))
    regions  = json.dumps(form.getlist("regions"))
    token    = make_token(re.sub(r'\s+','',phone))
    try:
        DB.execute("""INSERT INTO contractors
            (nom,entreprise,phone,email,whatsapp,telegram,domaines,regions,langue,token,created_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (nom,entreprise,re.sub(r'\s+','',phone),email,whatsapp,telegram,
             domaines,regions,langue,token,datetime.now().strftime("%Y-%m-%d %H:%M")))
        DB.commit()
    except Exception as e:
        print(f"Register error: {e}")
    return RedirectResponse(f"/dashboard/{token}", status_code=302)

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/login")
async def login_submit(request: Request, phone: str=Form(...)):
    token = make_token(re.sub(r'\s+','',phone))
    c = DB.execute("SELECT * FROM contractors WHERE token=?", (token,)).fetchone()
    if not c:
        return templates.TemplateResponse("login.html", {
            "request": request, "error": "رقم الهاتف غير موجود. سجّل أولاً."})
    DB.execute("UPDATE contractors SET last_login=? WHERE token=?",
               (datetime.now().strftime("%Y-%m-%d %H:%M"), token))
    DB.commit()
    return RedirectResponse(f"/dashboard/{token}", status_code=302)

@app.get("/dashboard/{token}", response_class=HTMLResponse)
async def dashboard(request: Request, token: str):
    c = DB.execute("SELECT * FROM contractors WHERE token=?", (token,)).fetchone()
    if not c: raise HTTPException(404)
    c    = dict(c)
    lang = c.get('langue','fr')
    stats = {
        "total":   DB.execute("SELECT COUNT(*) FROM notifications WHERE contractor_id=?", (c['id'],)).fetchone()[0],
        "month":   DB.execute("SELECT COUNT(*) FROM notifications WHERE contractor_id=? AND sent_at LIKE ?",
                              (c['id'], datetime.now().strftime("%Y-%m")+"%")).fetchone()[0],
        "tenders": DB.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif' OR statut IS NULL").fetchone()[0],
    }
    recent = DB.execute("""SELECT t.* FROM tenders t
        JOIN notifications n ON t.id=n.tender_id
        WHERE n.contractor_id=? ORDER BY n.sent_at DESC LIMIT 5""", (c['id'],)).fetchall()
    all_active = DB.execute("SELECT * FROM tenders WHERE statut='actif' OR statut IS NULL ORDER BY date_extraction DESC LIMIT 20").fetchall()
    matching   = [t for t in all_active if match(c, dict(t))][:5]
    return templates.TemplateResponse("dashboard_contractor.html", {
        "request": request, "lang": lang, "contractor": c, "token": token,
        "stats": stats, "recent": recent, "matching": matching,
        "REGIONS": REGIONS, "DOMAINS_AR": DOMAINS_AR,
    })

@app.get("/profile/{token}", response_class=HTMLResponse)
async def profile_edit_page(request: Request, token: str):
    c = DB.execute("SELECT * FROM contractors WHERE token=?", (token,)).fetchone()
    if not c: raise HTTPException(404)
    c = dict(c)
    return templates.TemplateResponse("profile_edit.html", {
        "request": request, "lang": c.get('langue','fr'), "contractor": c, "token": token,
        "c_domaines": json.loads(c['domaines'] or '[]'),
        "c_regions":  json.loads(c['regions']  or '[]'),
        "REGIONS": REGIONS, "DOMAINS_FR": DOMAINS_FR, "DOMAINS_AR": DOMAINS_AR,
    })

@app.post("/profile/{token}")
async def profile_edit_submit(request: Request, token: str,
    nom: str=Form(...), entreprise: str=Form(""),
    email: str=Form(""), whatsapp: str=Form(""),
    telegram: str=Form(""), langue: str=Form("fr")):
    form     = await request.form()
    domaines = json.dumps(form.getlist("domaines"))
    regions  = json.dumps(form.getlist("regions"))
    DB.execute("""UPDATE contractors SET
        nom=?,entreprise=?,email=?,whatsapp=?,telegram=?,
        domaines=?,regions=?,langue=? WHERE token=?""",
        (nom,entreprise,email,whatsapp,telegram,domaines,regions,langue,token))
    DB.commit()
    return RedirectResponse(f"/dashboard/{token}", status_code=302)

@app.get("/upgrade", response_class=HTMLResponse)
async def upgrade_page(request: Request):
    return templates.TemplateResponse("upgrade.html", {"request": request})

@app.post("/upgrade")
async def upgrade_submit(request: Request,
    phone: str=Form(...), email: str=Form(""), method: str=Form("virement")):
    DB.execute("INSERT OR IGNORE INTO payment_requests (phone,email,method,created_at) VALUES(?,?,?,?)",
               (re.sub(r'\s+','',phone), email, method, datetime.now().strftime("%Y-%m-%d %H:%M")))
    DB.commit()
    return templates.TemplateResponse("merci.html", {"request": request})

@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request, pwd: str=""):
    if pwd != ADMIN_PASS:
        return templates.TemplateResponse("admin_login.html", {"request": request})
    stats = {
        "tenders":     DB.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif' OR statut IS NULL").fetchone()[0],
        "cancelled":   DB.execute("SELECT COUNT(*) FROM tenders WHERE statut='annule'").fetchone()[0],
        "contractors": DB.execute("SELECT COUNT(*) FROM contractors").fetchone()[0],
        "premium":     DB.execute("SELECT COUNT(*) FROM contractors WHERE plan='premium'").fetchone()[0],
        "notifs":      DB.execute("SELECT COUNT(*) FROM notifications").fetchone()[0],
        "pending":     DB.execute("SELECT COUNT(*) FROM payment_requests WHERE status='pending'").fetchone()[0],
        "payments":    DB.execute("SELECT COUNT(*) FROM payment_requests WHERE status='pending'").fetchone()[0],
    }
    contractors = DB.execute("SELECT * FROM contractors ORDER BY created_at DESC").fetchall()
    payments    = DB.execute("SELECT * FROM payment_requests WHERE status='pending' ORDER BY created_at DESC").fetchall()
    top_regions = DB.execute("SELECT region, COUNT(*) as cnt FROM tenders WHERE region!='' GROUP BY region ORDER BY cnt DESC").fetchall()
    return templates.TemplateResponse("admin.html", {
        "request": request, "pwd": pwd, "stats": stats,
        "contractors": contractors, "payments": payments,
        "top_regions": top_regions, "REGIONS": REGIONS,
    })

@app.get("/admin/activate")
async def admin_activate(phone: str, pwd: str=""):
    if pwd != ADMIN_PASS: raise HTTPException(403)
    phone_clean = re.sub(r'\s+','',phone)
    DB.execute("UPDATE contractors SET plan='premium' WHERE phone=?", (phone_clean,))
    DB.execute("UPDATE payment_requests SET status='paid' WHERE phone=?", (phone_clean,))
    DB.commit()
    c = DB.execute("SELECT * FROM contractors WHERE phone=?", (phone_clean,)).fetchone()
    if c:
        c = dict(c)
        await send_email(c.get('email'), "✅ تم تفعيل اشتراكك Premium — شبكة رصد",
            f"""<div style="text-align:center;padding:30px;font-family:Cairo,Arial">
            <h2 style="color:#8B4513">✅ تم تفعيل حسابك Premium!</h2>
            <p>مرحباً {c['nom']}، حسابك مفعّل الآن.</p>
            <a href="/dashboard/{c['token']}" style="background:#8B4513;color:white;padding:12px 24px;border-radius:8px;text-decoration:none">عرض ملفك الشخصي</a></div>""")
    return JSONResponse({"status": "ok"})

@app.get("/admin/scrape")
async def admin_scrape(pwd: str=""):
    if pwd != ADMIN_PASS: raise HTTPException(403)
    async def run():
        new = await asyncio.get_event_loop().run_in_executor(None, scrape_sync)
        await notify_all(new)
        print(f"[Scrape] {len(new)} new tenders")
    asyncio.create_task(run())
    return JSONResponse({"status": "Scraping lancé..."})

@app.get("/admin/cancel_check")
async def admin_cancel_check(pwd: str=""):
    if pwd != ADMIN_PASS: raise HTTPException(403)
    rows = DB.execute("SELECT id,objet,description FROM tenders WHERE statut='actif' OR statut IS NULL").fetchall()
    updated = 0
    for row in rows:
        if is_cancelled(f"{row['objet']} {row['description'] or ''}"):
            DB.execute("UPDATE tenders SET statut='annule' WHERE id=?", (row['id'],))
            updated += 1
    DB.commit()
    return JSONResponse({"updated": updated})

@app.get("/api/stats")
async def api_stats():
    return JSONResponse({
        "tenders":     DB.execute("SELECT COUNT(*) FROM tenders WHERE statut='actif' OR statut IS NULL").fetchone()[0],
        "cancelled":   DB.execute("SELECT COUNT(*) FROM tenders WHERE statut='annule'").fetchone()[0],
        "contractors": DB.execute("SELECT COUNT(*) FROM contractors").fetchone()[0],
        "premium":     DB.execute("SELECT COUNT(*) FROM contractors WHERE plan='premium'").fetchone()[0],
    })
