# ATLAS PRO — Veille Marchés Publics Maroc

## Identité du projet
- **Nom**: ATLAS PRO
- **Mission**: Scraper marchespublics.gov.ma en temps réel et alerter les entreprises marocaines
- **URL**: https://web-production-b4ae4.up.railway.app
- **Repo**: mohamedelmontassir439-png/SHABAKA-ATLAS PRO (branch: main, root: atlas_v6/)
- **Admin**: atlas2026

## Stack technique
```
FastAPI + Python 3.11
SQLite (data/atlas.db) WAL mode
requests + BeautifulSoup (scraping)
Brevo + Telegram (notifications)
Railway.app (hosting)
```

## Architecture
```
atlas_v6/
├── main.py                      # FastAPI app - 31 routes
├── app/
│   ├── core/
│   │   ├── config.py           # Settings (cfg.ADMIN_PASS, cfg.TELEGRAM_BOT...)
│   │   ├── database.py         # Schema SQLite + init_db()
│   │   └── security.py         # Auth, hash_pw, verify_pw, days_left()
│   └── services/
│       ├── scraper.py          # Real-time scraper marchespublics
│       └── notifications.py    # Email (Brevo/Gmail) + Telegram
├── templates/                   # 12 templates Jinja2
│   ├── base.html               # Nav, fonts, CSS variables
│   ├── landing.html            # Page d'accueil
│   ├── tenders.html            # Liste marchés + filtres
│   ├── detail.html             # Détail marché + favoris
│   ├── dashboard.html          # Espace membre
│   ├── favorites.html          # Favoris
│   ├── register.html           # Inscription
│   ├── login.html              # Connexion
│   ├── settings.html           # Alertes + secteurs
│   ├── tarifs.html             # Page pricing
│   ├── admin.html              # Panel admin
│   └── admin_login.html        # Login admin
├── requirements.txt
├── nixpacks.toml               # cmd: uvicorn main:app
└── .python-version             # 3.11
```

## Variables d'environnement Railway
```
SITE_URL=https://web-production-b4ae4.up.railway.app
ADMIN_PASS=atlas2026
SECRET_KEY=...
DB_PATH=data/atlas.db
TELEGRAM_BOT=7849539613:AAF...
ADMIN_CHAT_ID=6424992854
BREVO_API_KEY=...
GMAIL_USER=...
GMAIL_PASS=...
SCAN_INTERVAL_MIN=60
```

## DB Schema (SQLite)
```sql
tenders:   id, objet, acheteur, secteur, region, montant,
           date_publication, date_limite, description,
           url, statut, views, scraped_at, updated_at

members:   id, nom, email, phone, company, pw_hash,
           plan, secteurs(JSON), telegram,
           notif_email, notif_tg, notif_digest,
           actif, created_at, trial_ends

favorites: id, member_id, tender_id, created_at
notif_log: id, member_id, tender_id, channel, sent_at
scrape_log:id, found, saved, errors, run_at
```

## Routes importantes
```
GET  /                     Landing + stats + derniers marchés
GET  /tenders              Liste avec filtres secteur/région/sort
GET  /tenders/{id}         Détail + favoris + marchés similaires
POST /tenders/{id}/favorite Toggle favori (JSON)
GET  /favorites            Favoris du membre connecté
GET  /dashboard            Espace personnel
GET  /settings             Gérer alertes + secteurs + Telegram
POST /settings             Sauvegarder (checkbox = form.get())
GET  /tarifs               Page pricing
GET  /register             Inscription (14j trial)
POST /register
GET  /login
POST /login
GET  /admin                Panel admin (cookie _admin)
GET  /admin/scrape         Lancer scan (async task)
GET  /admin/scrape_stream  SSE live logs
GET  /admin/expire         Expirer marchés passés
GET  /health               Status JSON
GET  /api/v1/tenders       API REST
GET  /sitemap.xml
GET  /robots.txt
```

## Scraper — Règles absolues
```python
SOURCE = "https://www.marchespublics.gov.ma"  # www. obligatoire
# Sans www. → DNS fail sur Railway

# Algorithme:
# 1. find_max_id() depuis page listing
# 2. Scan max_id-50 → max_id+200
# 3. Pour chaque ID:
#    - Parser HTML → objet depuis h2 (commence souvent par "#1Titre")
#    - Extraire date_limite depuis labels tableau ou texte
#    - RÈGLE: date_limite < today → return None (ignorer)
#    - Si "annulé"/"sans suite" → ignorer
# 4. TLSAdapter avec ssl.CERT_NONE (obligatoire Railway)
```

## Patterns courants à respecter

### Checkboxes dans les formulaires POST
```python
# ❌ MAUVAIS - ne capte pas les cases non cochées
notif_email: int = Form(0)

# ✅ BON - lire le form complet
form = await req.form()
n_email = 1 if form.get("notif_email") else 0
```

### Listes de secteurs
```python
# Toujours nettoyer
def clean_secteurs(raw: list) -> list:
    return list({s for s in raw if s and s.strip()})
```

### days_left retourne un tuple
```python
dl_n, dl_l = days_left("15/04/2026")
# dl_n = int (nombre de jours)
# dl_l = str (label: "3j 🔥", "Expiré", etc.)
```

### Admin auth
```python
# Cookie _admin = make_token("admin", ADMIN_PASS)
# Vérifier: _is_admin(req) dans chaque route admin
```

## Déploiement Railway
```powershell
# Depuis C:\Users\Lenovo\SHABAKA-ATLAS PRO
Expand-Archive "$env:USERPROFILE\Downloads\[FILE].zip" "." -Force
git add atlas_v6/
git commit -m "description"
git push origin main
```

## Plans
```python
PLANS = {
    "free":     {"tenders_day": 15,  "telegram": False, "api": False},
    "pro":      {"tenders_day": 0,   "telegram": True,  "api": True},
    "business": {"tenders_day": 0,   "telegram": True,  "api": True},
}
```

## Secteurs (16)
```
Travaux BTP, IT & Télécoms, Santé & Médical,
Transport & Véhicules, Services Généraux, Études & Conseil,
Formation, Restauration, Communication, Énergie,
Hydraulique, Fournitures Bureau, Mobilier,
Agriculture, Environnement, Autres
```

## Ce qui fonctionne (✅ testé en prod)
- Scraper: 203 marchés trouvés en un scan
- TLSAdapter: connexion Railway → marchespublics OK
- find_max_id(): détecte IDs autour de 323000+ (avril 2026)
- Parse objet depuis h2 (commence par "#1Titre")
- Filtre dates: rejette les expirations mars 2026

## Ce qui est en cours / à améliorer
- Export CSV des marchés filtrés
- Pagination API v1
- Webhook notifications (plan Business)
- Tests unitaires (scraper + routes)
- Rate limiting sur les routes publiques
