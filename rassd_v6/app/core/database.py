"""
ATLAS PRO — Database Layer (SQLite)
"""
import os, sqlite3, logging
from datetime import datetime
from app.core.config import cfg

logger = logging.getLogger("atlas.db")

# ── SQLite (local / Railway) ──────────────────────────────
def get_db() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(cfg.DB_PATH), exist_ok=True)
    db = sqlite3.connect(cfg.DB_PATH, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA synchronous=NORMAL")
    db.execute("PRAGMA cache_size=-32000")  # 32MB cache
    return db

# ── Schema SQLite ─────────────────────────────────────────
SCHEMA = """
CREATE TABLE IF NOT EXISTS tenders (
    id               TEXT PRIMARY KEY,
    objet            TEXT NOT NULL DEFAULT '',
    acheteur         TEXT DEFAULT '',
    secteur          TEXT DEFAULT '',
    region           TEXT DEFAULT '',
    montant          TEXT DEFAULT '',
    date_publication TEXT DEFAULT '',
    date_limite      TEXT DEFAULT '',
    description      TEXT DEFAULT '',
    url              TEXT DEFAULT '',
    statut           TEXT DEFAULT 'actif',
    views            INTEGER DEFAULT 0,
    scraped_at       TEXT DEFAULT '',
    updated_at       TEXT DEFAULT '',
    type_offre       TEXT DEFAULT 'Public',
    source           TEXT DEFAULT 'marchespublics',
    type_procedure   TEXT DEFAULT 'marche'
);
CREATE TABLE IF NOT EXISTS members (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    nom          TEXT DEFAULT '',
    email        TEXT UNIQUE NOT NULL,
    phone        TEXT DEFAULT '',
    company      TEXT DEFAULT '',
    pw_hash      TEXT DEFAULT '',
    plan         TEXT DEFAULT 'free',
    secteurs     TEXT DEFAULT '[]',
    regions      TEXT DEFAULT '[]',
    telegram     TEXT DEFAULT '',
    notif_email  INTEGER DEFAULT 1,
    notif_tg     INTEGER DEFAULT 0,
    notif_digest INTEGER DEFAULT 1,
    actif        INTEGER DEFAULT 1,
    created_at   TEXT DEFAULT '',
    trial_ends   TEXT DEFAULT '',
    last_login   TEXT DEFAULT '',
    session_token  TEXT DEFAULT '',
    whatsapp       TEXT DEFAULT '',
    notif_wa       INTEGER DEFAULT 0,
    reset_token    TEXT DEFAULT '',
    reset_expires  TEXT DEFAULT '',
    onboarded      INTEGER DEFAULT 0,
    last_digest_sent TEXT DEFAULT '',
    referral_code    TEXT DEFAULT '',
    referred_by      INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS favorites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id INTEGER NOT NULL,
    tender_id TEXT NOT NULL,
    created_at TEXT DEFAULT '',
    UNIQUE(member_id, tender_id)
);
CREATE TABLE IF NOT EXISTS notif_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id INTEGER,
    tender_id TEXT,
    channel TEXT,
    sent_at TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS scrape_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    found INTEGER DEFAULT 0,
    saved INTEGER DEFAULT 0,
    errors INTEGER DEFAULT 0,
    run_at TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS feedback (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id  INTEGER,
    email      TEXT DEFAULT '',
    message    TEXT DEFAULT '',
    features   TEXT DEFAULT '[]',
    rating     INTEGER DEFAULT 0,
    created_at TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS tender_results (
    id                TEXT PRIMARY KEY,
    reference         TEXT DEFAULT '',
    objet             TEXT DEFAULT '',
    acheteur          TEXT DEFAULT '',
    adjudicataire     TEXT DEFAULT '',
    region            TEXT DEFAULT '',
    budget            TEXT DEFAULT '',
    montant           TEXT DEFAULT '',
    secteur           TEXT DEFAULT '',
    date_adjudication TEXT DEFAULT '',
    date_ouverture    TEXT DEFAULT '',
    date_affichage    TEXT DEFAULT '',
    dao_url           TEXT DEFAULT '',
    pv_url            TEXT DEFAULT '',
    scraped_at        TEXT DEFAULT '',
    type_procedure    TEXT DEFAULT 'marche'
);

CREATE TABLE IF NOT EXISTS subcontract_posts (
    id           TEXT PRIMARY KEY,
    member_id    INTEGER NOT NULL,
    type         TEXT DEFAULT 'demande',
    titre        TEXT DEFAULT '',
    secteur      TEXT DEFAULT '',
    region       TEXT DEFAULT '',
    budget       TEXT DEFAULT '',
    date_limite  TEXT DEFAULT '',
    description  TEXT DEFAULT '',
    statut       TEXT DEFAULT 'actif',
    created_at   TEXT DEFAULT ''
);
-- Invitations envoyées aux entreprises collectées. Le jeton est personnel:
-- il pré-remplit le profil de sous-traitance et permet de savoir quelles
-- campagnes convertissent, entreprise par entreprise.
CREATE TABLE IF NOT EXISTS invitations (
    token      TEXT PRIMARY KEY,
    company_id INTEGER NOT NULL,
    canal      TEXT DEFAULT '',
    created_at TEXT DEFAULT '',
    sent_at    TEXT DEFAULT '',
    opened_at  TEXT DEFAULT '',
    member_id  INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_inv_company ON invitations(company_id);
CREATE INDEX IF NOT EXISTS idx_inv_member  ON invitations(member_id);

-- Profil de sous-traitance: ce qu'une entreprise sait faire, où, et avec
-- quels moyens. Sans lui, une annonce ne dit rien de celui qui la publie.
CREATE TABLE IF NOT EXISTS subcontract_profiles (
    member_id      INTEGER PRIMARY KEY,
    raison_sociale TEXT DEFAULT '',
    metiers        TEXT DEFAULT '[]',
    zones          TEXT DEFAULT '[]',
    effectif       TEXT DEFAULT '',
    moyens         TEXT DEFAULT '',
    experience     TEXT DEFAULT '',
    references_txt TEXT DEFAULT '',
    certifications TEXT DEFAULT '',
    disponible     INTEGER DEFAULT 1,
    created_at     TEXT DEFAULT '',
    updated_at     TEXT DEFAULT ''
);
-- Offres structurées: un prix, un délai et des références se comparent;
-- une conversation libre ne se compare pas.
CREATE TABLE IF NOT EXISTS subcontract_offers (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id     TEXT NOT NULL,
    member_id   INTEGER NOT NULL,
    prix        TEXT DEFAULT '',
    delai       TEXT DEFAULT '',
    message     TEXT DEFAULT '',
    piece_jointe TEXT DEFAULT '',
    statut      TEXT DEFAULT 'envoyee',
    created_at  TEXT DEFAULT '',
    updated_at  TEXT DEFAULT '',
    UNIQUE(post_id, member_id)
);
CREATE INDEX IF NOT EXISTS idx_so_post   ON subcontract_offers(post_id);
CREATE INDEX IF NOT EXISTS idx_so_member ON subcontract_offers(member_id);
CREATE TABLE IF NOT EXISTS subcontract_messages (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id      TEXT NOT NULL,
    sender_id    INTEGER NOT NULL,
    recipient_id INTEGER NOT NULL,
    body         TEXT DEFAULT '',
    created_at   TEXT DEFAULT '',
    read_at      TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS subcontract_ratings (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id    TEXT NOT NULL,
    rater_id   INTEGER NOT NULL,
    rated_id   INTEGER NOT NULL,
    rating     INTEGER DEFAULT 5,
    comment    TEXT DEFAULT '',
    created_at TEXT DEFAULT '',
    UNIQUE(post_id, rater_id, rated_id)
);
CREATE TABLE IF NOT EXISTS notif_queue (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id  INTEGER NOT NULL,
    tender_id  TEXT NOT NULL,
    created_at TEXT DEFAULT '',
    UNIQUE(member_id, tender_id)
);
-- File du résumé WhatsApp quotidien: un marché correspondant est mis en
-- file au moment du scraping, puis envoyé dans un seul message par jour.
CREATE TABLE IF NOT EXISTS wa_digest_queue (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id  INTEGER NOT NULL,
    tender_id  TEXT NOT NULL,
    created_at TEXT DEFAULT '',
    sent_at    TEXT DEFAULT '',
    UNIQUE(member_id, tender_id)
);
-- ── Abonnements / paiements ────────────────────────────────
-- Le paiement est encaissé hors plateforme (virement, espèces, WhatsApp) puis
-- enregistré par l'admin : ces tables tracent la réalité comptable, elles ne
-- simulent aucune passerelle de paiement.
CREATE TABLE IF NOT EXISTS subscriptions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id    INTEGER NOT NULL,
    plan_id      TEXT DEFAULT 'monthly',
    price        REAL DEFAULT 0,
    currency     TEXT DEFAULT 'MAD',
    status       TEXT DEFAULT 'TRIAL',
    start_date   TEXT DEFAULT '',
    end_date     TEXT DEFAULT '',
    trial_start  TEXT DEFAULT '',
    trial_end    TEXT DEFAULT '',
    payment_id   INTEGER DEFAULT 0,
    created_at   TEXT DEFAULT '',
    updated_at   TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS payments (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id       INTEGER NOT NULL,
    subscription_id INTEGER DEFAULT 0,
    amount          REAL DEFAULT 0,
    currency        TEXT DEFAULT 'MAD',
    method          TEXT DEFAULT '',
    reference       TEXT DEFAULT '',
    status          TEXT DEFAULT 'PAID',
    period_start    TEXT DEFAULT '',
    period_end      TEXT DEFAULT '',
    paid_at         TEXT DEFAULT '',
    recorded_by     TEXT DEFAULT 'admin',
    note            TEXT DEFAULT '',
    created_at      TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS documents (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_type        TEXT DEFAULT 'receipt',
    number          TEXT DEFAULT '',
    member_id       INTEGER NOT NULL,
    subscription_id INTEGER DEFAULT 0,
    payment_id      INTEGER DEFAULT 0,
    payload         TEXT DEFAULT '{}',
    accepted_at     TEXT DEFAULT '',
    accepted_ip     TEXT DEFAULT '',
    created_at      TEXT DEFAULT ''
);
-- ── Base entreprises (intelligence commerciale) ────────────
-- normalized_name sert de clé de rapprochement: c'est le nom réduit à sa
-- forme canonique (sans accents, sans forme juridique, sans ponctuation),
-- ce qui permet de reconnaître "STE ATLAS BTP SARL" et "Atlas B.T.P. S.A.R.L"
-- comme une seule et même entreprise.
CREATE TABLE IF NOT EXISTS companies (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    legal_name       TEXT DEFAULT '',
    trade_name       TEXT DEFAULT '',
    normalized_name  TEXT DEFAULT '',
    sector           TEXT DEFAULT '',
    subsector        TEXT DEFAULT '',
    city             TEXT DEFAULT '',
    region           TEXT DEFAULT '',
    address          TEXT DEFAULT '',
    phone            TEXT DEFAULT '',
    mobile           TEXT DEFAULT '',
    email            TEXT DEFAULT '',
    website          TEXT DEFAULT '',
    ice              TEXT DEFAULT '',
    if_num           TEXT DEFAULT '',
    rc               TEXT DEFAULT '',
    source           TEXT DEFAULT '',
    source_url       TEXT DEFAULT '',
    source_type      TEXT DEFAULT '',
    wins             INTEGER DEFAULT 0,
    verified         INTEGER DEFAULT 0,
    last_verified_at TEXT DEFAULT '',
    created_at       TEXT DEFAULT '',
    updated_at       TEXT DEFAULT ''
);
-- Chaque source d'où provient une entreprise est conservée: on ne supprime
-- jamais une provenance en fusionnant deux doublons.
CREATE TABLE IF NOT EXISTS company_sources (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id  INTEGER NOT NULL,
    source      TEXT DEFAULT '',
    source_url  TEXT DEFAULT '',
    raw_name    TEXT DEFAULT '',
    seen_at     TEXT DEFAULT ''
);
-- ── Registre de conformité des sources (§28) ───────────────
CREATE TABLE IF NOT EXISTS source_registry (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    source_name      TEXT UNIQUE NOT NULL,
    source_type      TEXT DEFAULT '',
    domain           TEXT DEFAULT '',
    source_url       TEXT DEFAULT '',
    access_method    TEXT DEFAULT '',
    robots_status    TEXT DEFAULT 'unknown',
    terms_checked    INTEGER DEFAULT 0,
    scraping_allowed TEXT DEFAULT 'unknown',
    api_available    INTEGER DEFAULT 0,
    status           TEXT DEFAULT 'active',
    last_checked     TEXT DEFAULT '',
    notes            TEXT DEFAULT ''
);
-- ── Exécutions de scraper, par source (§24) ────────────────
CREATE TABLE IF NOT EXISTS scraper_runs (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    source         TEXT DEFAULT '',
    status         TEXT DEFAULT 'RUNNING',
    records_found  INTEGER DEFAULT 0,
    records_saved  INTEGER DEFAULT 0,
    duplicates     INTEGER DEFAULT 0,
    errors         INTEGER DEFAULT 0,
    duration_ms    INTEGER DEFAULT 0,
    message        TEXT DEFAULT '',
    started_at     TEXT DEFAULT '',
    finished_at    TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS subcontract_reports (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id     TEXT NOT NULL,
    reporter_id INTEGER NOT NULL,
    reason      TEXT DEFAULT '',
    created_at  TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS error_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    path       TEXT DEFAULT '',
    method     TEXT DEFAULT '',
    message    TEXT DEFAULT '',
    traceback  TEXT DEFAULT '',
    created_at TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_t_statut   ON tenders(statut);
CREATE INDEX IF NOT EXISTS idx_t_scraped  ON tenders(scraped_at DESC);
CREATE INDEX IF NOT EXISTS idx_t_secteur  ON tenders(secteur);
CREATE INDEX IF NOT EXISTS idx_t_deadline ON tenders(date_limite);
CREATE INDEX IF NOT EXISTS idx_t_type     ON tenders(type_offre);
CREATE INDEX IF NOT EXISTS idx_t_proc     ON tenders(type_procedure);
CREATE INDEX IF NOT EXISTS idx_m_email    ON members(email);
CREATE INDEX IF NOT EXISTS idx_fav_member ON favorites(member_id);
-- La déduplication des alertes interroge notif_log pour CHAQUE couple
-- membre × marché. Sans index, SQLite parcourait toute la table à chaque
-- vérification: des dizaines de milliers de lignes lues par cycle de veille.
CREATE INDEX IF NOT EXISTS idx_nl_membre_marche ON notif_log(member_id, tender_id);
CREATE INDEX IF NOT EXISTS idx_nl_tender        ON notif_log(tender_id);
CREATE INDEX IF NOT EXISTS idx_nl_sent          ON notif_log(sent_at DESC);
-- Index composite pour la requête la plus fréquente du site: les marchés
-- ouverts d'un secteur, du plus récent au plus ancien.
CREATE INDEX IF NOT EXISTS idx_t_actif_secteur  ON tenders(statut, secteur, scraped_at DESC);
CREATE INDEX IF NOT EXISTS idx_r_scraped  ON tender_results(scraped_at DESC);
CREATE INDEX IF NOT EXISTS idx_r_secteur  ON tender_results(secteur);
CREATE INDEX IF NOT EXISTS idx_sp_statut  ON subcontract_posts(statut);
CREATE INDEX IF NOT EXISTS idx_sp_type    ON subcontract_posts(type);
CREATE INDEX IF NOT EXISTS idx_sp_member  ON subcontract_posts(member_id);
CREATE INDEX IF NOT EXISTS idx_sm_post    ON subcontract_messages(post_id);
CREATE INDEX IF NOT EXISTS idx_sm_sender  ON subcontract_messages(sender_id);
CREATE INDEX IF NOT EXISTS idx_sm_recip   ON subcontract_messages(recipient_id);
CREATE INDEX IF NOT EXISTS idx_sr_post    ON subcontract_ratings(post_id);
CREATE INDEX IF NOT EXISTS idx_sr_rated   ON subcontract_ratings(rated_id);
CREATE INDEX IF NOT EXISTS idx_nq_member  ON notif_queue(member_id);
CREATE INDEX IF NOT EXISTS idx_waq_member ON wa_digest_queue(member_id, sent_at);
CREATE INDEX IF NOT EXISTS idx_srep_post  ON subcontract_reports(post_id);
CREATE INDEX IF NOT EXISTS idx_err_created ON error_log(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_sub_member  ON subscriptions(member_id);
CREATE INDEX IF NOT EXISTS idx_sub_status  ON subscriptions(status);
CREATE INDEX IF NOT EXISTS idx_pay_member  ON payments(member_id);
CREATE INDEX IF NOT EXISTS idx_pay_paid    ON payments(paid_at DESC);
-- Suivi de prospection: une ligne par entreprise contactée ou à contacter.
-- Le refus d'être rappelé est une donnée à conserver (loi 09-08): on ne
-- supprime pas la fiche, on la marque, sinon la même entreprise ressort à
-- la prochaine campagne.
CREATE TABLE IF NOT EXISTS prospection (
    company_id      INTEGER PRIMARY KEY,
    statut          TEXT DEFAULT 'a_appeler',
    canal           TEXT DEFAULT '',
    notes           TEXT DEFAULT '',
    dernier_contact TEXT DEFAULT '',
    prochain_contact TEXT DEFAULT '',
    appels          INTEGER DEFAULT 0,
    created_at      TEXT DEFAULT '',
    updated_at      TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_prosp_statut ON prospection(statut);
CREATE INDEX IF NOT EXISTS idx_prosp_next   ON prospection(prochain_contact);
CREATE INDEX IF NOT EXISTS idx_doc_member  ON documents(member_id);
CREATE INDEX IF NOT EXISTS idx_doc_number  ON documents(number);
CREATE INDEX IF NOT EXISTS idx_co_norm     ON companies(normalized_name);
CREATE INDEX IF NOT EXISTS idx_co_sector   ON companies(sector);
CREATE INDEX IF NOT EXISTS idx_co_region   ON companies(region);
CREATE INDEX IF NOT EXISTS idx_co_ice      ON companies(ice);
CREATE INDEX IF NOT EXISTS idx_co_wins     ON companies(wins DESC);
CREATE INDEX IF NOT EXISTS idx_cosrc_co    ON company_sources(company_id);
CREATE INDEX IF NOT EXISTS idx_srun_src    ON scraper_runs(source);
CREATE INDEX IF NOT EXISTS idx_srun_start  ON scraper_runs(started_at DESC);
"""

def migrate_db():
    """Ajoute les colonnes manquantes si nécessaire.

    Les erreurs 'duplicate column' sont ignorées (normal = colonne déjà présente).
    Les autres erreurs sont loguées mais n'arrêtent pas le processus.
    """
    db = get_db()
    cols = [
        "ALTER TABLE members ADD COLUMN session_token TEXT DEFAULT ''",
        "ALTER TABLE members ADD COLUMN whatsapp TEXT DEFAULT ''",
        "ALTER TABLE members ADD COLUMN notif_wa INTEGER DEFAULT 0",
        "ALTER TABLE members ADD COLUMN reset_token TEXT DEFAULT ''",
        "ALTER TABLE members ADD COLUMN reset_expires TEXT DEFAULT ''",
        "ALTER TABLE members ADD COLUMN onboarded INTEGER DEFAULT 0",
        "ALTER TABLE tenders ADD COLUMN type_offre TEXT DEFAULT 'Public'",
        "ALTER TABLE tenders ADD COLUMN source TEXT DEFAULT 'marchespublics'",
        "ALTER TABLE members ADD COLUMN last_digest_sent TEXT DEFAULT ''",
        "ALTER TABLE members ADD COLUMN referral_code TEXT DEFAULT ''",
        "ALTER TABLE members ADD COLUMN referred_by INTEGER DEFAULT 0",
        "ALTER TABLE tenders ADD COLUMN type_procedure TEXT DEFAULT 'marche'",
        "ALTER TABLE tender_results ADD COLUMN type_procedure TEXT DEFAULT 'marche'",
        # Abonnement / essai gratuit
        "ALTER TABLE members ADD COLUMN trial_start TEXT DEFAULT ''",
        "ALTER TABLE members ADD COLUMN subscription_status TEXT DEFAULT ''",
        "ALTER TABLE members ADD COLUMN subscription_end TEXT DEFAULT ''",
        "ALTER TABLE members ADD COLUMN email_verified INTEGER DEFAULT 0",
        "ALTER TABLE members ADD COLUMN whatsapp_verified INTEGER DEFAULT 0",
        # Consentement WhatsApp + vérification du numéro
        "ALTER TABLE members ADD COLUMN wa_optin_at TEXT DEFAULT ''",
        "ALTER TABLE members ADD COLUMN wa_verify_code TEXT DEFAULT ''",
        "ALTER TABLE members ADD COLUMN wa_verify_expires TEXT DEFAULT ''",
        # Filtres d'alerte (moteur de correspondance)
        "ALTER TABLE members ADD COLUMN notif_regions TEXT DEFAULT '[]'",
        "ALTER TABLE members ADD COLUMN notif_keywords TEXT DEFAULT ''",
        "ALTER TABLE members ADD COLUMN notif_min_budget INTEGER DEFAULT 0",
        "ALTER TABLE members ADD COLUMN notif_types TEXT DEFAULT '[]'",
        "ALTER TABLE members ADD COLUMN last_wa_digest TEXT DEFAULT ''",
        # Vérification de l'adresse email (lien envoyé à l'inscription)
        "ALTER TABLE members ADD COLUMN email_token_expires TEXT DEFAULT ''",
        # Un avis sur bon de commande ne publie jamais d'estimation, mais il
        # publie la nature de la prestation et la quantité demandée: les
        # afficher vaut mieux qu'une case « montant » vide.
        "ALTER TABLE tenders ADD COLUMN nature TEXT DEFAULT ''",
        "ALTER TABLE tenders ADD COLUMN quantite TEXT DEFAULT ''",
        # Séquence d'emails pendant l'essai gratuit (étape déjà envoyée)
        "ALTER TABLE members ADD COLUMN trial_seq INTEGER DEFAULT 0",
        # Rythme des alertes email: « direct » (un email par marché) ou
        # « quotidien » (un seul email groupé le matin). Un secteur actif
        # publie jusqu'à 48 marchés par jour: le choix est vital.
        "ALTER TABLE members ADD COLUMN notif_rythme TEXT DEFAULT 'direct'",
        "ALTER TABLE members ADD COLUMN last_daily_digest TEXT DEFAULT ''",
        # Une annonce de sous-traitance née d'un marché garde le lien vers lui:
        # l'objet, l'acheteur et l'échéance viennent alors de la source.
        "ALTER TABLE subcontract_posts ADD COLUMN tender_id TEXT DEFAULT ''",
        "ALTER TABLE subcontract_posts ADD COLUMN part_marche TEXT DEFAULT ''",
        # Journal de notification: statut de livraison
        "ALTER TABLE notif_log ADD COLUMN status TEXT DEFAULT 'SENT'",
        "ALTER TABLE notif_log ADD COLUMN error TEXT DEFAULT ''",
        "ALTER TABLE notif_log ADD COLUMN provider TEXT DEFAULT ''",
        # Horodatage du passage devant le moteur de correspondance. Le
        # rattrapage se fondait sur l'absence de ligne dans notif_log, mais un
        # marché qu'aucun filtre ne retient n'en produit aucune: il était donc
        # resélectionné à chaque cycle, indéfiniment. La requête étant
        # plafonnée, ces marchés occupaient la fenêtre en permanence et une
        # alerte réellement manquée, plus ancienne, n'était jamais reprise.
        "ALTER TABLE tenders ADD COLUMN alertes_faites_at TEXT DEFAULT ''",
        # Instant à partir duquel un membre reçoit des alertes marché par
        # marché. Sans cette borne, un nouvel inscrit recevait tout le
        # rattrapage des 48 dernières heures: mesuré le 29/09/2026 sur un
        # compte de test, plus de 55 emails en trois heures. Ce qui existait
        # avant son arrivée lui est présenté en un seul message de bienvenue.
        # Format aligné sur tenders.scraped_at ('YYYY-MM-DD HH:MM:SS'):
        # members.created_at est en isoformat (séparateur 'T'), et 'T' > ' '
        # en comparaison de chaînes — les deux ne se comparent pas directement.
        "ALTER TABLE members ADD COLUMN alertes_depuis TEXT DEFAULT ''",
        # Montant de l'adjudication en nombre. La colonne texte reste la
        # source affichée; celle-ci n'existe que pour filtrer et trier, ce que
        # « 5.916.000,00 » et « 6.720.600.00 » — deux formats présents dans la
        # même table — interdisent en SQL.
        "ALTER TABLE tender_results ADD COLUMN montant_num REAL DEFAULT 0",
        # Nature de l'organisme acheteur: Etat, para-public ou prive. La
        # colonne type_offre existante ne porte pas cette information: elle
        # dit d'ou vient l'avis, pas qui achete. Mesure le 01/10/2026: cent
        # soixante-sept avis d'etablissements publics, dont cent dix classes
        # « Public » et cinquante-sept « Prive » selon la source.
        "ALTER TABLE tenders ADD COLUMN organisme TEXT DEFAULT ''",
        # Nom de l'attributaire reduit a sa forme comparable. Le rapprochement
        # avec l'annuaire se faisait sur « LOWER(TRIM(adjudicataire)) », donc
        # un nom brut face a un nom deja nettoye cote annuaire: « ZEF
        # SCIENTIFIC SARL AU » ne rencontrait jamais « zef scientific ».
        # Mesure du 01/10/2026: 84 rapprochements sur 246 attributaires, 196
        # une fois les deux cotes normalises.
        "ALTER TABLE tender_results ADD COLUMN adjudicataire_norm TEXT DEFAULT ''",
        # Fiche de l'entreprise dans un annuaire professionnel externe,
        # quand elle existe: Global Marché ne publie pas les contacts des
        # attributaires, un annuaire tiers peut les avoir.
        "ALTER TABLE companies ADD COLUMN annuaire_url TEXT DEFAULT ''",
    ]
    # Le lot du soir: ce qui sera envoyé à la main le lendemain matin.
    # Une ligne par membre et par jour — figée à la préparation, pour que
    # la liste ne bouge plus entre le moment où on l'ouvre et celui où on
    # envoie, et pour savoir qui a déjà reçu son message.
    db.execute("""CREATE TABLE IF NOT EXISTS recap_envois(
        member_id   INTEGER NOT NULL,
        jour        TEXT    NOT NULL,
        nombre      INTEGER DEFAULT 0,
        prepare_at  TEXT    DEFAULT '',
        envoye_at   TEXT    DEFAULT '',
        canal       TEXT    DEFAULT '',
        PRIMARY KEY (member_id, jour))""")
    db.execute("CREATE INDEX IF NOT EXISTS idx_recap_jour ON recap_envois(jour)")
    db.commit()
    cols = cols + [
    ]
    for col in cols:
        try:
            db.execute(col)
            db.commit()
        except sqlite3.OperationalError as e:
            # 'duplicate column name' = colonne existe déjà, c'est OK
            if "duplicate column" not in str(e).lower():
                logger.warning(f"[migrate] {col[:50]}...: {e}")
        except Exception as e:
            logger.error(f"[migrate] Erreur inattendue: {e}")

    # Normalisation des attributaires deja en base, pour que l'annuaire les
    # reconnaisse. Le calcul vit en Python: il retire les formes juridiques
    # et les mots vides, ce que SQL ne sait pas decrire.
    try:
        from app.services.companies import normalize_company_name
        a_normaliser = db.execute(
            "SELECT id, adjudicataire FROM tender_results "
            "WHERE COALESCE(adjudicataire_norm,'')='' AND COALESCE(adjudicataire,'')<>''"
        ).fetchall()
        for ligne in a_normaliser:
            db.execute("UPDATE tender_results SET adjudicataire_norm=? WHERE id=?",
                       (normalize_company_name(ligne["adjudicataire"]), ligne["id"]))
        if a_normaliser:
            db.commit()
            logger.info(f"[migrate] {len(a_normaliser)} attributaire(s) normalises")
        db.execute("CREATE INDEX IF NOT EXISTS idx_tr_adj_norm "
                   "ON tender_results(adjudicataire_norm)")
        db.commit()
    except Exception as e:
        logger.warning(f"[migrate] adjudicataire_norm: {e}")

    # Classement des acheteurs deja en base. Le calcul vit en Python: il
    # reconnait des sigles et des expressions que SQL ne sait pas decrire.
    try:
        from app.core.organismes import categorie
        a_classer = db.execute(
            "SELECT id, acheteur, type_offre FROM tenders "
            "WHERE COALESCE(organisme,'')=''").fetchall()
        for ligne in a_classer:
            db.execute("UPDATE tenders SET organisme=? WHERE id=?",
                       (categorie(ligne["acheteur"], ligne["type_offre"]), ligne["id"]))
        if a_classer:
            db.commit()
            logger.info(f"[migrate] {len(a_classer)} acheteur(s) classes par nature")
    except Exception as e:
        logger.warning(f"[migrate] organisme: {e}")

    try:
        db.execute("CREATE INDEX IF NOT EXISTS idx_t_organisme "
                   "ON tenders(statut, organisme)")
        db.commit()
    except Exception as e:
        logger.warning(f"[migrate] index organisme: {e}")

    # Remplissage de montant_num pour les résultats déjà en base. Le parsing
    # vit en Python: SQLite ne sait pas départager le séparateur décimal du
    # séparateur de milliers sur ces deux formats.
    try:
        from app.services.soustraitance import parse_montant
        # Au-dela du plafond, la valeur stockee vient de l'ancienne lecture
        # qui collait les chiffres des marches lotis bout a bout: elle doit
        # etre recalculee, pas conservee.
        from app.services.soustraitance import PLAFOND_MONTANT
        a_convertir = db.execute(
            "SELECT id, montant FROM tender_results "
            "WHERE COALESCE(montant,'')<>'' "
            "  AND (COALESCE(montant_num,0)=0 OR montant_num > ?)",
            (PLAFOND_MONTANT,)).fetchall()
        for ligne in a_convertir:
            db.execute("UPDATE tender_results SET montant_num=? WHERE id=?",
                       (parse_montant(ligne["montant"]), ligne["id"]))
        if a_convertir:
            db.commit()
            logger.info(f"[migrate] {len(a_convertir)} montant(s) de résultat convertis")
    except Exception as e:
        logger.warning(f"[migrate] montant_num: {e}")

    try:
        db.execute("CREATE INDEX IF NOT EXISTS idx_tr_filtres "
                   "ON tender_results(type_procedure, secteur, montant_num)")
        db.commit()
    except Exception as e:
        logger.warning(f"[migrate] index résultats: {e}")

    # Les comptes ouverts avant cette borne prennent leur date d'inscription.
    # Idempotent: seuls les champs restés vides sont touchés, donc une valeur
    # posée plus tard à la confirmation d'adresse n'est jamais écrasée.
    try:
        db.execute("""UPDATE members
                      SET alertes_depuis = REPLACE(SUBSTR(created_at, 1, 19), 'T', ' ')
                      WHERE COALESCE(alertes_depuis,'') = ''
                        AND COALESCE(created_at,'') <> ''""")
        db.commit()
    except Exception as e:
        logger.warning(f"[migrate] alertes_depuis: {e}")

    # Posé après les ALTER: l'index porte sur une colonne que la boucle
    # ci-dessus vient seulement d'ajouter aux bases existantes.
    try:
        db.execute("CREATE INDEX IF NOT EXISTS idx_t_rattrapage "
                   "ON tenders(statut, alertes_faites_at, scraped_at)")
        db.commit()
    except Exception as e:
        logger.warning(f"[migrate] index rattrapage: {e}")

    # La colonne email_token n'est ajoutée qu'une fois: sa création sert de
    # marqueur pour dater l'arrivée de la vérification par email. Les comptes
    # ouverts avant n'ont jamais reçu de lien, donc on les considère vérifiés
    # — sinon ils perdraient l'accès du jour au lendemain sans rien avoir fait.
    try:
        db.execute("ALTER TABLE members ADD COLUMN email_token TEXT DEFAULT ''")
        db.execute("UPDATE members SET email_verified=1")
        db.commit()
        logger.info("[migrate] vérification email activée — comptes existants validés")
    except sqlite3.OperationalError as e:
        if "duplicate column" not in str(e).lower():
            logger.warning(f"[migrate] email_token: {e}")
    except Exception as e:
        logger.error(f"[migrate] email_token: {e}")
    db.close()

def seed_source_registry():
    """Enregistre les sources exploitées et leur statut de conformité (§28).

    Les valeurs consignées correspondent à des vérifications réelles, pas à
    des suppositions: au 07/09/2026, marchespublics.gov.ma renvoie 403 sur
    /robots.txt (aucun fichier servi) et global-marches.com renvoie une page
    HTML applicative à la place d'un robots.txt (donc aucun fichier non plus).
    L'admin peut corriger ces champs depuis /admin/sources.
    """
    rows = [
        # source_name, type, domain, url, access, robots, terms_checked, allowed, api, status, notes
        ("marchespublics", "public", "marchespublics.gov.ma",
         "https://www.marchespublics.gov.ma", "http_public", "unavailable_403", 0, "public_data", 0, "active",
         "Portail officiel des marchés publics. /robots.txt renvoie 403 — aucune directive publiée. "
         "Données de commande publique par nature publiques. Rythme de requêtes volontairement modéré."),
        ("global-marches", "private_aggregator", "global-marches.com",
         "https://global-marches.com", "authenticated_account", "absent", 0, "partner_agreement", 0, "active",
         "Agrégateur privé (AO privés + bons de commande). Accès via un compte fourni par l'éditeur "
         "du site. À formaliser par un accord écrit (licence de données ou API) — un accord verbal ne "
         "protège pas la continuité du service. Nom de la source jamais exposé aux utilisateurs finaux."),
        ("tender_results", "derived", "", "", "internal", "n/a", 1, "own_data", 0, "active",
         "Données dérivées des résultats d'adjudication déjà collectés — sert de base à la table companies."),
    ]
    # Sources retirées définitivement: deux bloquaient les robots (403) et les
    # autres ne renvoyaient plus que la navigation de leur site. Les laisser
    # dans le registre ferait croire à une couverture qui n'existe pas.
    obsoletes = ("ONDA", "ONEE", "ONCF", "IAM", "SNRT", "Le Matin",
                 "Crédit Agricole", "BCP", "Équipement", "AMMC", "Marsa Maroc",
                 "RADEEM", "LYDEC", "Min. Santé", "Min. Éducation")
    db = get_db()
    try:
        for r in rows:
            db.execute(
                """INSERT OR IGNORE INTO source_registry
                   (source_name,source_type,domain,source_url,access_method,robots_status,
                    terms_checked,scraping_allowed,api_available,status,last_checked,notes)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (*r[:10], datetime.now().strftime("%Y-%m-%d"), r[10]))
        ph = ",".join("?" * len(obsoletes))
        db.execute(f"DELETE FROM source_registry WHERE source_name IN ({ph})", obsoletes)
        db.commit()
    except Exception as e:
        logger.error(f"[seed_source_registry] {e}")
    finally:
        db.close()

def migrate_subscriptions():
    """Renseigne subscription_status pour les membres créés avant la mise en
    place de l'essai gratuit.

    Prudence volontaire: les membres 'free' existants sont marqués EXPIRED et
    non TRIAL. Sans cela, l'activation du contrôle d'accès basé sur l'essai
    ouvrirait rétroactivement l'accès complet à d'anciens comptes jamais
    payants (leur trial_ends de 14 jours ayant pu être écrit récemment), ce que
    l'admin n'a jamais validé. Seules les nouvelles inscriptions bénéficient de
    l'essai de 7 jours. Idempotent: ne touche que les lignes non renseignées.
    """
    db = get_db()
    try:
        rows = db.execute(
            "SELECT id, plan FROM members WHERE subscription_status IS NULL OR subscription_status=''"
        ).fetchall()
        for row in rows:
            status = "ACTIVE" if row["plan"] in ("pro", "business") else "EXPIRED"
            db.execute("UPDATE members SET subscription_status=? WHERE id=?", (status, row["id"]))
        if rows:
            db.commit()
            logger.info(f"✅ {len(rows)} membre(s) migré(s) vers le suivi d'abonnement")
    except Exception as e:
        logger.error(f"[migrate_subscriptions] {e}")
    finally:
        db.close()

def migrate_secteurs():
    """Reclassifie les marchés scrapés avant le passage aux codes officiels MB SA
    (l'ancien scraper stockait des libellés libres du type "Travaux BTP" qui ne
    correspondent à aucun code choisi par les membres — les alertes ne
    partaient donc jamais pour eux). Ne retouche que les lignes invalides,
    donc ne coûte rien une fois toutes les lignes migrées.
    """
    from app.core.sectors import SECTORS, classify
    db = get_db()
    try:
        rows = db.execute(
            "SELECT id, objet, description FROM tenders WHERE secteur NOT IN ({})".format(
                ",".join("?" * len(SECTORS))),
            list(SECTORS.keys())
        ).fetchall()
        for row in rows:
            code = classify(f"{row['objet']} {row['description'][:400]}")
            db.execute("UPDATE tenders SET secteur=? WHERE id=?", (code, row["id"]))
        if rows:
            db.commit()
            logger.info(f"✅ {len(rows)} marchés reclassifiés vers les codes officiels")
    except Exception as e:
        logger.error(f"[migrate_secteurs] {e}")
    finally:
        db.close()

def init_db():
    """Initialise le schéma de la base de données.

    Exécute chaque statement SQL séparément pour que les tables déjà existantes
    ne bloquent pas la création des nouvelles.
    """
    db = get_db()
    for stmt in SCHEMA.split(";"):
        s = stmt.strip()
        if s:
            try:
                db.execute(s)
            except sqlite3.OperationalError as e:
                # Table/index déjà présent = OK
                if "already exists" not in str(e).lower():
                    logger.warning(f"[init_db] {s[:60]}...: {e}")
            except Exception as e:
                logger.error(f"[init_db] Erreur: {e}")
    db.commit()
    db.close()
    logger.info("✅ DB initialisée")
    try:
        migrate_db()
    except Exception as e:
        logger.error(f"[init_db] Erreur migration: {e}")
    try:
        migrate_subscriptions()
    except Exception as e:
        logger.error(f"[init_db] Erreur migration abonnements: {e}")
    try:
        seed_source_registry()
    except Exception as e:
        logger.error(f"[init_db] Erreur registre des sources: {e}")
    try:
        migrate_secteurs()
    except Exception as e:
        logger.error(f"[init_db] Erreur migration secteurs: {e}")
