# -*- coding: utf-8 -*-
"""Identité visuelle: un seul endroit d'où sort la marque.

Le signe est le khatim — l'étoile à huit branches née de deux carrés
superposés dont l'un pivote d'un quart de tour. C'est le motif géométrique
le plus répandu du zellige marocain: il se lit comme marocain sans qu'on ait
à l'expliquer, et il dit ce que fait la plateforme, une étoile servant à
s'orienter.

Sa géométrie est exacte, pas approchée: pour un carré de rayon R (centre
vers coin), les creux tombent à R·cos(45°)/cos(22,5°), soit 0,7654 R. Posé
au jugé, ce rapport transforme l'étoile en fleur ou en roue dentée.

Le centre est ajouré d'un carré tourné, en découpe réelle — règle de
remplissage evenodd — et non peint en blanc: le fond traverse, si bien que
la marque tient aussi bien sur la crème du site que sur le brun d'un en-tête
ou le blanc d'un document imprimé.

Format SVG: le trait reste net du favicon de seize pixels à l'en-tête
imprimé en A4, le fichier pèse quelques centaines d'octets et s'insère sans
requête supplémentaire. Les emails font exception, traités plus bas.
"""
import math

# Couleurs de la plateforme (variables CSS --gold, --terra, --text1, --bg).
OR = "#f2662d"
TERRE = "#c94e1f"
ENCRE = "#2b211b"
CREME = "#f8f1e1"

# Rapport du creux à la pointe: ce nombre fait le khatim.
_CREUX = math.cos(math.radians(45)) / math.cos(math.radians(22.5))


def _sommets(rayon: float, centre: float = 50.0) -> str:
    """Les seize sommets de l'étoile, pointe en haut, en commandes SVG."""
    parties = []
    for i in range(16):
        angle = math.radians(i * 22.5 - 90)
        r = rayon if i % 2 == 0 else rayon * _CREUX
        x = centre + r * math.cos(angle)
        y = centre + r * math.sin(angle)
        parties.append(f"{'M' if i == 0 else 'L'} {x:.2f} {y:.2f}")
    return " ".join(parties) + " Z"


def etoile(taille: int = 40, couleur: str = OR, fond: str = "none") -> str:
    """La marque seule.

    Pour le favicon, l'icône de l'application et la barre de navigation. Le
    carré ajouré est dimensionné pour laisser une couronne régulière: plus
    grand il romprait les branches, plus petit il deviendrait une tache et
    se refermerait sous vingt pixels.
    """
    fond_rect = (f'<rect width="100" height="100" rx="22" fill="{fond}"/>'
                 if fond != "none" else "")
    # Sous vingt pixels, l'ajour se referme en une bouillie de deux ou trois
    # pixels: l'etoile pleine y est plus nette et reste reconnaissable.
    ajour = "" if taille < 20 else " M 50 30 L 70 50 L 50 70 L 30 50 Z"
    return (
        # flex:none et la largeur minimale protegent la marque: dans une barre
        # de navigation chargee, la regle « svg { max-width: 100% } » la
        # laissait se reduire a rien pendant que le nom, en nowrap, tenait sa
        # place. Constate le 30/09/2026: l'etoile avait disparu de l'en-tete
        # tout en restant visible dans le pied de page, ou rien ne comprime.
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{taille}" '
        f'height="{taille}" viewBox="0 0 100 100" role="img" '
        f'style="flex:none;min-width:{taille}px" '
        f'aria-label="Maroc Entrepreneuriat">{fond_rect}'
        f'<path fill-rule="evenodd" fill="{couleur}" '
        f'd="{_sommets(48)}{ajour}"/>'
        f'</svg>'
    )


def _mot(taille: float, espace: float, couleur: str, texte: str) -> str:
    return (f'<div style="font-family:Georgia,Times New Roman,serif;'
            f'font-weight:700;font-size:{taille:.1f}px;'
            f'letter-spacing:{espace:.2f}px;color:{couleur};'
            f'line-height:1.16;white-space:nowrap">{texte}</div>')


def logo(hauteur: int = 44, couleur: str = OR, couleur_texte: str = ENCRE,
         baseline: bool = False) -> str:
    """Marque et nom côte à côte.

    Le nom tient sur deux lignes — MAROC au-dessus, ENTREPRENEURIAT en
    dessous. Sur une seule, vingt-deux lettres imposent soit une largeur
    que la barre de navigation n'a pas, soit un corps qui ne se lit plus.
    Empilé, le nom occupe la hauteur de l'étoile et la composition tient.

    L'interlettrage de MAROC est calculé pour que les deux lignes finissent
    à la même largeur: cinq lettres au-dessus de quinze, alignées à gauche
    et à droite, c'est ce qui fait tenir le bloc.
    """
    ligne = (f'<div style="font-family:Arial,Helvetica,sans-serif;'
             f'font-size:{hauteur * 0.16:.1f}px;'
             f'letter-spacing:{hauteur * 0.018:.2f}px;color:#8a7a6a;'
             f'text-transform:uppercase;margin-top:4px;white-space:nowrap">'
             f'Veille des marchés publics, semi-publics et privés</div>'
             if baseline else "")
    return (
        f'<span style="display:inline-flex;align-items:center;'
        f'gap:{max(9, round(hauteur * 0.25))}px;vertical-align:middle">'
        f'{etoile(hauteur, couleur)}'
        # Classe nommee: la barre de navigation masque le nom sous 1400 px
        # pour rendre sa largeur aux liens, et ne garde que l'etoile.
        f'<span class="me-logo-nom" style="display:block">'
        f'{_mot(hauteur * 0.295, hauteur * 0.0755, couleur_texte, "MAROC")}'
        f'{_mot(hauteur * 0.295, hauteur * 0.0155, couleur_texte, "ENTREPRENEURIAT")}'
        f'{ligne}</span></span>'
    )


def entete_document(hauteur: int = 52) -> str:
    """En-tête des documents qu'un membre imprime et remet.

    Même composition, en plus grand et avec la ligne de description: la
    déclaration de sous-traitance part chez un maître d'ouvrage, elle doit
    dire d'où elle vient sans qu'on la cherche.
    """
    return logo(hauteur, baseline=True)


def favicon_data_uri() -> str:
    """La marque encodée pour l'attribut href d'une balise <link>."""
    import urllib.parse
    return "data:image/svg+xml," + urllib.parse.quote(
        etoile(32, couleur=OR, fond=ENCRE), safe="")


def _entete_email(couleur_texte: str, trait: str) -> str:
    """En-tête d'email, en typographie seule.

    Ni SVG ni image: Gmail supprime le premier et bloque la seconde par
    défaut. Reconstituer l'étoile en CSS demanderait clip-path, qu'aucun
    client de messagerie n'interprète. Le nom composé entre deux filets rend
    la même chose partout.
    """
    return (
        f'<div style="text-align:center;padding:2px 0 20px">'
        f'<div style="height:2px;width:44px;background:{trait};'
        f'margin:0 auto 13px"></div>'
        f'<div style="font-family:Georgia,Times New Roman,serif;font-weight:700;'
        f'font-size:17px;letter-spacing:6.4px;color:{couleur_texte};'
        f'white-space:nowrap">MAROC</div>'
        f'<div style="font-family:Georgia,Times New Roman,serif;font-weight:700;'
        f'font-size:17px;letter-spacing:1.1px;color:{couleur_texte};'
        f'white-space:nowrap">ENTREPRENEURIAT</div>'
        f'<div style="height:2px;width:44px;background:{trait};'
        f'margin:13px auto 0"></div>'
        f'</div>'
    )


def logo_email(largeur: int = 210) -> str:
    """Bandeau des emails posés sur fond clair."""
    return _entete_email(ENCRE, OR)


def logo_email_sombre(largeur: int = 160) -> str:
    """Bandeau des emails posés sur fond encre."""
    return _entete_email(CREME, OR)
