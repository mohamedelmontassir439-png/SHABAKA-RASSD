"""SOURCE — Notifications v2 — TG + Email + WhatsApp"""
import json, logging, smtplib, urllib.parse, requests as _req
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from app.core.config import cfg
from app.core.security import days_left
from app.core.stx10 import match_member, top3
logger = logging.getLogger("source.notif")

def tg_send(chat_id, text):
    if not cfg.TELEGRAM_BOT or not chat_id: return False
    try:
        r = _req.post(f"https://api.telegram.org/bot{cfg.TELEGRAM_BOT}/sendMessage",
            json={"chat_id":str(chat_id).strip(),"text":text,"parse_mode":"HTML"},timeout=10)
        return r.status_code==200
    except Exception as e: logger.error(f"[TG] {e}"); return False

def tg_admin(msg):
    if cfg.ADMIN_CHAT_ID: tg_send(cfg.ADMIN_CHAT_ID,f"🔔 <b>SOURCE</b>\n{msg}")

def _tg_msg(t, matched=None, lang="fr"):
    _,dl = days_left(t.get("date_limite",""))
    if lang=="ar":
        lines=["🏛 <b>فرصة جديدة — SOURCE</b>","━"*24,"",
               f"📋 <b>{t.get('objet','')[:120]}</b>",""]
        if t.get("acheteur"): lines.append(f"🏢 {t['acheteur'][:80]}")
        if t.get("stx10_code"): lines.append(f"🏷 [{t['stx10_code']}] {t.get('stx10_label','')[:60]}")
        if t.get("region"): lines.append(f"📍 {t['region']}")
        if t.get("montant"): lines.append(f"💰 {t['montant']}")
        if t.get("date_limite"): lines.append(f"⏰ <b>{t['date_limite']}{' — '+dl if dl else ''}</b>")
        if matched: lines.append(f"✅ {', '.join(matched)}")
        lines+=["",f"🔗 <a href='{cfg.SITE_URL}/tenders/{t['id']}'>عرض التفاصيل</a>","","<i>SOURCE · المناقصات العمومية المغربية</i>"]
    else:
        lines=["🏛 <b>Nouvelle Opportunité — SOURCE</b>","━"*26,"",
               f"📋 <b>{t.get('objet','')[:120]}</b>",""]
        if t.get("acheteur"): lines.append(f"🏢 {t['acheteur'][:80]}")
        if t.get("stx10_code"): lines.append(f"🏷 [{t['stx10_code']}] {t.get('stx10_label','')[:60]}")
        if t.get("region"): lines.append(f"📍 {t['region']}")
        if t.get("montant"): lines.append(f"💰 {t['montant']}")
        if t.get("date_limite"): lines.append(f"⏰ <b>{t['date_limite']}{' — '+dl if dl else ''}</b>")
        if matched: lines.append(f"✅ Codes: {', '.join(matched)}")
        lines+=["",f"🔗 <a href='{cfg.SITE_URL}/tenders/{t['id']}'>Voir le détail</a>","","<i>SOURCE · Marchés Publics Maroc</i>"]
    return "\n".join(lines)

def _email_send(to, subj, html):
    if not to or "@" not in to: return False
    if cfg.BREVO_KEY:
        try:
            r=_req.post("https://api.brevo.com/v3/smtp/email",
                headers={"api-key":cfg.BREVO_KEY,"Content-Type":"application/json"},
                json={"sender":{"name":cfg.FROM_NAME,"email":cfg.FROM_EMAIL},
                      "to":[{"email":to}],"subject":subj,"htmlContent":html},timeout=15)
            if r.status_code in(200,201,202): return True
        except: pass
    if cfg.GMAIL_USER and cfg.GMAIL_PASS:
        try:
            msg=MIMEMultipart("alternative"); msg["Subject"]=subj
            msg["From"]=f"{cfg.FROM_NAME} <{cfg.GMAIL_USER}>"; msg["To"]=to
            msg.attach(MIMEText(html,"html","utf-8"))
            with smtplib.SMTP_SSL("smtp.gmail.com",465) as s:
                s.login(cfg.GMAIL_USER,cfg.GMAIL_PASS); s.send_message(msg)
            return True
        except: pass
    return False

def _email_html(t, nom="", lang="fr"):
    _,dl=days_left(t.get("date_limite",""))
    is_ar=lang=="ar"
    dir_a='dir="rtl"' if is_ar else ''
    return f"""<!DOCTYPE html><html {dir_a}><head><meta charset="UTF-8"></head>
<body style="background:#020408;font-family:{'Tahoma' if is_ar else 'Georgia'},serif;padding:20px">
<div style="max-width:580px;margin:0 auto;background:#0d1520;border:1px solid #1a2a3a;border-radius:16px;overflow:hidden">
<div style="padding:22px 28px;background:#080f1a;border-bottom:1px solid #1a2a3a">
<div style="font-size:22px;font-weight:900;color:#3b82f6;letter-spacing:3px">SOURCE</div>
<div style="font-size:9px;color:#444;letter-spacing:2px">MARCHÉS PUBLICS MAROC</div>
</div>
<div style="padding:28px">
<p style="color:#888;font-size:13px;margin-bottom:14px">{'السلام عليكم' if is_ar else 'Bonjour'} {nom},</p>
<p style="color:#aaa;font-size:13px;margin-bottom:20px">{'فرصة جديدة تطابق ملفكم:' if is_ar else 'Une nouvelle opportunité correspondant à votre profil :'}</p>
<div style="font-size:17px;font-weight:700;color:#f1f5f9;margin-bottom:20px;line-height:1.4">{t.get('objet','')[:200]}</div>
<table style="width:100%;border-collapse:collapse;margin-bottom:22px">
{''.join(f'<tr><td style="padding:9px 0;border-bottom:1px solid #1a2a3a;font-size:10px;color:#555;letter-spacing:1px;text-transform:uppercase;width:120px">{k}</td><td style="padding:9px 0;border-bottom:1px solid #1a2a3a;font-size:13px;color:{vc}">{v}</td></tr>' for k,v,vc in [
    ('Acheteur' if not is_ar else 'الجهة',t.get('acheteur','—')[:100],'#94a3b8'),
    ('STX10',f"[{t.get('stx10_code','')}] {t.get('stx10_label','')[:60]}",'#3b82f6'),
    ('Région' if not is_ar else 'الجهة',t.get('region','—'),'#94a3b8'),
    ('Montant' if not is_ar else 'الميزانية',t.get('montant','—'),'#94a3b8'),
    ('Date limite' if not is_ar else 'الموعد',f"{t.get('date_limite','—')} {('— '+dl) if dl else ''}",'#ef4444'),
])}
</table>
<a href="{cfg.SITE_URL}/tenders/{t['id']}" style="display:inline-block;padding:12px 22px;background:#2563eb;color:#fff;border-radius:8px;font-weight:700;text-decoration:none;font-size:13px">{'عرض التفاصيل ←' if is_ar else 'Voir le détail →'}</a>
</div>
<div style="padding:16px 28px;text-align:center;border-top:1px solid #1a2a3a">
<p style="font-size:11px;color:#444">SOURCE · <a href="{cfg.SITE_URL}/settings" style="color:#555">{'إدارة التنبيهات' if is_ar else 'Gérer mes alertes'}</a></p>
</div></div></body></html>"""

def wa_link(phone, t, lang="fr"):
    _,dl=days_left(t.get("date_limite",""))
    if lang=="ar":
        msg=(f"مرحباً!\n\nفرصة جديدة عبر SOURCE:\n\n📋 {t.get('objet','')[:120]}\n"
             f"🏢 {t.get('acheteur','')}\n💰 {t.get('montant','')}\n"
             f"⏰ {t.get('date_limite','')} {dl}\n\n🔗 {cfg.SITE_URL}/tenders/{t.get('id','')}")
    else:
        msg=(f"Bonjour!\n\nNouvelle opportunité SOURCE:\n\n📋 {t.get('objet','')[:120]}\n"
             f"🏢 {t.get('acheteur','')}\n💰 {t.get('montant','')}\n"
             f"⏰ {t.get('date_limite','')} {dl}\n\n🔗 {cfg.SITE_URL}/tenders/{t.get('id','')}")
    p=phone.strip().replace(" ","").replace("+","").replace("-","")
    if p.startswith("0") and len(p)==10: p="212"+p[1:]
    return f"https://wa.me/{p}?text={urllib.parse.quote(msg)}"

def dispatch(tenders, db):
    if not tenders: return {"tg":0,"email":0,"skip":0}
    tg=em=sk=0
    try:
        members=db.execute("SELECT * FROM members WHERE actif=1").fetchall()
        for m in members:
            member=dict(m)
            codes=json.loads(member.get("stx10_codes","[]") or "[]")
            lang=member.get("lang","fr")
            for t in tenders:
                td=dict(t) if not isinstance(t,dict) else t
                text=f"{td.get('objet','')} {td.get('acheteur','')} {td.get('region','')}"
                matched=match_member(text,codes) if codes else [td.get("stx10_code","")]
                if not matched: sk+=1; continue
                if db.execute("SELECT id FROM notif_log WHERE member_id=? AND tender_id=?",
                              (member["id"],td["id"])).fetchone(): continue
                now=datetime.now().isoformat()
                if member.get("notif_tg") and member.get("telegram"):
                    if tg_send(member["telegram"],_tg_msg(td,matched,lang)):
                        db.execute("INSERT OR IGNORE INTO notif_log(member_id,tender_id,channel,sent_at) VALUES(?,?,?,?)",
                                   (member["id"],td["id"],"tg",now)); tg+=1
                if member.get("notif_email") and member.get("email"):
                    s=f"📋 {'فرصة جديدة' if lang=='ar' else 'Nouvelle opportunité'}: {td.get('objet','')[:60]}"
                    if _email_send(member["email"],s,_email_html(td,member.get("nom",""),lang)):
                        db.execute("INSERT OR IGNORE INTO notif_log(member_id,tender_id,channel,sent_at) VALUES(?,?,?,?)",
                                   (member["id"],td["id"],"email",now)); em+=1
        db.commit()
        logger.info(f"[Notif] TG:{tg} Email:{em} Skip:{sk}")
        if tg+em>0: tg_admin(f"✅ <b>{len(tenders)} marchés</b>\n📱{tg} TG · 📧{em} Email · ⏭{sk} filtrés")
    except Exception as e: logger.error(f"[Notif] {e}",exc_info=True)
    return {"tg":tg,"email":em,"skip":sk}

def test_notif(email="",tg_id=""):
    fake={"id":"test_001","objet":"TEST — Construction bâtiment administratif R+3",
          "acheteur":"Ministère TEST SOURCE","stx10_code":"T101",
          "stx10_label":"Travaux de construction","region":"Rabat-Salé",
          "montant":"5 000 000 MAD","date_limite":"30/12/2026",
          "date_publication":datetime.now().strftime("%d/%m/%Y"),"url":"https://www.marchespublics.gov.ma"}
    res={"tg":False,"email":False}
    if tg_id: res["tg"]=tg_send(tg_id,_tg_msg(fake,[],"fr"))
    if email: res["email"]=_email_send(email,"🧪 Test SOURCE",_email_html(fake,"Admin","fr"))
    return res
