"""
SOURCE — Notifications v1.0
Telegram + Email + WhatsApp (wa.me link)
Matching sémantique STX10
"""
import json, logging, smtplib, requests as _req
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from app.core.config import cfg
from app.core.security import days_left
from app.core.stx10 import match_member, top3

logger = logging.getLogger("source.notif")

# ── Telegram ─────────────────────────────────────────────
def tg_send(chat_id: str, text: str) -> bool:
    if not cfg.TELEGRAM_BOT or not chat_id or not str(chat_id).strip():
        return False
    try:
        r = _req.post(
            f"https://api.telegram.org/bot{cfg.TELEGRAM_BOT}/sendMessage",
            json={"chat_id": str(chat_id).strip(), "text": text,
                  "parse_mode": "HTML", "disable_web_page_preview": False},
            timeout=10
        )
        return r.status_code == 200
    except Exception as e:
        logger.error(f"[TG] {e}")
        return False

def tg_admin(msg: str):
    if cfg.ADMIN_CHAT_ID:
        tg_send(cfg.ADMIN_CHAT_ID, f"🔔 <b>SOURCE</b>\n{msg}")

def _tg_message(t: dict, matched: list, member_lang: str = "fr") -> str:
    _, dl_label = days_left(t.get("date_limite",""))
    stx10 = t.get("stx10_code","")
    stx10_lbl = t.get("stx10_label","")

    if member_lang == "ar":
        lines = [
            "🏛 <b>فرصة جديدة — SOURCE</b>",
            "━" * 25,
            "",
            f"📋 <b>{t['objet'][:120]}</b>",
            "",
        ]
        if t.get("acheteur"): lines.append(f"🏢 {t['acheteur'][:80]}")
        if stx10:             lines.append(f"🏷 [{stx10}] {stx10_lbl[:60]}")
        if t.get("region"):   lines.append(f"📍 {t['region']}")
        if t.get("montant"):  lines.append(f"💰 {t['montant']}")
        if t.get("date_limite"):
            badge = f" — <b>{dl_label}</b>" if dl_label else ""
            lines.append(f"⏰ <b>{t['date_limite']}{badge}</b>")
        if matched: lines.append(f"✅ رموز STX10: {', '.join(matched)}")
        lines += ["", f"🔗 <a href='{cfg.SITE_URL}/tenders/{t['id']}'>عرض التفاصيل</a>",
                  "", "<i>SOURCE · المناقصات العمومية المغربية</i>"]
    else:
        lines = [
            "🏛 <b>Nouvelle Opportunité — SOURCE</b>",
            "━" * 28, "",
            f"📋 <b>{t['objet'][:120]}</b>", "",
        ]
        if t.get("acheteur"): lines.append(f"🏢 {t['acheteur'][:80]}")
        if stx10:             lines.append(f"🏷 [{stx10}] {stx10_lbl[:60]}")
        if t.get("region"):   lines.append(f"📍 {t['region']}")
        if t.get("montant"):  lines.append(f"💰 {t['montant']}")
        if t.get("date_limite"):
            badge = f" — <b>{dl_label}</b>" if dl_label else ""
            lines.append(f"⏰ <b>{t['date_limite']}{badge}</b>")
        if matched: lines.append(f"✅ Codes: {', '.join(matched)}")
        lines += ["", f"🔗 <a href='{cfg.SITE_URL}/tenders/{t['id']}'>Voir le détail</a>",
                  "", "<i>SOURCE · Marchés Publics Maroc</i>"]
    return "\n".join(lines)

# ── Email ─────────────────────────────────────────────────
def _email_send(to: str, subject: str, html: str) -> bool:
    if not to or "@" not in to: return False
    if cfg.BREVO_KEY:
        try:
            r = _req.post(
                "https://api.brevo.com/v3/smtp/email",
                headers={"api-key":cfg.BREVO_KEY,"Content-Type":"application/json"},
                json={"sender":{"name":cfg.FROM_NAME,"email":cfg.FROM_EMAIL},
                      "to":[{"email":to}],"subject":subject,"htmlContent":html},
                timeout=15)
            if r.status_code in (200,201,202): return True
        except Exception as e: logger.error(f"[Brevo] {e}")
    if cfg.GMAIL_USER and cfg.GMAIL_PASS:
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"]    = f"{cfg.FROM_NAME} <{cfg.GMAIL_USER}>"
            msg["To"]      = to
            msg.attach(MIMEText(html,"html","utf-8"))
            with smtplib.SMTP_SSL("smtp.gmail.com",465) as srv:
                srv.login(cfg.GMAIL_USER, cfg.GMAIL_PASS)
                srv.send_message(msg)
            return True
        except Exception as e: logger.error(f"[Gmail] {e}")
    return False

def _email_html(t: dict, nom: str = "", lang: str = "fr") -> str:
    _, dl_label = days_left(t.get("date_limite",""))
    dl = t.get("date_limite","—") or "—"
    badge = f'<span style="background:rgba(37,99,235,.1);border:1px solid rgba(37,99,235,.3);border-radius:99px;padding:4px 14px;font-size:12px;color:#3b82f6">⏰ {dl_label}</span>' if dl_label else ""
    is_ar = lang == "ar"
    dir_attr = 'dir="rtl"' if is_ar else ''
    greeting = f"السلام عليكم {nom}" if is_ar else f"Bonjour {nom or 'Madame/Monsieur'}"
    intro = "فرصة جديدة تطابق ملفكم:" if is_ar else "Une nouvelle opportunité correspondant à votre profil :"
    site_lbl = "عرض التفاصيل" if is_ar else "Voir le détail"
    mp_lbl = "marchespublics.gov.ma" if not is_ar else "البوابة الرسمية"
    footer_lbl = "إدارة تنبيهاتي" if is_ar else "Gérer mes alertes"

    return f"""<!DOCTYPE html>
<html {dir_attr}><head><meta charset="UTF-8"><style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#07070e;font-family:{'Tahoma,Arial' if is_ar else 'Georgia,serif'};padding:20px;direction:{'rtl' if is_ar else 'ltr'}}}
.wrap{{max-width:600px;margin:0 auto;background:#0d0d18;border:1px solid #1a1a28;border-radius:16px;overflow:hidden}}
.hdr{{padding:24px 28px;background:#080812;border-bottom:1px solid #1a1a28}}
.logo{{font-size:24px;font-weight:900;color:#3b82f6;letter-spacing:3px}}
.body{{padding:28px}}
.title{{font-size:17px;font-weight:700;color:#f0ede6;line-height:1.5;margin-bottom:20px}}
table{{width:100%;border-collapse:collapse;margin-bottom:24px}}
td{{padding:10px 0;border-bottom:1px solid #1a1a28;font-size:13px;vertical-align:top}}
.lbl{{color:#555;font-size:10px;letter-spacing:1px;text-transform:uppercase;width:120px}}
.val{{color:#c8c4bc}}.gold{{color:#3b82f6;font-weight:700}}.red{{color:#ef4444;font-weight:700}}
.cta{{display:inline-block;margin:4px;padding:12px 22px;background:#2563eb;color:#fff;border-radius:8px;font-weight:700;text-decoration:none;font-size:13px}}
.cta2{{display:inline-block;margin:4px;padding:12px 22px;border:1px solid #2563eb;color:#3b82f6;border-radius:8px;font-weight:700;text-decoration:none;font-size:13px}}
.ftr{{padding:18px 28px;text-align:center;border-top:1px solid #1a1a28}}
</style></head>
<body><div class="wrap">
<div class="hdr"><div class="logo">SOURCE</div><div style="font-size:10px;color:#444;letter-spacing:2px;margin-top:3px">MARCHÉS PUBLICS MAROC</div></div>
<div class="body">
<p style="color:#888;font-size:13px;margin-bottom:14px">{greeting},</p>
<p style="color:#aaa;font-size:13px;margin-bottom:20px">{intro}</p>
{badge and f'<div style="margin-bottom:18px">{badge}</div>' or ''}
<div class="title">{t.get("objet","")[:200]}</div>
<table>
<tr><td class="lbl">{'الجهة' if is_ar else 'Acheteur'}</td><td class="val">{t.get("acheteur","—")[:100]}</td></tr>
<tr><td class="lbl">STX10</td><td class="val gold">[{t.get("stx10_code","")}] {t.get("stx10_label","")[:60]}</td></tr>
<tr><td class="lbl">{'الجهة' if is_ar else 'Région'}</td><td class="val">{t.get("region","—")}</td></tr>
<tr><td class="lbl">{'الميزانية' if is_ar else 'Montant'}</td><td class="val">{t.get("montant","—")}</td></tr>
<tr><td class="lbl">{'الموعد' if is_ar else 'Date limite'}</td><td class="val red">{dl}</td></tr>
</table>
<a href="{cfg.SITE_URL}/tenders/{t['id']}" class="cta">{site_lbl} →</a>
<a href="{t.get('url','')}" class="cta2">{mp_lbl} ↗</a>
</div>
<div class="ftr"><p style="color:#444;font-size:11px">SOURCE · <a href="{cfg.SITE_URL}/settings" style="color:#555">{footer_lbl}</a></p></div>
</div></body></html>"""

# ── WhatsApp via wa.me (manuel) ───────────────────────────
def wa_link(phone: str, tender: dict, lang: str = "fr") -> str:
    """Génère un lien wa.me pour envoyer une notification manuelle"""
    import urllib.parse
    _, dl_label = days_left(tender.get("date_limite",""))
    if lang == "ar":
        msg = (f"مرحباً!\n\nفرصة جديدة عبر SOURCE:\n\n"
               f"📋 {tender.get('objet','')[:120]}\n"
               f"🏢 {tender.get('acheteur','')}\n"
               f"💰 {tender.get('montant','')}\n"
               f"⏰ {tender.get('date_limite','')} — {dl_label}\n\n"
               f"🔗 {cfg.SITE_URL}/tenders/{tender.get('id','')}")
    else:
        msg = (f"Bonjour!\n\nNouvelle opportunité via SOURCE:\n\n"
               f"📋 {tender.get('objet','')[:120]}\n"
               f"🏢 {tender.get('acheteur','')}\n"
               f"💰 {tender.get('montant','')}\n"
               f"⏰ {tender.get('date_limite','')} — {dl_label}\n\n"
               f"🔗 {cfg.SITE_URL}/tenders/{tender.get('id','')}")
    p = phone.strip().replace(" ","").replace("+","").replace("-","")
    if p.startswith("0") and len(p)==10: p = "212"+p[1:]
    return f"https://wa.me/{p}?text={urllib.parse.quote(msg)}"

# ── Dispatch principal ────────────────────────────────────
def dispatch(tenders: list, db) -> dict:
    if not tenders: return {"tg":0,"email":0,"wa":0,"skipped":0}
    total_tg = total_email = total_wa = total_skip = 0

    try:
        members = db.execute("SELECT * FROM members WHERE actif=1").fetchall()
        for m in members:
            member = dict(m)
            codes  = json.loads(member.get("stx10_codes","[]") or "[]")
            lang   = member.get("lang","fr")

            for t in tenders:
                text = f"{t.get('objet','')} {t.get('acheteur','')} {t.get('region','')}"

                # Matching sémantique STX10
                matched = match_member(text, codes) if codes else [t.get("stx10_code","")]

                if not matched: total_skip += 1; continue

                # Dédup
                if db.execute(
                    "SELECT id FROM notif_log WHERE member_id=? AND tender_id=?",
                    (member["id"], t["id"])
                ).fetchone(): continue

                now = datetime.now().isoformat()
                tender_dict = dict(t) if not isinstance(t, dict) else t

                # Telegram
                if member.get("notif_tg") and member.get("telegram"):
                    msg = _tg_message(tender_dict, matched, lang)
                    if tg_send(member["telegram"], msg):
                        db.execute("INSERT OR IGNORE INTO notif_log(member_id,tender_id,channel,sent_at) VALUES(?,?,?,?)",
                                   (member["id"],t["id"],"telegram",now))
                        total_tg += 1

                # Email
                if member.get("notif_email") and member.get("email"):
                    subj_fr = f"📋 Nouvelle opportunité: {tender_dict.get('objet','')[:60]}"
                    subj_ar = f"📋 فرصة جديدة: {tender_dict.get('objet','')[:60]}"
                    html = _email_html(tender_dict, member.get("nom",""), lang)
                    if _email_send(member["email"], subj_ar if lang=="ar" else subj_fr, html):
                        db.execute("INSERT OR IGNORE INTO notif_log(member_id,tender_id,channel,sent_at) VALUES(?,?,?,?)",
                                   (member["id"],t["id"],"email",now))
                        total_email += 1

                # Log WA si configuré
                if member.get("notif_wa") and member.get("whatsapp"):
                    db.execute("INSERT OR IGNORE INTO notif_log(member_id,tender_id,channel,sent_at) VALUES(?,?,?,?)",
                               (member["id"],t["id"],"whatsapp",now))
                    total_wa += 1

        db.commit()
        logger.info(f"[Notif] ✅ TG:{total_tg} Email:{total_email} WA:{total_wa} Skip:{total_skip}")
        if total_tg + total_email > 0:
            tg_admin(f"✅ <b>{len(tenders)} marchés</b>\n"
                     f"📱{total_tg} TG · 📧{total_email} Email · ⏭{total_skip} filtrés")

    except Exception as e:
        logger.error(f"[Notif] {e}", exc_info=True)

    return {"tg":total_tg,"email":total_email,"wa":total_wa,"skipped":total_skip}

def test_notif(email:str="", telegram_id:str="") -> dict:
    fake = {"id":"test_001","objet":"TEST — Construction bâtiment administratif R+3",
            "acheteur":"Ministère de l'Intérieur — TEST SOURCE",
            "stx10_code":"T101","stx10_label":"Travaux de construction et réhabilitation",
            "region":"Rabat-Salé","montant":"5 000 000 MAD",
            "date_limite":"30/12/2026","date_publication":datetime.now().strftime("%d/%m/%Y"),
            "url":"https://www.marchespublics.gov.ma"}
    results = {"telegram":False,"email":False}
    if telegram_id: results["telegram"] = tg_send(telegram_id, _tg_message(fake,[],  "fr"))
    if email: results["email"] = _email_send(email, "🧪 Test SOURCE", _email_html(fake,"Admin","fr"))
    return results
