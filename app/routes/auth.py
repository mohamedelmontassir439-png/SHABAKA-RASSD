from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from datetime import datetime, timedelta
import json

from main import (
    render, get_db, get_member, hash_pw, verify_pw,
    make_token, make_random_token, validate_email,
    validate_password, send_verification_email,
    send_password_reset_email, clean_secteurs, cfg
)

router = APIRouter()


@router.get("/register", response_class=HTMLResponse)
async def register_get(req: Request):
    m = get_member(req)
    if m:
        return RedirectResponse("/dashboard", 302)
    return render(req, "register.html", {})


@router.post("/register")
async def register_post(req: Request,
    nom:          str  = Form(""),
    email:        str  = Form(""),
    phone:        str  = Form(""),
    company:      str  = Form(""),
    pw:           str  = Form(""),
    pw2:          str  = Form(""),
    secteurs_sel: list = Form(default=[]),
):
    err = None
    vals = {"nom": nom, "email": email, "phone": phone, "company": company}

    if not email or not pw:
        err = "Email et mot de passe requis"
    elif not validate_email(email):
        err = "Adresse email invalide"
    elif pw != pw2:
        err = "Les mots de passe ne correspondent pas"
    else:
        ok, msg = validate_password(pw)
        if not ok:
            err = msg

    if err:
        return render(req, "register.html", {"err": err, "vals": vals})

    db = get_db()
    try:
        if db.execute("SELECT id FROM members WHERE email=?", (email,)).fetchone():
            return render(req, "register.html", {
                "err": "Cette adresse email est déjà utilisée",
                "vals": vals,
            })
        sects = clean_secteurs(secteurs_sel)
        trial_ends = (datetime.now() + timedelta(days=14)).strftime("%Y-%m-%d")
        created_at = datetime.now().isoformat()
        verify_token = make_random_token()
        db.execute(
            """INSERT INTO members
               (nom,email,phone,company,pw_hash,plan,secteurs,
                created_at,trial_ends,email_verified,verify_token,reset_token)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (nom, email, phone, company, hash_pw(pw), "free",
             json.dumps(sects), created_at, trial_ends,
             0, verify_token, "")
        )
        db.commit()
        m = db.execute("SELECT * FROM members WHERE email=?", (email,)).fetchone()
    finally:
        db.close()

    sent = send_verification_email(email, verify_token, nom)
    if sent:
        return render(req, "login.html", {
            "ok": "Compte créé ! Vérifiez votre email pour activer votre compte.",
            "vals": {"email": email}
        })

    return render(req, "login.html", {
        "ok": "Compte créé. Nous n'avons pas pu envoyer l'email de confirmation.",
        "vals": {"email": email}
    })


@router.get("/login", response_class=HTMLResponse)
async def login_get(req: Request, next: str = ""):
    m = get_member(req)
    if m:
        return RedirectResponse(next or "/dashboard", 302)
    return render(req, "login.html", {"next": next})


@router.post("/login")
async def login_post(req: Request,
    email: str = Form(""),
    pw:    str = Form(""),
    next:  str = Form(""),
):
    db = get_db()
    m = db.execute(
        "SELECT * FROM members WHERE email=? AND actif=1", (email,)
    ).fetchone()
    if not m or not verify_pw(pw, m["pw_hash"]):
        db.close()
        return render(req, "login.html", {
            "err": "Email ou mot de passe incorrect",
            "vals": {"email": email},
            "next": next,
        })
    email_enabled = bool(cfg.BREVO_KEY or (cfg.GMAIL_USER and cfg.GMAIL_PASS))
    if m["email_verified"] == 0 and email_enabled:
        db.close()
        return render(req, "login.html", {
            "err": "Votre email n'est pas vérifié. Vérifiez votre boîte de réception.",
            "vals": {"email": email},
            "next": next,
            "show_resend": True,
        })
    db.execute("UPDATE members SET last_login=? WHERE id=?", (datetime.now().isoformat(), m["id"]))
    db.commit()
    db.close()

    resp = RedirectResponse(next or "/dashboard", 302)
    resp.set_cookie(
        "_session", make_token(m["email"], m["created_at"]),
        max_age=86400 * 30, httponly=True, samesite="lax"
    )
    return resp


@router.get("/verify-email", response_class=HTMLResponse)
async def verify_email(req: Request, token: str = ""):
    if not token:
        return render(req, "verify_email.html", {
            "err": "Jeton de vérification manquant."
        })
    db = get_db()
    m = db.execute("SELECT * FROM members WHERE verify_token=? AND actif=1", (token,)).fetchone()
    if not m:
        db.close()
        return render(req, "verify_email.html", {
            "err": "Jeton invalide ou compte introuvable."
        })
    db.execute("UPDATE members SET email_verified=1, verify_token='' WHERE id=?", (m["id"],))
    db.commit()
    db.close()
    return render(req, "verify_email.html", {
        "ok": "Email vérifié ! Vous pouvez maintenant vous connecter."
    })


@router.get("/resend-verification", response_class=HTMLResponse)
async def resend_verification_get(req: Request):
    return render(req, "resend_verification.html", {})


@router.post("/resend-verification")
async def resend_verification_post(req: Request, email: str = Form("")):
    db = get_db()
    m = db.execute("SELECT * FROM members WHERE email=? AND actif=1", (email,)).fetchone()
    if m and m["email_verified"] == 0:
        token = m["verify_token"] or make_random_token()
        if not m["verify_token"]:
            db.execute("UPDATE members SET verify_token=? WHERE id=?", (token, m["id"]))
            db.commit()
        send_verification_email(email, token, m["nom"] or email)
    db.close()
    return render(req, "resend_verification.html", {
        "ok": "Si ce compte existe, un lien de vérification vient d'être envoyé."
    })


@router.get("/forgot-password", response_class=HTMLResponse)
async def forgot_password_get(req: Request):
    return render(req, "forgot_password.html", {})


@router.post("/forgot-password")
async def forgot_password_post(req: Request, email: str = Form("")):
    db = get_db()
    m = db.execute("SELECT * FROM members WHERE email=? AND actif=1", (email,)).fetchone()
    if m:
        token = make_random_token()
        db.execute("UPDATE members SET reset_token=? WHERE id=?", (token, m["id"]))
        db.commit()
        send_password_reset_email(email, token, m["nom"] or email)
    db.close()
    return render(req, "forgot_password.html", {
        "ok": "Si ce compte existe, un lien de réinitialisation a été envoyé."
    })


@router.get("/reset-password", response_class=HTMLResponse)
async def reset_password_get(req: Request, token: str = ""):
    if not token:
        return render(req, "reset_password.html", {
            "err": "Jeton de réinitialisation manquant."
        })
    db = get_db()
    m = db.execute("SELECT * FROM members WHERE reset_token=? AND actif=1", (token,)).fetchone()
    db.close()
    if not m:
        return render(req, "reset_password.html", {
            "err": "Jeton invalide ou expiré."
        })
    return render(req, "reset_password.html", {"token": token})


@router.post("/reset-password")
async def reset_password_post(req: Request,
    token: str = Form(""),
    pw:    str = Form(""),
    pw2:   str = Form(""),
):
    if not token:
        return render(req, "reset_password.html", {
            "err": "Jeton manquant."
        })
    if not pw or pw != pw2:
        return render(req, "reset_password.html", {
            "err": "Les mots de passe ne correspondent pas.",
            "token": token,
        })
    ok, msg = validate_password(pw)
    if not ok:
        return render(req, "reset_password.html", {
            "err": msg,
            "token": token,
        })
    db = get_db()
    m = db.execute("SELECT * FROM members WHERE reset_token=? AND actif=1", (token,)).fetchone()
    if not m:
        db.close()
        return render(req, "reset_password.html", {
            "err": "Jeton invalide ou expiré."
        })
    db.execute(
        "UPDATE members SET pw_hash=?, reset_token='', email_verified=1, verify_token='' WHERE id=?",
        (hash_pw(pw), m["id"])
    )
    db.commit()
    db.close()
    return render(req, "login.html", {
        "ok": "Mot de passe réinitialisé. Vous pouvez maintenant vous connecter.",
        "vals": {"email": m["email"]}
    })


@router.get("/logout")
async def logout():
    r = RedirectResponse("/", 302)
    r.delete_cookie("_session")
    return r
