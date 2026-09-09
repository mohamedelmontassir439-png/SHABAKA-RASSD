"""
Maroc Entrepreneuriat — Termes de recherche annuaire par secteur

Les libellés officiels des 83 secteurs sont rédigés pour la commande
publique, pas pour un annuaire d'entreprises. Certains fonctionnent tels
quels ("Mobilier de Bureau"), d'autres non:

  · « Électricité & éclairage public » ramenait des magasins de luminaires
    au lieu d'installateurs électriciens;
  · « Produits chimiques & para-chimiques » était tronqué en « produits
    chimiques para » et ramenait des cosmétiques;
  · « Aménagements associés aux bâtiments » ramenait les mêmes entreprises
    générales que le secteur Construction.

Ce tableau associe donc à chaque code le terme réellement utilisé par les
entreprises marocaines pour se décrire. Vérifié par échantillonnage sur
Google Maps (Casablanca, 09/09/2026).
"""
import re

from app.core.sectors import SECTORS

# Secteurs dont le libellé officiel n'est pas un terme de recherche
# exploitable: on précise l'intention métier.
REQUETES = {
    # ── Travaux ──────────────────────────────────────────────
    "T101": "entreprise de construction bâtiment",
    "T102": "entreprise de terrassement travaux publics",
    "T103": "menuiserie métallerie charpente",
    "T104": "plomberie chauffage climatisation",
    "T105": "entreprise de peinture bâtiment",
    "T106": "étanchéité isolation bâtiment",
    "T107": "revêtement de sol carrelage",
    "T108": "plâtrerie faux plafond",
    "T109": "installation maintenance ascenseurs",
    "T110": "entreprise de génie civil",
    "T111": "entreprise espaces verts paysagiste",
    "T112": "aménagement intérieur agencement",
    "T201": "entreprise assainissement canalisation",
    "T202": "fondations spéciales forage sondage",
    "T203": "traitement des eaux station épuration",
    "T204": "travaux maritimes portuaires",
    "T301": "entreprise de travaux routiers",
    "T302": "signalisation routière marquage",
    "T401": "entreprise installation électrique bâtiment",
    "T403": "installation réseaux télécom fibre",
    "T402": "installation vidéosurveillance alarme",
    "T404": "chambre froide installation frigorifique",
    "T501": "cabinet de topographie géomètre",
    "T601": "entreprise de travaux agricoles",
    # ── Équipements ──────────────────────────────────────────
    "P802": "matériel télécom et électronique",
    "P804": "matériel de sonorisation et vidéo",
    "P805": "mobilier de bureau",
    "P806": "équipement hydraulique pompes",
    "P808": "matériel topographique",
    "P810": "matériel agricole tracteurs",
    "P812": "fournisseur matériel électrique",
    "P813": "fournisseur matériel médical",
    "P814": "vente installation climatisation",
    "P815": "engins de manutention chariot élévateur",
    "P816": "concessionnaire véhicules utilitaires",
    "P817": "matériel pédagogique et didactique",
    "P818": "magasin matériel informatique",
    "P819": "magasin équipement sportif",
    "P820": "fournitures industrielles",
    "P821": "équipement de protection individuelle",
    "P822": "outillage de précision",
    "P823": "quincaillerie outillage",
    "P824": "équipement de cuisine professionnelle",
    "P825": "fournitures de bureau",
    "P830": "pièces de rechange industrielles",
    "P831": "lubrifiants et huiles industrielles",
    "P832": "produits chimiques industriels",
    "P833": "grossiste produits pharmaceutiques",
    "P834": "grossiste produits alimentaires",
    "P836": "imprimerie",
    "P837": "confection textile usine",
    "P838": "négoce métaux acier",
    "P839": "matériaux de construction",
    "P840": "magasin de meubles et literie",
    "P841": "grossiste produits d'hygiène et nettoyage",
    "P843": "matériel de laboratoire",
    "P850": "installation panneaux solaires",
    "P852": "fournisseur matériel solaire photovoltaïque",
    "P853": "entreprise énergies renouvelables",
    # ── Services ─────────────────────────────────────────────
    "S901": "société de développement informatique",
    "S902": "cabinet de conseil et études",
    "S903": "bureau d'études techniques BTP",
    "S904": "société de services aux entreprises",
    "S906": "société de maintenance industrielle",
    "S907": "société de nettoyage",
    "S908": "société de gardiennage et sécurité",
    "S909": "cabinet d'architecture",
    "S910": "agence de communication et publicité",
    "S911": "traiteur réception événement",
    "S912": "compagnie d'assurance courtier",
    "S913": "centre de formation professionnelle",
    "S914": "société de location matériel",
    "S915": "location de voitures et utilitaires",
    "S916": "bureau d'études agricole",
    "S917": "agence événementielle",
    "S918": "collecte et traitement des déchets",
    "S919": "archivage et numérisation de documents",
    "S920": "expert immobilier",
    "S921": "laboratoire d'analyses industrielles",
    "S922": "laboratoire d'analyses médicales",
    "S923": "laboratoire d'analyses BTP",
    "S930": "centre d'hébergement",
    "S931": "société développement logiciel informatique",
}

# Secteurs dont le périmètre est trop large pour un annuaire: la requête
# reste approximative, ce qui est signalé plutôt que masqué.
IMPRECIS = {"S904", "P820", "S914", "S930"}


def requete_secteur(code: str) -> str:
    """Terme de recherche annuaire pour un code secteur.

    Repli sur le libellé officiel nettoyé si le code est inconnu — un
    nouveau secteur ajouté au référentiel reste ainsi exploitable sans
    modification de ce fichier.
    """
    if code in REQUETES:
        return REQUETES[code]
    libelle = SECTORS.get(code, "")
    parties = [p.strip() for p in re.split(r"[–\-,&/]", libelle) if p.strip()]
    return " ".join(parties[:2]) if parties else libelle


def secteurs_sans_requete() -> list:
    """Codes du référentiel qui ne produisent aucun terme exploitable."""
    return [c for c in SECTORS if not requete_secteur(c).strip()]
