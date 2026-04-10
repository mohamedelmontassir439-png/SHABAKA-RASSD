import json, logging, smtplib, requests as _req
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from app.core.config   import cfg
from app.core.database import get_db
from app.core.security import days_left

logger = logging.getLogger("atlas.notif")

# ── Telegram ─────────────────────────────────────────────

def tg_send(chat_id: str, text: str, parse_mode: str = "HTML") -> bool:
    if not cfg.TELEGRAM_BOT:
        logger.warning("[TG] TELEGRAM_BOT non configuré")
        return False
    if not chat_id or not str(chat_id).strip():
        logger.warning("[TG] chat_id vide")
        return False
    try:
        r = _req.post(
            f"https://api.telegram.org/bot{cfg.TELEGRAM_BOT}/sendMessage",
            json={
                "chat_id":                  str(chat_id).strip(),
                "text":                     text,
                "parse_mode":               parse_mode,
                "disable_web_page_preview": False,
            },
            timeout=10
        )
        if r.status_code == 200:
            return True
        logger.error(f"[TG] Erreur {r.status_code}: {r.text[:200]}")
        return False
    except Exception as e:
        logger.error(f"[TG] Exception: {e}")
        return False

def tg_admin(msg: str):
    if cfg.ADMIN_CHAT_ID:
        tg_send(cfg.ADMIN_CHAT_ID, f"🔔 <b>ATLAS PRO</b>\n{msg}")

def build_tg_message(t: dict) -> str:
    _n, dl_label = days_left(t.get("date_limite", ""))
    lines = [
        "🏛 <b>Nouveau Marché Public</b>",
        "━" * 28,
        "",
        f"📋 <b>{t['objet'][:120]}</b>",
        "",
    ]
    if t.get("acheteur"): lines.append(f"🏢 {t['acheteur'][:70]}")
    if t.get("secteur"):  lines.append(f"🏷 {t['secteur']}")
    if t.get("region"):   lines.append(f"📍 {t['region']}")
    if t.get("montant"):  lines.append(f"💰 {t['montant']}")
    dl = t.get("date_limite", "")
    if dl:
        badge = f" — <b>{dl_label}</b>" if dl_label else ""
        lines.append(f"⏰ <b>{dl}{badge}</b>")
    lines += [
        "",
        f"🔗 <a href='{t['url']}'>Voir sur marchespublics.gov.ma</a>",
        f"📱 <a href='{cfg.SITE_URL}/tenders/{t['id']}'>Voir sur ATLAS PRO</a>",
        "",
        "<i>ATLAS PRO · Veille Marchés Publics Maroc</i>",
    ]
    return "\n".join(lines)

# ── Email ─────────────────────────────────────────────────

def email_send(to: str, subject: str, html: str) -> bool:
    if not to or "@" not in to:
        logger.warning(f"[Email] Adresse invalide: {to}")
        return False
    # Brevo
    if cfg.BREVO_KEY:
        try:
            r = _req.post(
                "https://api.brevo.com/v3/smtp/email",
                headers={"api-key": cfg.BREVO_KEY, "Content-Type": "application/json"},
                json={
                    "sender":      {"name": cfg.FROM_NAME, "email": cfg.FROM_EMAIL},
                    "to":          [{"email": to}],
                    "subject":     subject,
                    "htmlContent": html,
                },
                timeout=15
            )
            if r.status_code in (200, 201, 202):
                logger.info(f"[Brevo] ✅ Email envoyé à {to}")
                return True
            logger.error(f"[Brevo] Erreur {r.status_code}: {r.text[:200]}")
        except Exception as e:
            logger.error(f"[Brevo] Exception: {e}")
    # Gmail fallback
    if cfg.GMAIL_USER and cfg.GMAIL_PASS:
        try:
            msg             = MIMEMultipart("alternative")
            msg["Subject"]  = subject
            msg["From"]     = f"{cfg.FROM_NAME} <{cfg.GMAIL_USER}>"
            msg["To"]       = to
            msg.attach(MIMEText(html, "html", "utf-8"))
            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as srv:
                srv.login(cfg.GMAIL_USER, cfg.GMAIL_PASS)
                srv.send_message(msg)
            logger.info(f"[Gmail] ✅ Email envoyé à {to}")
            return True
        except Exception as e:
            logger.error(f"[Gmail] Exception: {e}")
    logger.error(f"[Email] Aucun provider configuré pour {to}")
    return False

def build_email(t: dict, nom: str = "") -> str:
    dl              = t.get("date_limite", "—") or "—"
    _n, dl_label    = days_left(t.get("date_limite", ""))
    site            = cfg.SITE_URL
    badge_html      = f'''<div class="dl-badge">⏰ {dl_label}</div>''' if dl_label else ""
    region_row      = f'<tr><td class="lbl">📍 Région</td><td class="val">{t.get("region","")}</td></tr>' if t.get("region") else ""
    montant_row     = f'<tr><td class="lbl">💰 Montant</td><td class="val">{t.get("montant","")}</td></tr>' if t.get("montant") else ""
    return f"""<!DOCTYPE html>
<html lang="fr"><head><meta charset="UTF-8">
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#07070e;font-family:Georgia,serif;padding:20px}}
.wrap{{max-width:600px;margin:0 auto;background:#0d0d15;border:1px solid #1e1e2c;border-radius:12px;overflow:hidden}}
.hdr{{padding:28px 32px;border-bottom:1px solid #1e1e2c}}
.logo{{font-size:22px;font-weight:900;color:#c8a850;letter-spacing:3px;font-style:italic}}
.body{{padding:32px}}
.title{{font-size:17px;font-weight:700;color:#f0ede6;line-height:1.5;margin-bottom:20px}}
table{{width:100%;border-collapse:collapse;margin-bottom:24px}}
td{{padding:10px 0;border-bottom:1px solid #1a1a26;vertical-align:top;font-size:13px}}
.lbl{{color:#666;letter-spacing:1px;text-transform:uppercase;font-family:monospace;width:110px;font-size:10px}}
.val{{color:#c8c4bc}}.val-g{{color:#c8a850;font-weight:700}}.val-r{{color:#e05c5c;font-weight:700}}
.cta{{display:inline-block;margin:6px 6px 0 0;padding:12px 22px;background:#c8a850;color:#000;border-radius:6px;font-weight:700;text-decoration:none;font-size:13px}}
.cta2{{display:inline-block;margin:6px 6px 0 0;padding:12px 22px;border:1px solid #c8a850;color:#c8a850;border-radius:6px;font-weight:700;text-decoration:none;font-size:13px}}
.ftr{{padding:20px 32px;background:#070710;border-top:1px solid #1e1e2c;text-align:center}}
.dl-badge{{display:inline-block;padding:6px 14px;background:rgba(200,168,80,.1);border:1px solid rgba(200,168,80,.3);border-radius:99px;font-size:12px;color:#c8a850;margin-bottom:20px}}
</style></head>
<body><div class="wrap">
<div class="hdr"><div class="logo">ATLAS PRO</div><div style="font-size:10px;color:#555;letter-spacing:2px;font-family:monospace;margin-top:3px">MARCHÉS PUBLICS MAROC</div></div>
<div class="body">
<p style="color:#888;font-size:13px;margin-bottom:16px">Bonjour {nom or "Madame/Monsieur"},</p>
<p style="color:#aaa;font-size:13px;margin-bottom:20px">Un nouveau marché correspondant à votre profil vient d'être publié :</p>
{badge_html}
<div class="title">{t["objet"][:200]}</div>
<table>
<tr><td class="lbl">🏢 Acheteur</td><td class="val">{t.get("acheteur","—")[:100]}</td></tr>
<tr><td class="lbl">🏷 Secteur</td><td class="val val-g">{t.get("secteur","—")}</td></tr>
{region_row}
{montant_row}
<tr><td class="lbl">⏰ Date limite</td><td class="val val-r">{dl}</td></tr>
<tr><td class="lbl">📅 Publication</td><td class="val">{t.get("date_publication","—")}</td></tr>
</table>
<a href="{t["url"]}" class="cta">Voir sur marchespublics ↗</a>
<a href="{site}/tenders/{t["id"]}" class="cta2">Détails ATLAS PRO</a>
</div>
<div class="ftr"><p style="color:#444;font-size:11px">ATLAS PRO · <a href="{site}" style="color:#666">atlas.ma</a> · <a href="{site}/settings" style="color:#666">Gérer mes alertes</a></p></div>
</div></body></html>"""

# ── Dispatch principal ────────────────────────────────────

def dispatch_notifications(tenders: list):
    if not tenders:
        return
    db = get_db()
    try:
        members = db.execute(
            "SELECT * FROM members WHERE actif=1"
        ).fetchall()
        total_tg = total_email = total_skip = 0

        for m in members:
            member          = dict(m)
            member_secteurs = json.loads(member.get("secteurs", "[]") or "[]")

            for t in tenders:
                # Filtre secteur
                if member_secteurs and t.get("secteur") not in member_secteurs:
                    total_skip += 1
                    continue
                # Dédup
                if db.execute(
                    "SELECT id FROM notif_log WHERE member_id=? AND tender_id=?",
                    (member["id"], t["id"])
                ).fetchone():
                    continue

                now = datetime.now().isoformat()

                # Telegram
                if member.get("notif_tg") and member.get("telegram"):
                    ok = tg_send(member["telegram"], build_tg_message(t))
                    if ok:
                        db.execute(
                            "INSERT INTO notif_log(member_id,tender_id,channel,sent_at) VALUES(?,?,?,?)",
                            (member["id"], t["id"], "telegram", now)
                        )
                        total_tg += 1
                    else:
                        logger.warning(f"[Notif] TG failed pour {member['email']}")

                # Email
                if member.get("notif_email") and member.get("email"):
                    html = build_email(t, member.get("nom", ""))
                    ok   = email_send(
                        member["email"],
                        f"📋 Nouveau marché: {t['objet'][:60]}",
                        html
                    )
                    if ok:
                        db.execute(
                            "INSERT INTO notif_log(member_id,tender_id,channel,sent_at) VALUES(?,?,?,?)",
                            (member["id"], t["id"], "email", now)
                        )
                        total_email += 1

        db.commit()
        logger.info(
            f"[Notif] ✅ {total_tg} TG + {total_email} Email "
            f"pour {len(tenders)} marchés ({total_skip} filtrés)"
        )
        if total_tg + total_email > 0:
            tg_admin(
                f"✅ <b>{len(tenders)} nouveaux marchés</b>\n"
                f"📱 {total_tg} Telegram · 📧 {total_email} Email"
            )
    except Exception as e:
        logger.error(f"[Notif] Exception: {e}", exc_info=True)
    finally:
        db.close()


def test_notifications(email: str = "", telegram_id: str = "") -> dict:
    """Test les notifications — appelé depuis /admin/test_notif"""
    results = {"telegram": False, "email": False}
    fake_tender = {
        "id":               "bdc_test",
        "objet":            "TEST — Marché de test ATLAS PRO",
        "acheteur":         "Administration Marocaine",
        "secteur":          "IT & Télécoms",
        "region":           "Rabat-Salé-Kénitra",
        "montant":          "100 000 MAD",
        "date_limite":      "30/12/2026",
        "date_publication": datetime.now().strftime("%d/%m/%Y"),
        "url":              "https://www.marchespublics.gov.ma",
    }
    if telegram_id:
        results["telegram"] = tg_send(telegram_id, build_tg_message(fake_tender))
    if email:
        html = build_email(fake_tender, "Administrateur")
        results["email"] = email_send(email, "🧪 Test ATLAS PRO — Notifications", html)
    return results
