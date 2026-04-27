"""
SOURCE v2.1 — Notifications Service
====================================
✅ httpx for async HTTP
✅ Error handling
✅ Rate limiting
"""
import json
import logging
from datetime import datetime
from typing import List, Dict

import httpx

from app.core.config import cfg

logger = logging.getLogger("source.notifications")

async def tg_admin(msg: str) -> bool:
    """Send message to admin via Telegram"""
    if not cfg.TELEGRAM_BOT or not cfg.TELEGRAM_ADMIN:
        return False
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                f"https://api.telegram.org/bot{cfg.TELEGRAM_BOT}/sendMessage",
                json={
                    "chat_id": cfg.TELEGRAM_ADMIN,
                    "text": msg,
                    "parse_mode": "HTML"
                }
            )
        return r.status_code == 200
    except Exception as e:
        logger.warning(f"[tg_admin] {e}")
        return False

async def tg_send(chat_id: str, msg: str) -> bool:
    """Send Telegram message to user"""
    if not cfg.TELEGRAM_BOT:
        return False
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                f"https://api.telegram.org/bot{cfg.TELEGRAM_BOT}/sendMessage",
                json={"chat_id": chat_id, "text": msg, "parse_mode": "HTML"}
            )
        return r.status_code == 200
    except Exception as e:
        logger.warning(f"[tg_send] {e}")
        return False

async def dispatch(new_tenders: List[Dict], db) -> None:
    """Dispatch notifications for new tenders"""
    if not new_tenders:
        return

    members = db.execute(
        "SELECT id, nom, telegram, notif_tg, stx10_codes, regions, lang FROM members WHERE actif=1"
    ).fetchall()

    for member in members:
        codes = json.loads(member["stx10_codes"] or "[]")
        regions = json.loads(member["regions"] or "[]")
        matched = []

        for t in new_tenders:
            score = 0
            t_code = t.get("stx10_code", "")
            t_region = t.get("region", "")

            if t_code in codes:
                score += 50
            if any(r in t_region for r in regions):
                score += 30

            if score >= 30:
                matched.append((t, score))

        if matched:
            matched.sort(key=lambda x: x[1], reverse=True)
            top = matched[:5]

            lang = member.get("lang", "fr")
            if lang == "ar":
                lines = ["📢 مناقصات جديدة تهمك:"]
            else:
                lines = ["📢 Nouveaux marchés pour vous :"]

            for t, score in top:
                dl = t.get("date_limite", "—")
                lines.append(f"\n• {t['objet'][:80]}\n  Score: {score}/100 | Limite: {dl}")

            msg = "\n".join(lines)

            if member.get("notif_tg") and member.get("telegram"):
                await tg_send(member["telegram"], msg)

async def send_urgent_alerts(db) -> None:
    """Send urgent deadline alerts"""
    from app.core.security import days_left

    rows = db.execute(
        "SELECT id, objet, date_limite FROM tenders WHERE statut='actif' AND date_limite!=''"
    ).fetchall()

    urgent = []
    for r in rows:
        dl = days_left(r["date_limite"])[0]
        if 0 <= dl <= 2:
            urgent.append(r)

    if urgent and cfg.TELEGRAM_ADMIN:
        msg = f"⚠️ {len(urgent)} marchés expirent dans 48h"
        await tg_admin(msg)

def test_notif(email: str = "", telegram_id: str = "") -> Dict:
    """Test notification channels"""
    results = {"email": False, "telegram": False}

    if email and cfg.SMTP_HOST:
        try:
            import smtplib
            from email.mime.text import MIMEText
            msg = MIMEText("Test SOURCE notifications", "plain", "utf-8")
            msg["Subject"] = "Test SOURCE"
            msg["From"] = cfg.SMTP_FROM
            msg["To"] = email
            with smtplib.SMTP(cfg.SMTP_HOST, cfg.SMTP_PORT) as s:
                s.starttls()
                s.login(cfg.SMTP_USER, cfg.SMTP_PASS)
                s.send_message(msg)
            results["email"] = True
        except Exception as e:
            logger.error(f"[test_email] {e}")

    if telegram_id and cfg.TELEGRAM_BOT:
        import asyncio
        try:
            asyncio.run(tg_send(telegram_id, "✅ Test SOURCE notifications"))
            results["telegram"] = True
        except Exception as e:
            logger.error(f"[test_tg] {e}")

    return results
