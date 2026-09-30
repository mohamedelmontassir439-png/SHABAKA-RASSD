# -*- coding: utf-8 -*-
"""Identité visuelle: un seul endroit d'où sort le logo.

Le logo apparaît sur le site, dans les emails, sur l'icône de l'application
et sur les documents qu'un membre imprime pour les remettre à un maître
d'ouvrage. Le dessiner à chaque endroit garantissait qu'il finirait
différent partout; il est donc produit ici, et partout appelé.

Format SVG plutôt qu'une image: le trait reste net du favicon de 16 pixels
à l'en-tête imprimé en A4, le fichier pèse quelques centaines d'octets, et
il s'insère dans un email ou une page sans requête supplémentaire.

Le dessin: un disque coupé en deux, le nom logé dans la fente. Le cercle
dit le territoire, la coupure dit la mise en relation — une entreprise d'un
côté, un marché de l'autre.
"""

# Couleurs de la plateforme (variables CSS --gold, --terra, --text1, --bg).
OR = "#f2662d"
TERRE = "#c94e1f"
ENCRE = "#2b211b"
CREME = "#f8f1e1"


def marque(taille: int = 40, couleur: str = OR, fond: str = "none") -> str:
    """Le disque coupé, sans le nom.

    Réservé aux petites tailles — favicon, icône d'application, barre de
    navigation — où le nom ne serait de toute façon pas lisible. La forme
    seule reste reconnaissable à 16 pixels, ce qu'un texte ne fait pas.
    """
    fond_rect = (f'<rect width="100" height="100" rx="22" fill="{fond}"/>'
                 if fond != "none" else "")
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{taille}" '
        f'height="{taille}" viewBox="0 0 100 100" role="img" '
        f'aria-label="Maroc Entrepreneuriat">{fond_rect}'
        # Demi-disque haut, puis demi-disque bas: la fente entre les deux
        # fait 10 unités, proportion tenue à toutes les tailles.
        f'<path d="M 12.33 45 A 38 38 0 0 1 87.67 45 Z" fill="{couleur}"/>'
        f'<path d="M 12.33 55 A 38 38 0 0 0 87.67 55 Z" fill="{couleur}"/>'
        f'</svg>'
    )


def logo(largeur: int = 280, couleur: str = OR,
         couleur_texte: str = ENCRE, fond: str = "none") -> str:
    """Le logo complet: disque coupé et nom dans la fente.

    Pour les en-têtes de documents, les emails et le pied de page, où la
    largeur disponible permet de lire le nom.

    Le cadre est plus large que le disque parce que le nom l'est aussi: à
    vingt-deux lettres espacées, il déborde de part et d'autre, et c'est ce
    débordement qui fait tenir la composition. Un premier essai calé sur la
    seule largeur du disque coupait le M et le T.
    """
    hauteur = round(largeur * 320 / 420)
    fond_rect = (f'<rect width="420" height="320" fill="{fond}"/>'
                 if fond != "none" else "")
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{largeur}" '
        f'height="{hauteur}" viewBox="0 0 420 320" role="img" '
        f'aria-label="Maroc Entrepreneuriat">{fond_rect}'
        # Disque de rayon 150 centré en (210,160), coupé par une fente de 40.
        # Les extrémités des arcs sont posées sur le cercle: à 20 du centre,
        # la demi-corde vaut racine(150² - 20²) = 148,66.
        f'<path d="M 61.34 140 A 150 150 0 0 1 358.66 140 Z" fill="{couleur}"/>'
        f'<path d="M 61.34 180 A 150 150 0 0 0 358.66 180 Z" fill="{couleur}"/>'
        f'<text x="210" y="160" text-anchor="middle" dominant-baseline="central" '
        f'font-family="Georgia, Times New Roman, serif" font-size="18" '
        f'font-weight="600" letter-spacing="3" fill="{couleur_texte}">'
        f'MAROC ENTREPRENEURIAT</text>'
        f'</svg>'
    )


def favicon_data_uri() -> str:
    """La marque encodée pour l'attribut href d'une balise <link>."""
    import urllib.parse
    svg = marque(32, couleur=OR, fond=ENCRE)
    return "data:image/svg+xml," + urllib.parse.quote(svg, safe="")


def logo_email(largeur: int = 210) -> str:
    """En-tête d'email.

    Les clients de messagerie ne savent pas tous afficher un SVG inséré dans
    le corps d'un message: Gmail le supprime purement et simplement, et une
    image distante est bloquée par défaut. Le logo y est donc reconstitué en
    HTML et en CSS, que tous interprètent.

    Le nom est posé sur sa propre ligne pleine largeur, centrée: logé dans
    la colonne étroite du disque, il débordait vers la droite et décalait
    toute la composition.
    """
    d = largeur // 2
    return (
        f'<div style="text-align:center;padding:2px 0 16px">'
        f'<div style="width:{d}px;height:{d // 2}px;background:{OR};'
        f'border-radius:{d}px {d}px 0 0;margin:0 auto"></div>'
        f'<div style="font-family:Georgia,serif;font-size:12px;font-weight:600;'
        f'letter-spacing:2px;color:{ENCRE};padding:6px 0;white-space:nowrap">'
        f'MAROC ENTREPRENEURIAT</div>'
        f'<div style="width:{d}px;height:{d // 2}px;background:{OR};'
        f'border-radius:0 0 {d}px {d}px;margin:0 auto"></div>'
        f'</div>'
    )


def logo_email_sombre(largeur: int = 160) -> str:
    """En-tête d'email.

    Les clients de messagerie ne savent pas tous afficher un SVG inséré dans
    le corps d'un message: Gmail le supprime purement et simplement, et une
    image distante est bloquée par défaut. Le logo y est donc reconstitué en
    HTML et en CSS, que tous interprètent.

    Le nom est posé sur sa propre ligne pleine largeur, centrée: logé dans
    la colonne étroite du disque, il débordait vers la droite et décalait
    toute la composition.
    """
    d = largeur // 2
    return (
        f'<div style="text-align:center;padding:2px 0 16px">'
        f'<div style="width:{d}px;height:{d // 2}px;background:{OR};'
        f'border-radius:{d}px {d}px 0 0;margin:0 auto"></div>'
        f'<div style="font-family:Georgia,serif;font-size:10px;font-weight:600;'
        f'letter-spacing:1.6px;color:{CREME};padding:6px 0;white-space:nowrap">'
        f'MAROC ENTREPRENEURIAT</div>'
        f'<div style="width:{d}px;height:{d // 2}px;background:{OR};'
        f'border-radius:0 0 {d}px {d}px;margin:0 auto"></div>'
        f'</div>'
    )

def entete_document(hauteur: int = 54) -> str:
    """En-tête de papier à lettre: la marque à gauche, le nom à côté.

    Le logo empilé — disque coupé, nom dans la fente — demande de la largeur
    pour rester lisible: réduit à la hauteur d'un en-tête, son nom devient
    illisible. Un document imprimé et remis à une administration ne peut pas
    se permettre ça, d'où cette disposition horizontale où le nom est composé
    à sa taille propre.
    """
    d = hauteur
    return (
        f'<div style="display:flex;align-items:center;gap:{max(10, d // 4)}px">'
        f'{marque(d, couleur=OR)}'
        f'<div style="line-height:1.25">'
        f'<div style="font-family:Georgia,Times New Roman,serif;font-weight:700;'
        f'font-size:{round(d * 0.31)}px;letter-spacing:{d * 0.028:.1f}px;'
        f'color:{ENCRE};white-space:nowrap">MAROC ENTREPRENEURIAT</div>'
        f'<div style="font-family:Arial,Helvetica,sans-serif;'
        f'font-size:{round(d * 0.17)}px;letter-spacing:{d * 0.02:.1f}px;'
        f'color:#6b7280;text-transform:uppercase">'
        f'Veille des marchés publics et privés</div>'
        f'</div></div>'
    )
