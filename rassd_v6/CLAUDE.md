# ATLAS PRO v2.0 — Veille Marchés Publics Maroc

## v2.0 — CHANGELOG

### 🎨 Refonte design complète
- Identité visuelle éditoriale premium (inspirée Vesper)
- Typographie : Fraunces variable + Manrope + JetBrains Mono
- Palette : ink #0a0a0e + bone #f4ece0 + gold #d4a574
- Three.js sphère animée (landing), custom cursor, grain overlay
- Tous les 16 templates redessinés

### 🔍 Scraper v2.0 — 6 nouvelles sources (16 total)
- Marsa Maroc — autorité portuaire
- RADEEM — Régie Eau & Électricité Meknès
- LYDEC — Casablanca utilities
- Ministère de la Santé
- Ministère de l'Éducation
- Global-Marchés — UNIQUEMENT actualités publiques

### Position éthique sur le scraping
Le projet remonte aux sources ORIGINALES (organismes émetteurs)
plutôt que de scraper des agrégateurs payants. C'est :
- Plus rapide (pas d'intermédiaire)
- Plus exhaustif (toutes les sources, pas une sélection)
- 100% légal (données publiques par nature)
- Plus durable (pas de risque ToS / poursuites)

## Stack technique (inchangé)
- FastAPI + Python 3.11
- SQLite (data/atlas.db) WAL mode
- requests + BeautifulSoup
- Brevo + Telegram (notifications)
- Railway.app (hosting)

## Routes (toutes préservées)
- GET  /                     Landing
- GET  /tenders              Liste + filtres
- GET  /tenders/{id}         Détail
- POST /tenders/{id}/favorite
- GET  /favorites
- GET  /dashboard
- GET  /settings + POST
- GET  /tarifs
- GET  /register + POST
- GET  /login + POST
- GET  /forgot + POST
- GET  /reset + POST
- GET  /admin (cookie _admin)
- GET  /admin/scrape
- GET  /admin/scrape_stream  SSE
- GET  /api/v1/tenders

## CSS variables (toutes préservées pour compatibilité)
```
--bg, --bg2, --bg3, --bg4
--gold, --gold2, --gold3, --golda, --goldb
--text1..text4
--bdr, --bdr2
--grn, --red, --blue
--serif, --sans, --mono
--r, --r2, --r3, --r4
```

## Templates (16, tous v2.0)
- base.html, landing.html, tenders.html, detail.html
- dashboard.html, favorites.html, settings.html, tarifs.html
- login.html, register.html, forgot.html, reset.html
- admin.html, admin_login.html, feedback.html, 404.html
