# ATLAS PRO v3.3 — Corrections & Améliorations

## 🔒 Sécurité
- SECRET_KEY: warning au démarrage si non configuré
- API /api/v1/tenders: rate limiting 60 req/min par IP
- API: authentification requise

## ⚡ Fonctionnalités
- Multi-scraper: activé (MULTI_OK = True)
- Export CSV: nouveau endpoint GET /export/csv (Pro+)
- Tarifs: page complète avec paiement WhatsApp
- WhatsApp: bouton flottant sur toutes les pages
- Startup: checks complets au démarrage

## 🛠 Variables Railway à configurer
```
SECRET_KEY = [générer: python -c "import secrets; print(secrets.token_hex(32))"]
PAYMENT_PHONE = 212621728813
PAYMENT_MSG = Bonjour, je veux m abonner ATLAS PRO
WA_ADMIN_PHONE = 0621728813
```

## 💾 Persistance DB Railway
Pour ne pas perdre les données à chaque deploy:
Railway Dashboard → Projet → New Volume → Mount: /app/data
Puis: DB_PATH=/app/data/atlas.db
