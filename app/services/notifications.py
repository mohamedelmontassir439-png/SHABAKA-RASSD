import json, logging, smtplib, requests as _req
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from app.core.config import cfg
from app.core.database import get_db
from app.core.security import days_left

logger = logging.getLogger("rassd.notif")

# ── Telegram ────────────────────────────────────────────

def tg_send(chat_id: str, text: str, parse_mode: str = "HTML") -> bool:
    if not cfg.TELEGRAM_BOT or not chat_id: return False
    try:
        r = _req.post(
            f"https://api.telegram.org/bot{cfg.TELEGRAM_BOT}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": parse_mode,
                  "disable_web_page_preview": False},
            timeout=8
        )
        return r.status_code == 200
    except Exception as e:
        logger.error(f"[TG] {e}"); return False

def tg_admin(msg: str):
    tg_send(cfg.ADMIN_CHAT_ID, f"🔔 <b>RASSD</b>\n{msg}")

def build_tg_message(t: dict) -> str:
    _, dl_label = days_left(t.get("date_limite", ""))
    lines = [
        f"🏛 <b>Nouveau Marché Public</b>",
        f"{'━' * 32}",
        f"",
        f"📋 <b>{t['objet'][:100]}</b>",
        f"",
    ]
    if t.get("acheteur"):  lines.append(f"🏢 {t['acheteur'][:60]}")
    if t.get("secteur"):   lines.append(f"🏷 {t['secteur']}")
    if t.get("region"):    lines.append(f"📍 {t['region']}")
    if t.get("montant"):   lines.append(f"💰 {t['montant']}")
    dl = t.get("date_limite", "")
    if dl:
        label = f" — <b>{dl_label}</b>" if dl_label else ""
        lines.append(f"⏰ <b>{dl}{label}</b>")
    lines += ["", f"🔗 <a href='{t['url']}'>Voir sur marchespublics.gov.ma</a>",
              f"📱 <a href='{cfg.SITE_URL}/tenders/{t['id']}'>Voir sur RASSD</a>",
              f"", f"<i>RASSD · Veille Marchés Publics Maroc</i>"]
    return "\n".join(lines)

# ── Email ────────────────────────────────────────────────

def email_send(to: str, subject: str, html: str) -> bool:
    if cfg.BREVO_KEY:
        try:
            r = _req.post(
                "https://api.brevo.com/v3/smtp/email",
                headers={"api-key": cfg.BREVO_KEY, "Content-Type": "application/json"},
                json={"sender": {"name": cfg.FROM_NAME, "email": cfg.FROM_EMAIL},
                      "to": [{"email": to}],
                      "subject": subject, "htmlContent": html},
                timeout=12
            )
            if r.status_code in (200, 201): return True
        except Exception as e:
            logger.error(f"[Brevo] {e}")
    if cfg.GMAIL_USER and cfg.GMAIL_PASS:
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"]    = f"{cfg.FROM_NAME} <{cfg.GMAIL_USER}>"
            msg["To"]      = to
            msg.attach(MIMEText(html, "html", "utf-8"))
            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as srv:
                srv.login(cfg.GMAIL_USER, cfg.GMAIL_PASS)
                srv.send_message(msg)
            return True
        except Exception as e:
            logger.error(f"[Gmail] {e}")
    return False

def build_email(t: dict, nom: str = "") -> str:
    dl  = t.get("date_limite", "—") or "—"
    _, dl_label = days_left(t.get("date_limite", ""))
    site = cfg.SITE_URL
    return f"""<!DOCTYPE html>
<html lang="fr"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:#07070e;font-family:'Georgia',serif;padding:20px}}
  .wrap{{max-width:600px;margin:0 auto;background:#0d0d15;border:1px solid #1e1e2c;border-radius:12px;overflow:hidden}}
  .hdr{{padding:28px 32px;border-bottom:1px solid #1e1e2c;display:flex;align-items:center;gap:14px}}
  .logo{{font-size:24px;font-weight:900;color:#c8a850;letter-spacing:3px;font-style:italic}}
  .body{{padding:32px}}
  .title{{font-size:18px;font-weight:700;color:#f0ede6;line-height:1.5;margin-bottom:20px}}
  .table{{width:100%;border-collapse:collapse;margin-bottom:24px}}
  .table td{{padding:10px 0;border-bottom:1px solid #1a1a26;vertical-align:top}}
  .lbl{{font-size:10px;color:#666;letter-spacing:1px;text-transform:uppercase;font-family:monospace;width:110px}}
  .val{{font-size:13px;color:#c8c4bc}}
  .val-g{{color:#c8a850;font-weight:700}}
  .val-r{{color:#e05c5c;font-weight:700}}
  .cta{{display:inline-block;margin:6px 6px 0 0;padding:12px 22px;background:#c8a850;color:#000;border-radius:6px;font-weight:700;text-decoration:none;font-size:13px}}
  .cta2{{display:inline-block;margin:6px 6px 0 0;padding:12px 22px;border:1px solid #c8a850;color:#c8a850;border-radius:6px;font-weight:700;text-decoration:none;font-size:13px}}
  .ftr{{padding:20px 32px;background:#070710;border-top:1px solid #1e1e2c;text-align:center}}
  .dl-badge{{display:inline-block;padding:6px 14px;background:rgba(200,168,80,.1);border:1px solid rgba(200,168,80,.3);border-radius:99px;font-size:12px;color:#c8a850;margin-bottom:20px}}
</style></head>
<body><div class="wrap">
  <div class="hdr">
    <div><div class="logo">RASSD</div><div style="font-size:10px;color:#555;letter-spacing:2px;font-family:monospace;margin-top:3px">MARCHÉS PUBLICS MAROC</div></div>
  </div>
  <div class="body">
    <p style="color:#888;font-size:13px;margin-bottom:20px">Bonjour {nom or 'Madame/Monsieur'},</p>
    <p style="color:#aaa;font-size:13px;margin-bottom:20px">Un nouveau marché correspondant à votre profil vient d'être publié :</p>
    {'<div class="dl-badge">⏰ ' + dl_label + '</div>' if dl_label else ''}
    <div class="title">{t['objet'][:180]}</div>
    <table class="table">
      <tr><td class="lbl">🏢 Acheteur</td><td class="val">{t.get('acheteur','—')[:80]}</td></tr>
      <tr><td class="lbl">🏷 Secteur</td><td class="val val-g">{t.get('secteur','—')}</td></tr>
      {'<tr><td class="lbl">📍 Région</td><td class="val">' + t.get("region","") + '</td></tr>' if t.get("region") else ''}
      {'<tr><td class="lbl">💰 Montant</td><td class="val">' + t.get("montant","") + '</td></tr>' if t.get("montant") else ''}
      <tr><td class="lbl">⏰ Date limite</td><td class="val val-r">{dl}</td></tr>
      <tr><td class="lbl">📅 Publication</td><td class="val">{t.get('date_publication','—')}</td></tr>
    </table>
    <div>
      <a href="{t['url']}" class="cta">Voir sur marchespublics ↗</a>
      <a href="{site}/tenders/{t['id']}" class="cta2">Détails RASSD</a>
    </div>
  </div>
  <div class="ftr">
    <p style="color:#444;font-size:11px">RASSD · <a href="{site}" style="color:#666">rassd.ma</a> · <a href="{site}/settings" style="color:#666">Gérer mes alertes</a></p>
  </div>
</div></body></html>"""


def build_verify_email(email: str, token: str, nom: str = "") -> str:
    site = cfg.SITE_URL
    label = nom or email
    return f"""<!DOCTYPE html>
<html lang=\"fr\"><head><meta charset=\"UTF-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><style>
  body{{background:#07070e;color:#f0ede8;font-family:Georgia,serif;padding:24px}}
  .card{{max-width:600px;margin:0 auto;background:#0d0d15;border:1px solid #1e1e2c;border-radius:16px;overflow:hidden}}
  .hdr{{padding:28px 32px;border-bottom:1px solid #1e1e2c}}
  .title{{font-size:22px;font-weight:700;color:#f0ede8;margin-bottom:16px}}
  .btn{{display:inline-block;padding:14px 18px;background:#d4a843;color:#000;border-radius:10px;text-decoration:none;font-weight:700}}
  .note{{color:#aaa;font-size:13px}}
</style></head><body><div class=\"card\">
  <div class=\"hdr\"><div class=\"title\">Confirmez votre adresse email</div></div>
  <div style=\"padding:28px 32px;color:#c8c4bc;font-size:14px;line-height:1.7\">
    <p>Bonjour {label},</p>
    <p>Merci de créer votre compte RASSD. Cliquez sur le bouton ci-dessous pour activer votre accès :</p>
    <p style=\"margin:24px 0\"><a href=\"{site}/verify-email?token={token}\" class=\"btn\">Vérifier mon email</a></p>
    <p class=\"note\">Si vous n'avez pas demandé cette validation, ignorez cet email.</p>
    <p class=\"note\">Si le lien ne fonctionne pas, copiez-collez cette URL dans votre navigateur :</p>
    <p class=\"note\"><a href=\"{site}/verify-email?token={token}\" style=\"color:#d4a843\">{site}/verify-email?token={token}</a></p>
  </div>
</div></body></html>"""


def build_reset_email(email: str, token: str, nom: str = "") -> str:
    site = cfg.SITE_URL
    label = nom or email
    return f"""<!DOCTYPE html>
<html lang=\"fr\"><head><meta charset=\"UTF-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><style>
  body{{background:#07070e;color:#f0ede8;font-family:Georgia,serif;padding:24px}}
  .card{{max-width:600px;margin:0 auto;background:#0d0d15;border:1px solid #1e1e2c;border-radius:16px;overflow:hidden}}
  .hdr{{padding:28px 32px;border-bottom:1px solid #1e1e2c}}
  .title{{font-size:22px;font-weight:700;color:#f0ede8;margin-bottom:16px}}
  .btn{{display:inline-block;padding:14px 18px;background:#d4a843;color:#000;border-radius:10px;text-decoration:none;font-weight:700}}
  .note{{color:#aaa;font-size:13px}}
</style></head><body><div class=\"card\">
  <div class=\"hdr\"><div class=\"title\">Réinitialiser votre mot de passe</div></div>
  <div style=\"padding:28px 32px;color:#c8c4bc;font-size:14px;line-height:1.7\">
    <p>Bonjour {label},</p>
    <p>Vous avez demandé à réinitialiser votre mot de passe. Cliquez sur le bouton ci-dessous pour définir un nouveau mot de passe :</p>
    <p style=\"margin:24px 0\"><a href=\"{site}/reset-password?token={token}\" class=\"btn\">Réinitialiser mon mot de passe</a></p>
    <p class=\"note\">Si vous n'avez pas demandé cette réinitialisation, ignorez cet email.</p>
    <p class=\"note\">Lien direct : <a href=\"{site}/reset-password?token={token}\" style=\"color:#d4a843\">{site}/reset-password?token={token}</a></p>
  </div>
</div></body></html>"""


# ── Engine principal ────────────────────────────────────

def dispatch_notifications(tenders: list):
    """Envoie les notifications pour chaque nouveau tender"""
    if not tenders: return
    db = get_db()
    try:
        members = db.execute(
            "SELECT * FROM members WHERE actif=1 AND (notif_email=1 OR notif_tg=1)"
        ).fetchall()
        total_sent = 0
        for m in members:
            member = dict(m)
            member_secteurs = json.loads(member.get("secteurs", "[]") or "[]")
            for t in tenders:
                # Filtre secteur
                if member_secteurs and t.get("secteur") not in member_secteurs:
                    continue
                # Dédup
                dup = db.execute(
                    "SELECT id FROM notif_log WHERE member_id=? AND tender_id=?",
                    (member["id"], t["id"])
                ).fetchone()
                if dup: continue
                # Envoyer
                if member["notif_tg"] and member["telegram"]:
                    ok = tg_send(member["telegram"], build_tg_message(t))
                    if ok:
                        db.execute(
                            "INSERT INTO notif_log(member_id,tender_id,channel,sent_at) VALUES(?,?,?,?)",
                            (member["id"], t["id"], "telegram", datetime.now().isoformat())
                        )
                        total_sent += 1
                if member["notif_email"] and member["email"]:
                    html = build_email(t, member.get("nom",""))
                    ok = email_send(member["email"], f"📋 Nouveau marché: {t['objet'][:60]}", html)
                    if ok:
                        db.execute(
                            "INSERT INTO notif_log(member_id,tender_id,channel,sent_at) VALUES(?,?,?,?)",
                            (member["id"], t["id"], "email", datetime.now().isoformat())
                        )
                        total_sent += 1
        db.commit()
        if total_sent > 0:
            logger.info(f"[Notif] {total_sent} notifications envoyées pour {len(tenders)} marchés")
            tg_admin(f"✅ <b>{len(tenders)} nouveaux marchés</b>\n{total_sent} notifications envoyées")
    finally:
        db.close()
