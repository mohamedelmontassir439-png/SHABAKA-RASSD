# -*- coding: utf-8 -*-
"""Les garanties et le financement d'un marché: la demande, et ce qu'il faut savoir.

Une PME qui gagne son premier marché bute souvent sur l'argent avant le
travail: la caution provisoire pour déposer, la caution définitive pour
signer, l'avance à garantir, puis des décomptes payés à 60 ou 90 jours
pendant qu'il faut payer les ouvriers. Les banques le font — encore faut-il
savoir quoi demander, avec quelles pièces, et s'y prendre assez tôt.

La plateforme n'est ni une banque ni un courtier: elle prépare la demande
(montant, marché, échéance) et la transmet à l'équipe, qui accompagne le
membre auprès d'un établissement. Aucun partenaire n'est nommé tant
qu'aucun accord n'est signé.
"""
import logging
from datetime import datetime

from app.core.config import cfg
from app.core.database import get_db

logger = logging.getLogger("atlas.financement")

# code: (libellé fr, libellé ar, à quoi elle sert fr, ar, pièces usuelles fr, ar)
TYPES = {
    "caution_provisoire": (
        "Caution provisoire", "الضمانة المؤقّتة",
        "Exigée pour déposer l'offre ; restituée si vous n'êtes pas retenu.",
        "مطلوبة لإيداع العرض؛ تُستردّ إن لم يُقبل عرضك.",
        "Avis d'appel d'offres, statuts, RC, derniers bilans, relevés bancaires.",
        "إعلان طلب العروض، النظام الأساسي، السجلّ التجاري، آخر الحصائل، الكشوف البنكية."),
    "caution_definitive": (
        "Caution définitive", "الضمانة النهائية",
        "À constituer après l'attribution, en général 3 % du montant, avant la signature.",
        "تُقدَّم بعد الإسناد، غالبًا 3 % من المبلغ، قبل التوقيع.",
        "Lettre d'attribution ou marché, pièces de la société, bilans.",
        "رسالة الإسناد أو الصفقة، وثائق الشركة، الحصائل."),
    "caution_avance": (
        "Caution de restitution d'avance", "ضمانة إرجاع التسبيق",
        "Permet de toucher l'avance prévue au marché.",
        "تمكّن من الحصول على التسبيق المنصوص عليه في الصفقة.",
        "Marché signé, ordre de service.", "الصفقة الموقّعة، الأمر بالخدمة."),
    "caution_retenue": (
        "Caution de retenue de garantie", "ضمانة الاقتطاع الضماني",
        "Remplace la retenue sur chaque décompte : vous êtes payé en entier.",
        "تعوّض الاقتطاع من كلّ مستحقّ: تتقاضى المبلغ كاملًا.",
        "Marché signé, décomptes.", "الصفقة الموقّعة، المستحقّات."),
    "prefinancement": (
        "Préfinancement ou avance sur marché", "تمويل مسبق أو تسبيق على الصفقة",
        "Financer les achats et la main-d'œuvre avant les premiers paiements.",
        "تمويل المشتريات واليد العاملة قبل أولى الأداءات.",
        "Marché signé, planning, devis fournisseurs.", "الصفقة الموقّعة، البرمجة، عروض الموردين."),
    "affacturage": (
        "Mobilisation de créance (décomptes)", "تعبئة الديون (المستحقّات)",
        "Être payé tout de suite sur un décompte validé, sans attendre l'administration.",
        "تقاضي مستحقّ مصادَق عليه فورًا، دون انتظار الإدارة.",
        "Décompte visé, marché, attestation de droits constatés.",
        "المستحقّ المؤشَّر عليه، الصفقة، شهادة الحقوق المثبتة."),
}
STATUTS = ("nouvelle", "en_cours", "transmise", "accordee", "refusee", "annulee")


def _maintenant() -> str:
    return datetime.now().isoformat(timespec="seconds")


def creer(member: dict, type_demande: str, montant: str, tender_id: str = "",
          echeance: str = "", message: str = "") -> tuple:
    """(True, id) ou (False, code). Prévient l'équipe par email."""
    if type_demande not in TYPES:
        return False, "type"
    montant = (montant or "").strip()[:40]
    if not montant:
        return False, "montant"
    db = get_db()
    try:
        objet = ""
        if tender_id:
            r = db.execute("SELECT objet FROM tenders WHERE id=?", (tender_id,)).fetchone()
            objet = r["objet"] if r else ""
        cur = db.execute(
            """INSERT INTO demandes_financement(member_id,type,montant,tender_id,objet,echeance,
                  message,statut,created_at,updated_at) VALUES(?,?,?,?,?,?,?,'nouvelle',?,?)""",
            (member["id"], type_demande, montant, (tender_id or "")[:60], (objet or "")[:300],
             (echeance or "")[:20], (message or "").strip()[:1500], _maintenant(), _maintenant()))
        db.commit()
        did = cur.lastrowid
    finally:
        db.close()
    try:
        from app.services.notifications import email_send
        email_send(cfg.CONTACT_EMAIL, f"Demande de financement : {TYPES[type_demande][0]} — {montant}",
                   f"<p><b>{member.get('company') or ''}</b> — {member.get('nom') or ''} · "
                   f"{member.get('phone') or ''} · {member.get('email') or ''}</p>"
                   f"<p>{TYPES[type_demande][0]} : <b>{montant}</b> · échéance {echeance or '—'}</p>"
                   f"<p>Marché : {objet or '—'}</p><p>{(message or '')[:1500]}</p>"
                   f"<p><a href='{cfg.SITE_URL}/admin/financement'>Ouvrir les demandes</a></p>")
    except Exception as e:
        logger.warning(f"[financement] email équipe: {e}")
    return True, did


def mes_demandes(member_id: int) -> list:
    db = get_db()
    try:
        return [dict(r) for r in db.execute(
            "SELECT * FROM demandes_financement WHERE member_id=? ORDER BY id DESC", (member_id,)).fetchall()]
    finally:
        db.close()


def toutes() -> list:
    db = get_db()
    try:
        return [dict(r) for r in db.execute(
            """SELECT d.*, m.nom, m.company, m.phone, m.email FROM demandes_financement d
               JOIN members m ON m.id = d.member_id ORDER BY d.id DESC LIMIT 300""").fetchall()]
    finally:
        db.close()


def changer_statut(did: int, statut: str) -> bool:
    if statut not in STATUTS:
        return False
    db = get_db()
    try:
        db.execute("UPDATE demandes_financement SET statut=?, updated_at=? WHERE id=?",
                   (statut, _maintenant(), did))
        db.commit()
    finally:
        db.close()
    return True
