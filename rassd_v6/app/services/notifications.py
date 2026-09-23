import json, logging, smtplib, requests as _req
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from app.core.config   import cfg
from app.core.database import get_db
from app.core.security import days_left, has_access
from app.core.sectors   import get_label

logger = logging.getLogger("atlas.notif")

from app.services.matching import matches

try:
    from app.services.whatsapp import (send_wa, format_tender_wa, twilio_configured,
                                       send_wa_template, clean_template_var, is_twilio_sandbox)
    WA_OK = True
except Exception:
    WA_OK = False
    def send_wa(*a, **kw): return False
    def format_tender_wa(t): return ""
    def twilio_configured(): return False
    def send_wa_template(*a, **kw): return False
    def clean_template_var(v, fallback="-", max_len=180): return str(v or fallback)
    def is_twilio_sandbox(): return False


def _log_notif(db, member_id: int, tender_id: str, channel: str,
               ok: bool, error: str = "", provider: str = ""):
    """Journalise chaque tentative d'envoi, réussie ou non.

    Les échecs sont enregistrés au même titre que les réussites: sans cela,
    un canal qui tombe en panne reste invisible et le marché serait retenté
    indéfiniment à chaque cycle (la déduplication se base sur ce journal).
    """
    try:
        db.execute(
            """INSERT INTO notif_log(member_id,tender_id,channel,sent_at,status,error,provider)
               VALUES(?,?,?,?,?,?,?)""",
            (member_id, tender_id, channel, datetime.now().isoformat(),
             "SENT" if ok else "FAILED", (error or "")[:300], provider))
    except Exception as e:
        logger.error(f"[notif_log] {e}")


def send_wa_verification(phone: str, code: str) -> bool:
    """Envoie le code de vérification WhatsApp (opt-in).

    En production, un code envoyé à l'initiative de l'entreprise doit passer
    par un modèle d'authentification approuvé (TWILIO_OTP_CONTENT_SID). Sans
    lui, le texte libre ne fonctionne qu'avec le Sandbox Twilio.
    """
    if twilio_configured() and cfg.TWILIO_OTP_CONTENT_SID:
        return send_wa_template(phone, cfg.TWILIO_OTP_CONTENT_SID, {"1": code})
    return send_wa(phone, (
        f"🔐 Maroc Entrepreneuriat\n\n"
        f"Votre code de vérification WhatsApp : *{code}*\n\n"
        f"Saisissez-le sur la page Réglages pour activer les alertes WhatsApp.\n"
        f"Ce code expire dans 15 minutes.\n\n"
        f"Si vous n'êtes pas à l'origine de cette demande, ignorez ce message."
    ))

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
        tg_send(cfg.ADMIN_CHAT_ID, f"🔔 <b>MAROC ENTREPRENEURIAT</b>\n{msg}")

def build_tg_message(t: dict) -> str:
    _n, dl_label = days_left(t.get("date_limite", ""))
    type_offre = t.get("type_offre", "Public")
    lines = [
        f"🏛 <b>Nouveau Marché {type_offre}</b>",
        "━" * 28,
        "",
        f"📋 <b>{t['objet'][:120]}</b>",
        "",
    ]
    if t.get("acheteur"): lines.append(f"🏢 {t['acheteur'][:70]}")
    if t.get("secteur"):  lines.append(f"🏷 {get_label(t['secteur'])}")
    if t.get("region"):   lines.append(f"📍 {t['region']}")
    if t.get("montant"):  lines.append(f"💰 {t['montant']}")
    dl = t.get("date_limite", "")
    if dl:
        badge = f" — <b>{dl_label}</b>" if dl_label else ""
        lines.append(f"⏰ <b>{dl}{badge}</b>")
    lines.append("")
    # Le lien passe par notre propre domaine (redirection serveur) — la source
    # des marchés privés n'apparaît donc jamais dans le message.
    if t.get("source") == "marchespublics":
        lines.append(f"🔗 <a href='{t['url']}'>Voir sur marchespublics.gov.ma</a>")
    else:
        lines.append(f"🔗 <a href='{cfg.SITE_URL}/tenders/{t['id']}/source'>Voir le marché</a>")
    lines += [
        f"📱 <a href='{cfg.SITE_URL}/tenders/{t['id']}'>Voir sur MAROC ENTREPRENEURIAT</a>",
        "",
        "<i>MAROC ENTREPRENEURIAT · Veille Marchés Publics & Privés Maroc</i>",
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
            # timeout explicite: sans lui smtplib bloque indéfiniment si le
            # port SMTP est filtré par l'hébergeur (cas de Railway) au lieu
            # d'échouer immédiatement — ça gelait toute la requête /forgot.
            with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=10) as srv:
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
    type_offre      = t.get("type_offre", "Public")
    is_public       = t.get("source") == "marchespublics"
    cta_label       = "Voir sur marchespublics.gov.ma" if is_public else "Voir le marché"
    # Le lien passe par notre propre domaine (redirection serveur) pour les
    # marchés privés — leur source n'apparaît donc jamais dans l'email.
    cta_url         = t["url"] if is_public else f"{site}/tenders/{t['id']}/source"
    priv_badge      = '<div class="priv-badge">🔒 Marché privé</div>' if type_offre == "Privé" else ""
    badge_html      = f'''<div class="dl-badge">⏰ {dl_label}</div>''' if dl_label else ""
    region_row      = f'<tr><td class="lbl">📍 Région</td><td class="val">{t.get("region","")}</td></tr>' if t.get("region") else ""
    montant_row     = f'<tr><td class="lbl">💰 Montant</td><td class="val">{t.get("montant","")}</td></tr>' if t.get("montant") else ""
    return f"""<!DOCTYPE html>
<html lang="fr"><head><meta charset="UTF-8">
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#f6f7fb;font-family:Arial,Helvetica,sans-serif;padding:20px}}
.wrap{{max-width:600px;margin:0 auto;background:#ffffff;border:1px solid #e3e7ef;border-radius:12px;overflow:hidden}}
.hdr{{padding:24px 32px;background:#1e1611;border-bottom:1px solid #e3e7ef}}
.logo{{font-size:20px;font-weight:800;color:#ffffff}}
.logo em{{font-style:normal;color:#f2662d}}
.body{{padding:32px}}
.title{{font-size:17px;font-weight:700;color:#101828;line-height:1.5;margin-bottom:20px}}
table{{width:100%;border-collapse:collapse;margin-bottom:24px}}
td{{padding:10px 0;border-bottom:1px solid #e3e7ef;vertical-align:top;font-size:13px}}
.lbl{{color:#98a1b3;letter-spacing:.5px;text-transform:uppercase;width:110px;font-size:11px}}
.val{{color:#3b4457}}.val-g{{color:#c94e1f;font-weight:700}}.val-r{{color:#d64545;font-weight:700}}
.cta{{display:inline-block;margin:6px 6px 0 0;padding:12px 22px;background:#f2662d;color:#1e1611;border-radius:8px;font-weight:700;text-decoration:none;font-size:13px}}
.cta2{{display:inline-block;margin:6px 6px 0 0;padding:12px 22px;border:1px solid #1e1611;color:#1e1611;border-radius:8px;font-weight:700;text-decoration:none;font-size:13px}}
.ftr{{padding:20px 32px;background:#f6f7fb;border-top:1px solid #e3e7ef;text-align:center}}
.dl-badge{{display:inline-block;padding:6px 14px;background:rgba(242,102,45,.12);border:1px solid rgba(242,102,45,.3);border-radius:99px;font-size:12px;color:#c94e1f;margin-bottom:20px;margin-inline-end:8px}}
.priv-badge{{display:inline-block;padding:6px 14px;background:rgba(59,68,87,.08);border:1px solid rgba(59,68,87,.25);border-radius:99px;font-size:12px;color:#3b4457;font-weight:700;margin-bottom:20px}}
</style></head>
<body><div class="wrap">
<div class="hdr"><div class="logo">Maroc<em>Entrepreneuriat</em></div><div style="font-size:11px;color:rgba(255,255,255,.6);margin-top:3px">MARCHÉS {type_offre.upper()}S · MAROC</div></div>
<div class="body">
<p style="color:#6b7488;font-size:13px;margin-bottom:16px">Bonjour {nom or "Madame/Monsieur"},</p>
<p style="color:#6b7488;font-size:13px;margin-bottom:20px">Un nouveau marché correspondant à votre profil vient d'être publié :</p>
{priv_badge}{badge_html}
<div class="title">{t["objet"][:200]}</div>
<table>
<tr><td class="lbl">🏢 Acheteur</td><td class="val">{t.get("acheteur","—")[:100]}</td></tr>
<tr><td class="lbl">🏷 Secteur</td><td class="val val-g">{get_label(t.get("secteur",""))}</td></tr>
{region_row}
{montant_row}
<tr><td class="lbl">⏰ Date limite</td><td class="val val-r">{dl}</td></tr>
<tr><td class="lbl">📅 Publication</td><td class="val">{t.get("date_publication","—")}</td></tr>
</table>
<a href="{cta_url}" class="cta">{cta_label} ↗</a>
<a href="{site}/tenders/{t["id"]}" class="cta2">Détails MAROC ENTREPRENEURIAT</a>
</div>
<div class="ftr"><p style="color:#98a1b3;font-size:11px">MAROC ENTREPRENEURIAT · <a href="{site}" style="color:#6b7488">marocentrepreneuriat.com</a> · <a href="{site}/settings" style="color:#6b7488">Gérer mes alertes</a></p></div>
</div></body></html>"""

def build_digest_email(tenders: list, nom: str = "") -> str:
    site = cfg.SITE_URL
    rows = "".join(f'''
<tr><td style="padding:14px 0;border-bottom:1px solid #e3e7ef;">
  <div style="font-size:14px;font-weight:700;color:#101828;margin-bottom:4px">{"🔒 Privé · " if t.get("type_offre")=="Privé" else ""}{t["objet"][:140]}</div>
  <div style="font-size:12px;color:#6b7488">{t.get("acheteur","")[:80]} · {get_label(t.get("secteur",""))} · ⏰ {t.get("date_limite","—")}</div>
  <a href="{site}/tenders/{t["id"]}" style="font-size:12px;color:#c94e1f;font-weight:700;text-decoration:none">Voir le marché ↗</a>
</td></tr>''' for t in tenders)
    return f"""<!DOCTYPE html>
<html lang="fr"><head><meta charset="UTF-8">
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#f6f7fb;font-family:Arial,Helvetica,sans-serif;padding:20px}}
.wrap{{max-width:600px;margin:0 auto;background:#ffffff;border:1px solid #e3e7ef;border-radius:12px;overflow:hidden}}
.hdr{{padding:24px 32px;background:#1e1611;border-bottom:1px solid #e3e7ef}}
.logo{{font-size:20px;font-weight:800;color:#ffffff}}
.logo em{{font-style:normal;color:#f2662d}}
.body{{padding:32px}}
table{{width:100%;border-collapse:collapse}}
.ftr{{padding:20px 32px;background:#f6f7fb;border-top:1px solid #e3e7ef;text-align:center}}
</style></head>
<body><div class="wrap">
<div class="hdr"><div class="logo">Maroc<em>Entrepreneuriat</em></div><div style="font-size:11px;color:rgba(255,255,255,.6);margin-top:3px">RÉCAPITULATIF HEBDOMADAIRE</div></div>
<div class="body">
<p style="color:#6b7488;font-size:13px;margin-bottom:20px">Bonjour {nom or "Madame/Monsieur"}, voici les {len(tenders)} marché(s) correspondant à votre profil publiés cette semaine :</p>
<table>{rows}</table>
</div>
<div class="ftr"><p style="color:#98a1b3;font-size:11px">MAROC ENTREPRENEURIAT · <a href="{site}" style="color:#6b7488">marocentrepreneuriat.com</a> · <a href="{site}/settings" style="color:#6b7488">Gérer mes alertes</a></p></div>
</div></body></html>"""

def send_weekly_digests(force: bool = False) -> int:
    """Envoie le récapitulatif hebdomadaire (chaque lundi) aux membres ayant
    activé l'option 'Digest hebdomadaire' — regroupe les marchés mis en file
    depuis le dernier envoi en un seul email par membre."""
    from datetime import timedelta
    db, sent = get_db(), 0
    try:
        if not force and datetime.now().weekday() != 0:  # 0 = lundi
            return 0
        members = db.execute(
            "SELECT * FROM members WHERE actif=1 AND notif_digest=1 AND notif_email=1"
        ).fetchall()
        for m in members:
            member = dict(m)
            if not has_access(member):
                continue
            last = member.get("last_digest_sent") or ""
            if last:
                try:
                    if datetime.now() - datetime.fromisoformat(last) < timedelta(days=6):
                        continue
                except ValueError:
                    pass
            rows = db.execute(
                """SELECT t.* FROM notif_queue q JOIN tenders t ON t.id=q.tender_id
                   WHERE q.member_id=? ORDER BY q.created_at ASC""",
                (member["id"],)).fetchall()
            if not rows:
                continue
            tenders = [dict(r) for r in rows]
            html = build_digest_email(tenders, member.get("nom", ""))
            ok = email_send(member["email"], f"📋 Votre récapitulatif hebdomadaire — {len(tenders)} marché(s)", html)
            if ok:
                db.execute("DELETE FROM notif_queue WHERE member_id=?", (member["id"],))
                db.execute("UPDATE members SET last_digest_sent=? WHERE id=?",
                           (datetime.now().isoformat(), member["id"]))
                db.commit()
                sent += 1
    except Exception as e:
        logger.error(f"[digest] {e}", exc_info=True)
    finally:
        db.close()
    return sent

# ── Dispatch principal ────────────────────────────────────

def dispatch_notifications(tenders: list, max_par_membre: int = 40):
    """Envoie les alertes pour une liste de marchés.

    max_par_membre borne ce qu'un membre reçoit en un seul passage: après un
    gros import, une rafale de centaines d'alertes ferait fuir le destinataire.
    Le reste part au cycle suivant, la déduplication garantissant qu'aucun
    marché n'est ni perdu ni envoyé deux fois.
    """
    if not tenders:
        return
    db = get_db()
    try:
        members = db.execute(
            "SELECT * FROM members WHERE actif=1"
        ).fetchall()
        total_tg = total_email = total_wa = total_skip = 0

        for m in members:
            envoyes_ce_membre = 0
            member = dict(m)
            # Un membre dont l'abonnement n'a pas été activé par l'admin ne
            # doit recevoir aucun détail de marché, sur aucun canal — le même
            # principe que le blocage appliqué aux pages du site.
            if not has_access(member):
                continue
            for t in tenders:
                # Moteur de correspondance: secteur, région, type, budget
                # minimum et mots-clés (un filtre vide = aucune restriction).
                ok_match, _reason = matches(member, t)
                if not ok_match:
                    total_skip += 1
                    continue
                # Dédup
                if db.execute(
                    "SELECT id FROM notif_log WHERE member_id=? AND tender_id=?",
                    (member["id"], t["id"])
                ).fetchone():
                    continue
                if envoyes_ce_membre >= max_par_membre:
                    break

                envoyes_ce_membre += 1
                now = datetime.now().isoformat()

                # Digest hebdomadaire : mise en file, envoyée groupée le lundi
                if member.get("notif_digest"):
                    db.execute(
                        "INSERT OR IGNORE INTO notif_queue(member_id,tender_id,created_at) VALUES(?,?,?)",
                        (member["id"], t["id"], now))

                # Telegram
                if member.get("notif_tg") and member.get("telegram"):
                    ok = tg_send(member["telegram"], build_tg_message(t))
                    _log_notif(db, member["id"], t["id"], "telegram", ok,
                               "" if ok else "échec envoi Telegram", "telegram")
                    if ok:
                        total_tg += 1
                    else:
                        logger.warning(f"[Notif] TG failed pour {member['email']}")

                # Email — une adresse non confirmée n'a jamais prouvé son
                # existence: lui écrire ne fait qu'accumuler des rebonds, ce
                # qui dégrade la réputation d'envoi du domaine.
                if (member.get("notif_email") and member.get("email")
                        and member.get("email_verified", 1)):
                    html = build_email(t, member.get("nom", ""))
                    ok   = email_send(
                        member["email"],
                        f"📋 Nouveau marché: {t['objet'][:60]}",
                        html
                    )
                    _log_notif(db, member["id"], t["id"], "email", ok,
                               "" if ok else "échec envoi email",
                               "brevo" if cfg.BREVO_KEY else "gmail")
                    if ok:
                        total_email += 1

                # WhatsApp — n'est envoyé qu'à un numéro dont le membre a
                # confirmé la propriété (opt-in vérifié par code). Sans cette
                # condition on enverrait des messages non sollicités, ce que
                # les règles WhatsApp/Twilio interdisent.
                if cfg.WA_ENABLED and member.get("notif_wa") and member.get("whatsapp"):
                    if not member.get("whatsapp_verified"):
                        _log_notif(db, member["id"], t["id"], "whatsapp", False,
                                   "numéro non vérifié (opt-in requis)", "")
                    else:
                        # WhatsApp ne part plus marché par marché: chaque message
                        # est facturé par Meta, et plusieurs alertes par jour sur
                        # WhatsApp sont vécues comme du spam. Le marché est mis en
                        # file et part dans le résumé quotidien
                        # (send_daily_wa_digests). Email et Telegram restent
                        # instantanés.
                        db.execute(
                            "INSERT OR IGNORE INTO wa_digest_queue(member_id,tender_id,created_at) VALUES(?,?,?)",
                            (member["id"], t["id"], now))
                        total_wa += 1

        db.commit()
        logger.info(
            f"[Notif] ✅ {total_tg} TG + {total_email} Email + {total_wa} WhatsApp en file "
            f"pour {len(tenders)} marchés ({total_skip} filtrés)"
        )
        if total_tg + total_email + total_wa > 0:
            tg_admin(
                f"✅ <b>{len(tenders)} nouveaux marchés</b>\n"
                f"📱 {total_tg} Telegram · 📧 {total_email} Email · 💬 {total_wa} WhatsApp en file"
            )
    except Exception as e:
        logger.error(f"[Notif] Exception: {e}", exc_info=True)
    finally:
        db.close()


def test_notifications(email: str = "", telegram_id: str = "", whatsapp: str = "") -> dict:
    """Test les notifications — appelé depuis /admin/test_notif"""
    results = {"telegram": False, "email": False, "whatsapp": False}
    fake_tender = {
        "id":               "bdc_test",
        "objet":            "TEST — Marché de test MAROC ENTREPRENEURIAT",
        "acheteur":         "Administration Marocaine",
        "secteur":          "S901",
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
        results["email"] = email_send(email, "🧪 Test MAROC ENTREPRENEURIAT — Notifications", html)
    if whatsapp:
        results["whatsapp"] = send_wa(whatsapp, format_tender_wa(fake_tender))
    return results


# ── Résumé WhatsApp quotidien ─────────────────────────────

def _morocco_now():
    """Heure du Maroc — le serveur Railway tourne en UTC."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Africa/Casablanca")).replace(tzinfo=None)
    except Exception:
        from datetime import timedelta, timezone
        return datetime.now(timezone(timedelta(hours=1))).replace(tzinfo=None)


def build_wa_digest_vars(member: dict, items: list, link: str) -> dict:
    """Variables du modèle approuvé (catégorie UTILITY).

    Texte du modèle à créer dans la console Twilio:
      Bonjour {{1}}, {{2}} nouvelle(s) opportunité(s) correspondent à vos
      secteurs. La plus récente : {{3}}. Liste complète : {{4}} —
      Maroc Entrepreneuriat
    """
    prenom = ((member.get("nom") or "").strip().split(" ") or [""])[0]
    plus_recente = items[0].get("objet", "") if items else ""
    return {
        "1": clean_template_var(prenom, "cher membre", 40),
        "2": str(len(items)),
        "3": clean_template_var(plus_recente, "voir la liste", 120),
        "4": clean_template_var(link, link, 200),
    }


def build_wa_digest_text(member: dict, items: list, link: str) -> str:
    """Version texte libre du résumé (Sandbox Twilio, ou service Baileys)."""
    prenom = ((member.get("nom") or "").strip().split(" ") or [""])[0]
    lignes = ["🔔 *Maroc Entrepreneuriat* — résumé du jour", "",
              f"Bonjour {prenom}," if prenom else "Bonjour,",
              f"*{len(items)} nouvelle(s) opportunité(s)* correspondent à vos secteurs :", ""]
    for t in items[:5]:
        dl = f" · ⏰ {t['date_limite']}" if t.get("date_limite") else ""
        lignes.append(f"• {(t.get('objet') or '')[:90]}{dl}")
    if len(items) > 5:
        lignes.append(f"… et {len(items) - 5} autre(s)")
    lignes += ["", f"👉 {link}"]
    return "\n".join(lignes)


def send_daily_wa_digests(force: bool = False, now=None) -> int:
    """Envoie à chaque membre un seul message WhatsApp par jour.

    Idempotent: last_wa_digest (date du Maroc) empêche un second envoi le
    même jour, et un résumé vide n'est jamais envoyé. Un échec n'est pas
    marqué comme envoyé — il sera retenté, mais au plus 3 fois par jour
    pour ne pas enchaîner des appels facturés qui échouent tous.
    """
    import time as _time
    if not cfg.WA_ENABLED:
        return 0
    now = now or _morocco_now()
    if not force and now.hour < cfg.WA_DIGEST_HOUR:
        return 0
    today = now.strftime("%Y-%m-%d")
    link  = f"{cfg.SITE_URL}/opportunites-du-jour"
    envoyes = 0
    db = get_db()
    try:
        membres = [dict(m) for m in db.execute(
            """SELECT * FROM members WHERE actif=1 AND notif_wa=1 AND whatsapp_verified=1
               AND whatsapp!='' AND (last_wa_digest IS NULL OR last_wa_digest!=?)""",
            (today,)).fetchall()]
        for m in membres:
            if not has_access(m):
                continue
            echecs = db.execute(
                """SELECT COUNT(*) FROM notif_log WHERE member_id=? AND channel='whatsapp'
                   AND tender_id=? AND status='FAILED'""",
                (m["id"], f"digest:{today}")).fetchone()[0]
            if echecs >= 3:
                continue
            items = [dict(r) for r in db.execute(
                """SELECT t.id, t.objet, t.date_limite, t.secteur, q.id AS qid
                   FROM wa_digest_queue q JOIN tenders t ON t.id = q.tender_id
                   WHERE q.member_id=? AND (q.sent_at IS NULL OR q.sent_at='')
                   ORDER BY t.scraped_at DESC LIMIT 200""",
                (m["id"],)).fetchall()]
            if not items:
                continue

            if twilio_configured() and cfg.TWILIO_CONTENT_SID:
                ok = send_wa_template(m["whatsapp"], cfg.TWILIO_CONTENT_SID,
                                      build_wa_digest_vars(m, items, link))
                provider = "twilio-template"
            else:
                ok = send_wa(m["whatsapp"], build_wa_digest_text(m, items, link))
                provider = "twilio" if twilio_configured() else "baileys"

            _log_notif(db, m["id"], f"digest:{today}", "whatsapp", ok,
                       "" if ok else "échec envoi résumé WhatsApp", provider)
            if ok:
                ids = [it["qid"] for it in items]
                ph = ",".join("?" * len(ids))
                db.execute(f"UPDATE wa_digest_queue SET sent_at=? WHERE id IN ({ph})",
                           [now.isoformat()] + ids)
                db.execute("UPDATE members SET last_wa_digest=? WHERE id=?", (today, m["id"]))
                envoyes += 1
            db.commit()
            # Le Sandbox Twilio n'accepte qu'un message toutes les 3 secondes.
            _time.sleep(3.1 if is_twilio_sandbox() else 0.3)
    except Exception as e:
        logger.error(f"[WA digest] {e}", exc_info=True)
    finally:
        db.close()
    if envoyes:
        logger.info(f"[WA digest] {envoyes} résumé(s) WhatsApp envoyé(s)")
    return envoyes


# ── Fin d'abonnement: prévenir avant la coupure ───────────

# Jours restants → étape. Un abonné prévenu renouvelle; un abonné coupé sans
# préavis se sent puni et ne revient pas.
RELANCES_ABONNEMENT = ((7, "j7"), (1, "j1"), (0, "fin"))


def send_renewal_reminders(now=None) -> int:
    """Relance les abonnements payants qui arrivent à échéance.

    Idempotent par étape grâce au journal des notifications: un même membre
    ne reçoit jamais deux fois la relance « J-7 » pour la même échéance.
    """
    now = now or datetime.now()
    aujourdhui = now.date()
    db, envoyes = get_db(), 0
    try:
        membres = [dict(m) for m in db.execute(
            """SELECT * FROM members WHERE actif=1 AND notif_email=1 AND email_verified=1
               AND subscription_status='ACTIVE' AND subscription_end!=''""").fetchall()]
        for m in membres:
            try:
                fin = datetime.strptime(m["subscription_end"][:10], "%Y-%m-%d").date()
            except (ValueError, TypeError):
                continue
            restant = (fin - aujourdhui).days
            if restant < 0 or restant > 7:
                continue
            # On retient l'étape la plus proche atteinte (7 → 1 → fin).
            etape = None
            for seuil, cle in RELANCES_ABONNEMENT:
                if restant <= seuil:
                    etape = cle
            if not etape:
                continue

            marqueur = f"abo:{etape}:{m['subscription_end'][:10]}"
            if db.execute("SELECT id FROM notif_log WHERE member_id=? AND tender_id=?",
                          (m["id"], marqueur)).fetchone():
                continue

            if etape == "fin":
                sujet = "Votre abonnement arrive à échéance aujourd'hui"
                titre = "Votre accès se termine aujourd'hui"
                corps = ("Vos secteurs, vos favoris et vos alertes restent enregistrés. "
                         "Un renouvellement les réactive immédiatement.")
            else:
                jours = "7 jours" if etape == "j7" else "demain"
                sujet = f"Votre abonnement expire {'dans 7 jours' if etape == 'j7' else 'demain'}"
                titre = f"Votre abonnement expire {jours}"
                corps = ("Pour ne pas interrompre vos alertes, renouvelez avant la date "
                         f"d'échéance du {fin.strftime('%d/%m/%Y')}.")
            html = f"""
            <div style="font-family:Arial,Helvetica,sans-serif;max-width:560px;margin:auto">
              <h2 style="color:#1e1611;font-size:20px;margin:0 0 12px">{titre}</h2>
              <p style="color:#4a4a4a;font-size:15px;line-height:1.7;margin:0 0 20px">{corps}</p>
              <a href="{cfg.SITE_URL}/mon-abonnement" style="display:inline-block;padding:12px 24px;
                 background:#f2662d;color:#fff;border-radius:8px;text-decoration:none;font-weight:600">
                 Renouveler mon abonnement</a>
              <p style="color:#98a1b3;font-size:11px;margin-top:24px">
                MAROC ENTREPRENEURIAT · <a href="{cfg.SITE_URL}/settings" style="color:#6b7488">Gérer mes alertes</a></p>
            </div>"""
            ok = email_send(m["email"], sujet, html)
            _log_notif(db, m["id"], marqueur, "email", ok,
                       "" if ok else "échec relance abonnement",
                       "brevo" if cfg.BREVO_KEY else "gmail")
            if ok:
                envoyes += 1
            db.commit()
    except Exception as e:
        logger.error(f"[relance abo] {e}", exc_info=True)
    finally:
        db.close()
    if envoyes:
        logger.info(f"[relance abo] {envoyes} relance(s) envoyée(s)")
    return envoyes


# ── Rattrapage des alertes manquées ───────────────────────

def dispatch_pending(heures: int = 48, limite: int = 400) -> int:
    """Renvoie les marchés récents qu'aucune alerte n'a encore couverts.

    Les alertes partaient uniquement pour les marchés de la collecte en
    cours, gardés en mémoire: un redémarrage du serveur entre l'écriture en
    base et l'envoi les perdait définitivement, et un import lancé depuis
    l'admin n'alertait personne. On repart donc de la base, seule source
    fiable: tout marché actif récent sans ligne dans notif_log est repris.
    """
    db = get_db()
    try:
        lignes = [dict(r) for r in db.execute(
            """SELECT t.* FROM tenders t
               WHERE t.statut='actif'
                 AND t.scraped_at >= datetime('now', ?)
                 AND NOT EXISTS (SELECT 1 FROM notif_log n WHERE n.tender_id = t.id)
               ORDER BY t.scraped_at DESC LIMIT ?""",
            (f"-{int(heures)} hours", limite)).fetchall()]
    finally:
        db.close()
    if lignes:
        logger.info(f"[rattrapage] {len(lignes)} marché(s) sans alerte — reprise")
        dispatch_notifications(lignes)
    return len(lignes)


# ── Accompagnement de l'essai gratuit ─────────────────────

# Jour depuis l'inscription → (étape, clés de texte). Un membre reçoit au
# plus une étape par passage, et jamais deux fois la même (members.trial_seq).
SEQUENCE_ESSAI = ((0, 1, "j0"), (2, 2, "j2"), (5, 3, "j5"), (7, 4, "j7"))


def _enveloppe_email(titre: str, texte: str, lien: str, libelle_bouton: str) -> str:
    """Même habillage que les alertes, sans dépendre d'un marché précis."""
    return f"""
    <div style="font-family:Arial,Helvetica,sans-serif;max-width:560px;margin:auto">
      <h2 style="color:#1e1611;font-size:20px;margin:0 0 12px">{titre}</h2>
      <p style="color:#4a4a4a;font-size:15px;line-height:1.7;margin:0 0 20px">{texte}</p>
      <a href="{lien}" style="display:inline-block;padding:12px 24px;background:#f2662d;
         color:#fff;border-radius:8px;text-decoration:none;font-weight:600">{libelle_bouton}</a>
      <p style="color:#98a1b3;font-size:11px;margin-top:24px">
        MAROC ENTREPRENEURIAT · <a href="{cfg.SITE_URL}" style="color:#6b7488">marocentrepreneuriat.com</a>
        · <a href="{cfg.SITE_URL}/settings" style="color:#6b7488">Gérer mes alertes</a></p>
    </div>"""


def _marches_du_membre(db, membre: dict) -> int:
    """Nombre de marchés actifs correspondant aux secteurs du membre."""
    try:
        secteurs = json.loads(membre.get("secteurs") or "[]")
    except Exception:
        secteurs = []
    if not secteurs:
        return 0
    ph = ",".join("?" * len(secteurs))
    return db.execute(
        f"""SELECT COUNT(*) FROM tenders WHERE statut='actif' AND secteur IN ({ph})
            AND scraped_at >= ?""",
        secteurs + [membre.get("created_at", "")[:10]]).fetchone()[0]


def send_trial_sequence(now=None) -> int:
    """Accompagne chaque membre pendant son essai: 4 emails en 7 jours.

    Idempotent: trial_seq retient la dernière étape envoyée, donc un
    redémarrage ou un double passage ne renvoie rien. Une adresse non
    confirmée ne reçoit rien non plus — elle n'a jamais prouvé son existence.
    """
    from app.core.i18n import tr as _tr
    now = now or datetime.now()
    db, envoyes = get_db(), 0
    try:
        membres = [dict(m) for m in db.execute(
            """SELECT * FROM members WHERE actif=1 AND notif_email=1
               AND email_verified=1 AND trial_start!=''""").fetchall()]
        for membre in membres:
            try:
                debut = datetime.strptime(membre["trial_start"][:10], "%Y-%m-%d")
            except (ValueError, TypeError):
                continue
            jours = (now - debut).days
            etape_faite = membre.get("trial_seq") or 0

            cible = None
            for jour_min, etape, cle in SEQUENCE_ESSAI:
                if jours >= jour_min and etape > etape_faite:
                    cible = (etape, cle)
            if not cible:
                continue
            etape, cle = cible

            # L'étape « fin d'essai » n'a de sens que pour qui n'a pas payé.
            if cle == "j7" and (membre.get("subscription_status") == "ACTIVE"):
                db.execute("UPDATE members SET trial_seq=? WHERE id=?", (etape, membre["id"]))
                db.commit()
                continue

            lang = "fr"
            n = _marches_du_membre(db, membre) if cle == "j2" else 0
            if cle == "j2" and n == 0:
                continue  # rien à montrer: on n'envoie pas un email vide
            destination = {"j0": "/settings", "j2": "/tenders",
                           "j5": "/tarifs", "j7": "/tarifs"}[cle]
            html = _enveloppe_email(
                _tr(f"mail_{cle}_h2", lang),
                _tr(f"mail_{cle}_p", lang, n=n),
                f"{cfg.SITE_URL}{destination}",
                _tr(f"mail_{cle}_btn", lang))
            ok = email_send(membre["email"], _tr(f"mail_{cle}_subject", lang, n=n), html)
            _log_notif(db, membre["id"], f"essai:{cle}", "email", ok,
                       "" if ok else "échec email d'accompagnement",
                       "brevo" if cfg.BREVO_KEY else "gmail")
            if ok:
                db.execute("UPDATE members SET trial_seq=? WHERE id=?", (etape, membre["id"]))
                envoyes += 1
            db.commit()
    except Exception as e:
        logger.error(f"[essai] {e}", exc_info=True)
    finally:
        db.close()
    if envoyes:
        logger.info(f"[essai] {envoyes} email(s) d'accompagnement envoyé(s)")
    return envoyes
