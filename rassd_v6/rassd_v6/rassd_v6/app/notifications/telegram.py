"""
Modern Business — Notifications Telegram
"""
import requests
from datetime import datetime
from app.core.config import cfg


def send(chat_id: str, text: str, parse_mode: str = "HTML") -> bool:
    if not cfg.TELEGRAM_BOT or not chat_id: return False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{cfg.TELEGRAM_BOT}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": parse_mode},
            timeout=8,
        )
        return r.status_code == 200
    except: return False


def notify_admin(msg: str) -> bool:
    return send(cfg.ADMIN_CHAT_ID, f"🔔 <b>Modern Business</b>\n{msg}")


def days_left(dl: str) -> str:
    import re
    from datetime import date
    m = re.search(r'(\d{2}/\d{2}/\d{4}|\d{4}-\d{2}-\d{2})', dl or "")
    if not m: return ""
    try:
        fmt = "%d/%m/%Y" if "/" in m.group(1)[:3] else "%Y-%m-%d"
        d = datetime.strptime(m.group(1), fmt).date()
        delta = (d - date.today()).days
        if delta < 0:  return "⚠️ Expiré"
        if delta == 0: return "⚡ Aujourd'hui!"
        if delta == 1: return "⚡ Demain!"
        if delta <= 3: return f"🔥 {delta}j"
        if delta <= 7: return f"⏳ {delta}j"
        return f"📅 {delta}j"
    except: return ""


def build_message(tenders: list, header: str) -> str:
    # Dedup
    seen = set(); uniq = []
    for t in tenders:
        key = t.get("objet","")[:60].lower()
        if key not in seen:
            seen.add(key); uniq.append(t)

    lines = [f"🏛 <b>{header}</b>\n{'━'*28}\n"]
    for t in uniq[:8]:
        dl   = t.get("date_limite","") or ""
        days = days_left(dl)
        sc   = t.get("ai_score", 0) or 0
        icon = "⭐" if sc >= 70 else "◑" if sc >= 40 else "○"
        b  = f"{icon} <b>{t.get('objet','')[:70]}</b>\n"
        if t.get("acheteur"): b += f"   🏢 {t['acheteur'][:50]}\n"
        if t.get("region"):   b += f"   📍 {t['region']}\n"
        if t.get("domaine"):  b += f"   🏷 {t['domaine'][:30]}\n"
        if dl:
            b += f"   ⏰ <b>{dl}"
            if days: b += f" — {days}"
            b += "</b>\n"
        if sc: b += f"   📊 Score: {sc}/100\n"
        url = t.get("url") or t.get("source_url","")
        if url: b += f"   🔗 {url}\n"
        lines.append(b)

    lines.append(f"\n🌐 {cfg.SITE_URL}/tenders")
    return "\n\n".join(lines)
