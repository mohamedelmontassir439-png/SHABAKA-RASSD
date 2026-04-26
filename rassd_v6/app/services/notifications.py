"""SOURCE v2 — Notifications avec alertes urgence automatiques"""
import json, logging, smtplib, requests as _req
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from app.core.config import cfg
from app.core.security import days_left
from app.core.stx10 import match_member, top3

logger = logging.getLogger("source.notif")

def tg_send(chat_id: str, text: str) -> bool:
    if not cfg.TELEGRAM_BOT or not chat_id: return False
    try:
        r = _req.post(
            f"https://api.telegram.org/bot{cfg.TELEGRAM_BOT}/sendMessage",
            json={"chat_id":str(chat_id),"text":text,"parse_mode":"HTML"},
            timeout=10)
        return r.status_code == 200
    except Exception as e:
        logger.error(f"[TG] {e}"); return False

def tg_admin(msg: str):
    if cfg.ADMIN_CHAT_ID:
        tg_send(cfg.ADMIN_CHAT_ID, f"🔔 <b>SOURCE</b>\n{msg}")

def _email_send(to: str, subject: str, html: str) -> bool:
    if not to or "@" not in to: return False
    if cfg.BREVO_KEY:
        try:
            r = _req.post("https://api.brevo.com/v3/smtp/email",
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

def _tg_message(t: dict, matched: list, lang: str = "fr") -> str:
    _, dl_label = days_left(t.get("date_limite",""))
    if lang == "ar":
        lines = ["🏛 <b>فرصة جديدة — SOURCE</b>","━"*24,"",
                 f"📋 <b>{t['objet'][:120]}</b>",""]
        if t.get("acheteur"):  lines.append(f"🏢 {t['acheteur'][:80]}")
        if t.get("stx10_code"): lines.append(f"🏷 [{t['stx10_code']}] {t.get('stx10_label','')[:60]}")
        if t.get("region"):    lines.append(f"📍 {t['region']}")
        if t.get("montant"):   lines.append(f"💰 {t['montant']}")
        if t.get("date_limite"):
            badge = f" — <b>{dl_label}</b>" if dl_label else ""
            lines.append(f"⏰ <b>{t['date_limite']}{badge}</b>")
        lines += ["",f"🔗 <a href='{cfg.SITE_URL}/tenders/{t['id']}'>عرض التفاصيل</a>","",
                  "<i>SOURCE · المناقصات العمومية المغربية</i>"]
    else:
        lines = ["🏛 <b>Nouvelle Opportunité — SOURCE</b>","━"*28,"",
                 f"📋 <b>{t['objet'][:120]}</b>",""]
        if t.get("acheteur"):  lines.append(f"🏢 {t['acheteur'][:80]}")
        if t.get("stx10_code"): lines.append(f"🏷 [{t['stx10_code']}] {t.get('stx10_label','')[:60]}")
        if t.get("region"):    lines.append(f"📍 {t['region']}")
        if t.get("montant"):   lines.append(f"💰 {t['montant']}")
        if t.get("date_limite"):
            badge = f" — <b>{dl_label}</b>" if dl_label else ""
            lines.append(f"⏰ <b>{t['date_limite']}{badge}</b>")
        if matched: lines.append(f"✅ Codes: {', '.join(matched)}")
        lines += ["",f"🔗 <a href='{cfg.SITE_URL}/tenders/{t['id']}'>Voir le détail</a>","",
                  "<i>SOURCE · Marchés Publics Maroc</i>"]
    return "\n".join(lines)

def _urgent_message(t: dict, n: int, lang: str = "fr") -> str:
    if lang == "ar":
        return (f"🚨 <b>تحذير عاجل — SOURCE</b>\n\n"
                f"⏰ <b>{n} {'يوم' if n>1 else 'أيام'} فقط متبقية!</b>\n\n"
                f"📋 {t['objet'][:100]}\n"
                f"🏢 {t.get('acheteur','')[:70]}\n"
                f"📅 التسليم: {t.get('date_limite','')}\n\n"
                f"🔗 <a href='{cfg.SITE_URL}/tenders/{t['id']}'>تقدم الآن ←</a>")
    return (f"🚨 <b>URGENT — SOURCE</b>\n\n"
            f"⏰ <b>Plus que {n} {'jour' if n==1 else 'jours'}!</b>\n\n"
            f"📋 {t['objet'][:100]}\n"
            f"🏢 {t.get('acheteur','')[:70]}\n"
            f"📅 Clôture: {t.get('date_limite','')}\n\n"
            f"🔗 <a href='{cfg.SITE_URL}/tenders/{t['id']}'>Postuler maintenant →</a>")

def _email_html(t: dict, nom: str = "", lang: str = "fr") -> str:
    _, dl_label = days_left(t.get("date_limite",""))
    dl = t.get("date_limite","—") or "—"
    is_ar = lang == "ar"
    dir_attr = 'dir="rtl"' if is_ar else ''
    return f"""<!DOCTYPE html>
<html {dir_attr}><head><meta charset="UTF-8">
<style>*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#07060a;font-family:{'Tahoma,Arial' if is_ar else 'Georgia,serif'};padding:20px}}
.wrap{{max-width:600px;margin:0 auto;background:#0e0d14;border:1px solid rgba(200,169,110,.2);border-radius:16px;overflow:hidden}}
.hdr{{padding:24px 28px;background:#09080f;border-bottom:1px solid rgba(200,169,110,.15)}}
.logo{{font-size:22px;font-weight:900;color:#c8a96e;letter-spacing:3px}}
.body{{padding:28px}}
.title{{font-size:17px;font-weight:700;color:#f0ede6;line-height:1.5;margin-bottom:20px}}
table{{width:100%;border-collapse:collapse;margin-bottom:24px}}
td{{padding:10px 0;border-bottom:1px solid #1a1828;font-size:13px}}
.lbl{{color:#555;font-size:10px;letter-spacing:1px;text-transform:uppercase;width:110px}}
.val{{color:#c8c4bc}}.gold{{color:#c8a96e;font-weight:700}}.red{{color:#ef4444;font-weight:700}}
.cta{{display:inline-block;margin:4px;padding:12px 22px;background:#c8a96e;color:#000;border-radius:8px;font-weight:700;text-decoration:none;font-size:13px}}
.ftr{{padding:16px 28px;text-align:center;border-top:1px solid #1a1828}}
</style></head>
<body><div class="wrap">
<div class="hdr"><div class="logo">SOURCE</div>
<div style="font-size:10px;color:#444;margin-top:3px;letter-spacing:2px">MARCHÉS PUBLICS MAROC</div></div>
<div class="body">
<p style="color:#888;font-size:13px;margin-bottom:14px">{'السلام عليكم' if is_ar else 'Bonjour'} {nom or 'Madame/Monsieur'},</p>
<div class="title">{t.get('objet','')[:200]}</div>
<table>
<tr><td class="lbl">{'الجهة' if is_ar else 'Acheteur'}</td><td class="val">{t.get('acheteur','—')[:100]}</td></tr>
<tr><td class="lbl">STX10</td><td class="val gold">[{t.get('stx10_code','')}] {t.get('stx10_label','')[:60]}</td></tr>
<tr><td class="lbl">{'الجهة' if is_ar else 'Région'}</td><td class="val">{t.get('region','—')}</td></tr>
<tr><td class="lbl">{'الميزانية' if is_ar else 'Montant'}</td><td class="val">{t.get('montant','—')}</td></tr>
<tr><td class="lbl">{'الموعد' if is_ar else 'Date limite'}</td><td class="val red">{dl}</td></tr>
</table>
<a href="{cfg.SITE_URL}/tenders/{t['id']}" class="cta">{'عرض التفاصيل ←' if is_ar else 'Voir le détail →'}</a>
</div>
<div class="ftr"><p style="color:#444;font-size:11px">SOURCE · <a href="{cfg.SITE_URL}/settings" style="color:#555">{'إدارة التنبيهات' if is_ar else 'Gérer mes alertes'}</a></p></div>
</div></body></html>"""

def dispatch(tenders: list, db) -> dict:
    if not tenders: return {"tg":0,"email":0,"skip":0}
    total_tg = total_email = total_skip = 0
    try:
        members = db.execute("SELECT * FROM members WHERE actif=1").fetchall()
        for m in members:
            member = dict(m)
            codes  = json.loads(member.get("stx10_codes","[]") or "[]")
            regions= json.loads(member.get("regions","[]") or "[]")
            lang   = member.get("lang","fr")
            for t in tenders:
                text = f"{t.get('objet','')} {t.get('acheteur','')} {t.get('region','')}"
                matched = match_member(text, codes) if codes else [t.get("stx10_code","")]
                if not matched: total_skip += 1; continue
                if db.execute(
                    "SELECT id FROM notif_log WHERE member_id=? AND tender_id=?",
                    (member["id"], t["id"])
                ).fetchone(): continue
                now = datetime.now().isoformat()
                tender = dict(t) if not isinstance(t,dict) else t
                if member.get("notif_tg") and member.get("telegram"):
                    if tg_send(member["telegram"], _tg_message(tender,matched,lang)):
                        db.execute("INSERT OR IGNORE INTO notif_log(member_id,tender_id,channel,sent_at) VALUES(?,?,?,?)",
                                   (member["id"],t["id"],"telegram",now))
                        total_tg += 1
                if member.get("notif_email") and member.get("email"):
                    subj = f"📋 {'فرصة جديدة' if lang=='ar' else 'Nouvelle opportunité'}: {tender.get('objet','')[:60]}"
                    if _email_send(member["email"], subj, _email_html(tender, member.get("nom",""), lang)):
                        db.execute("INSERT OR IGNORE INTO notif_log(member_id,tender_id,channel,sent_at) VALUES(?,?,?,?)",
                                   (member["id"],t["id"],"email",now))
                        total_email += 1
        db.commit()
        logger.info(f"[Notif] ✅ TG:{total_tg} Email:{total_email} Skip:{total_skip}")
        if total_tg+total_email > 0:
            tg_admin(f"✅ <b>{len(tenders)} marchés</b> → TG:{total_tg} Email:{total_email}")
    except Exception as e:
        logger.error(f"[Notif] {e}", exc_info=True)
    return {"tg":total_tg,"email":total_email,"skip":total_skip}

def send_urgent_alerts(db):
    """Alertes automatiques J-3 et J-1 pour marchés en favoris/pipeline"""
    try:
        members = db.execute("SELECT * FROM members WHERE actif=1 AND notif_tg=1 AND telegram!=''").fetchall()
        sent = 0
        for m in members:
            member = dict(m)
            # Marchés en pipeline ou favoris
            watched = db.execute("""
                SELECT DISTINCT t.* FROM tenders t
                LEFT JOIN submissions s ON s.tender_id=t.id AND s.member_id=?
                LEFT JOIN favorites f ON f.tender_id=t.id AND f.member_id=?
                WHERE t.statut='actif' AND t.date_limite!=''
                AND (s.member_id IS NOT NULL OR f.member_id IS NOT NULL)
            """, (member["id"], member["id"])).fetchall()
            for row in watched:
                t = dict(row)
                n, _ = days_left(t.get("date_limite",""))
                if n not in (1, 3): continue
                if db.execute("SELECT id FROM urgent_alerts WHERE member_id=? AND tender_id=?",
                              (member["id"],t["id"])).fetchone(): continue
                msg = _urgent_message(t, n, member.get("lang","fr"))
                if tg_send(member["telegram"], msg):
                    db.execute("INSERT OR IGNORE INTO urgent_alerts(member_id,tender_id,sent_at) VALUES(?,?,?)",
                               (member["id"],t["id"],datetime.now().isoformat()))
                    sent += 1
        db.commit()
        if sent: logger.info(f"[Urgent] {sent} alertes envoyées")
    except Exception as e:
        logger.error(f"[Urgent] {e}")

def test_notif(email: str = "", telegram_id: str = "") -> dict:
    fake = {"id":"test_001","objet":"TEST — Construction bâtiment administratif R+3",
            "acheteur":"Ministère de l'Intérieur","stx10_code":"T101",
            "stx10_label":"Travaux de construction et réhabilitation de bâtiments",
            "region":"Rabat-Salé","montant":"5 000 000 MAD",
            "date_limite":"30/12/2026","date_publication":datetime.now().strftime("%d/%m/%Y")}
    results = {"telegram":False,"email":False}
    if telegram_id: results["telegram"] = tg_send(telegram_id, _tg_message(fake,[],"fr"))
    if email: results["email"] = _email_send(email,"🧪 Test SOURCE",_email_html(fake,"Admin","fr"))
    return results
