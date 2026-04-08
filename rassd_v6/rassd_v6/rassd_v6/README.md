# Modern Business — Intelligence Marchés Publics Maroc

Plateforme SaaS de veille automatique des appels d'offres marocains.

## Architecture
- **Backend**: FastAPI + SQLite WAL
- **Scraper principal**: marchespublics.gov.ma (scan séquentiel IDs bdc_XXXXX)
- **Scraper local**: journaux marocains (IP Maroc requise)
- **Multi-source**: 10+ sources via multi_scraper.py
- **6 Agents IA**: Scraper · Classifier · Notify · Monitor · Chat · SelfHealing
- **Notifications**: Telegram + Email (Brevo)

## Déploiement Railway

Variables d'environnement requises:
```
ADMIN_PASS=rassd2026
SECRET_KEY=<random 64 chars>
TELEGRAM_BOT=<bot token>
ADMIN_CHAT_ID=<chat id>
BREVO_API_KEY=<optional>
ANTHROPIC_API_KEY=<optional>
```

## Scraper local (IP Maroc)
```bash
pip install requests beautifulsoup4 schedule
python local_scraper.py          # run normal
python local_scraper.py --test   # tester moteur de dates
python local_scraper.py --debug  # analyser structure sites
```

## Fix v10.2 — 2026-03-31
- `_parse()` entièrement réécrit avec `card_value()` 3 stratégies
- Filtre immédiat des offres expirées/annulées dans le parser
- Auto-expire robuste: ISO + DD/MM/YYYY + dates embarquées
- Extraction `Catégorie principale` officielle du portail
