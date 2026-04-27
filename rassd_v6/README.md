# SOURCE v2.1 — Marchés Publics Maroc

## 🚀 Quick Start

```bash
# 1. Clone and enter directory
cd source_v21_fixed

# 2. Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
# or: venv\Scripts\activate  # Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Set up environment variables
cp .env.example .env
# Edit .env with your values

# 5. Run the application
uvicorn main:app --host 0.0.0.0 --port 8000
```

## 🔒 Security Improvements (v2.1)

- ✅ **httpx** instead of requests (async-safe)
- ✅ **Connection pooling** via SQLAlchemy
- ✅ **Pydantic validation** on all inputs
- ✅ **Security headers** middleware (CSP, HSTS, etc.)
- ✅ **Rate limiting** on sensitive endpoints
- ✅ **Proper error handling** (no bare except)
- ✅ **Secure cookies** (httponly, secure, samesite)
- ✅ **Password strength validation**
- ✅ **HMAC signatures** for admin auth
- ✅ **SQL injection protection** (parameterized queries)

## 📁 Project Structure

```
source_v21_fixed/
├── main.py                  # Main FastAPI application
├── requirements.txt         # Dependencies
├── .env.example            # Environment variables template
├── app/
│   ├── core/
│   │   ├── config.py       # Configuration
│   │   ├── database.py     # Database layer
│   │   ├── security.py     # Security utilities
│   │   └── stx10.py        # STX10 classification
│   └── services/
│       ├── scraper.py      # Web scraper
│       └── notifications.py # Notification service
├── templates/              # Jinja2 templates
├── static/                 # Static files
└── data/                   # SQLite database
```

## 🛡️ Production Checklist

- [ ] Set strong SECRET_KEY (min 32 chars)
- [ ] Set strong ADMIN_PASS (min 12 chars)
- [ ] Set DEBUG=false
- [ ] Configure HTTPS
- [ ] Set up SMTP for email notifications
- [ ] Configure Telegram bot
- [ ] Set up Groq API key
- [ ] Run behind reverse proxy (nginx)
- [ ] Set up log rotation
- [ ] Configure backups

## 📄 License

Proprietary — All rights reserved.
