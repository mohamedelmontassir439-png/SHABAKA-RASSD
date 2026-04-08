"""
Modern Business — Notifications Email (Brevo + SMTP fallback)
"""
import smtplib, requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from app.core.config import cfg


def build_email_html(tenders: list, title: str) -> str:
    # Dedup
    seen = set(); uniq = []
    for t in tenders:
        key = t.get("objet","")[:60].lower()
        if key not in seen: seen.add(key); uniq.append(t)

    def card(t):
        dl = t.get("date_limite","—") or "—"
        sc = t.get("ai_score", 0) or 0
        sc_color = "#5a9e78" if sc >= 70 else "#c9a84c" if sc >= 40 else "#9e4a4a"
        url = t.get("url") or t.get("source_url","") or cfg.SITE_URL
        mon = (f'<tr><td style="color:#888;font-size:11px;padding:3px 0;width:130px">'
               f'💰 Montant</td><td style="color:#c9a84c;font-size:11px;font-weight:700">'
               f'{t.get("montant","")}</td></tr>') if t.get("montant") else ""
        return f"""<div style="border:1px solid #2a2a2a;border-radius:8px;padding:16px;margin-bottom:12px;background:#141414">
  <div style="font-size:14px;font-weight:700;color:#f0ede6;margin-bottom:8px">{t.get("objet","")[:100]}</div>
  {'<div style="display:inline-block;background:'+sc_color+'22;border:1px solid '+sc_color+'44;border-radius:99px;padding:2px 8px;font-size:9px;color:'+sc_color+';margin-bottom:8px">Score IA: '+str(sc)+'/100</div>' if sc else ''}
  <table style="width:100%;border-collapse:collapse;margin-top:6px">
    <tr><td style="color:#888;font-size:11px;padding:3px 0;width:130px">🏢 Acheteur</td><td style="color:#aaa;font-size:11px">{t.get("acheteur","—")[:60]}</td></tr>
    <tr><td style="color:#888;font-size:11px;padding:3px 0">📍 Région</td><td style="color:#aaa;font-size:11px">{t.get("region","—")}</td></tr>
    <tr><td style="color:#888;font-size:11px;padding:3px 0">🏷 Secteur</td><td style="color:#aaa;font-size:11px">{t.get("domaine","—")}</td></tr>
    {mon}
    <tr><td style="color:#888;font-size:11px;padding:3px 0">⏰ Limite</td><td style="color:#e87070;font-size:11px;font-weight:700">{dl}</td></tr>
  </table>
  <a href="{url}" style="display:inline-block;margin-top:10px;padding:6px 14px;background:#c9a84c;color:#000;border-radius:5px;font-weight:700;text-decoration:none;font-size:12px">Voir le marché →</a>
</div>"""

    cards = "".join(card(t) for t in uniq[:12])
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"></head>
<body style="margin:0;padding:20px;background:#080808;font-family:Georgia,serif">
<div style="max-width:640px;margin:0 auto;background:#0d0d0d;border-radius:12px;padding:32px">
  <div style="border-bottom:2px solid #c9a84c;padding-bottom:16px;margin-bottom:22px">
    <div style="font-size:20px;font-weight:700;color:#c9a84c">◆ Modern Business</div>
    <div style="font-size:11px;color:#555;margin-top:4px">{datetime.now().strftime("%d/%m/%Y à %H:%M")}</div>
  </div>
  <div style="font-size:17px;font-weight:700;color:#f0ede6;margin-bottom:18px">{title}</div>
  {cards}
  <div style="border-top:1px solid #222;padding-top:18px;margin-top:8px;text-align:center">
    <a href="{cfg.SITE_URL}/tenders" style="padding:10px 24px;background:#c9a84c;color:#000;border-radius:6px;font-weight:700;text-decoration:none;font-size:13px">Accéder à la plateforme →</a>
    <div style="font-size:10px;color:#333;margin-top:12px">Modern Business · Veille Marchés Publics Maroc</div>
  </div>
</div></body></html>"""


def send_brevo(to_email: str, subject: str, html: str) -> bool:
    if not cfg.BREVO_API_KEY: return False
    try:
        r = requests.post(
            "https://api.brevo.com/v3/smtp/email",
            headers={"api-key": cfg.BREVO_API_KEY, "Content-Type": "application/json"},
            json={
                "sender":  {"name":"Modern Business","email":"no-reply@modern-business.ma"},
                "to":      [{"email": to_email}],
                "subject": subject,
                "htmlContent": html,
            },
            timeout=10,
        )
        return r.status_code in (200, 201)
    except: return False


def send_gmail(to_email: str, subject: str, html: str) -> bool:
    if not cfg.GMAIL_USER or not cfg.GMAIL_PASS: return False
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = cfg.GMAIL_USER
        msg["To"]      = to_email
        msg.attach(MIMEText(html, "html"))
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as srv:
            srv.login(cfg.GMAIL_USER, cfg.GMAIL_PASS)
            srv.send_message(msg)
        return True
    except: return False


def send(to_email: str, subject: str, html: str) -> bool:
    """Essaie Brevo d'abord, puis Gmail."""
    return send_brevo(to_email, subject, html) or send_gmail(to_email, subject, html)
