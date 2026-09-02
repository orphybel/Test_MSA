"""Emplacement des fichiers produits et ouverture dans l'explorateur."""

import os
import subprocess
import sys
import tempfile


def _est_inscriptible(dossier):
    """Verifie qu'on peut reellement ecrire dans ce dossier."""
    try:
        os.makedirs(dossier, exist_ok=True)
        temoin = os.path.join(dossier, ".ecriture_test")
        with open(temoin, "w"):
            pass
        os.remove(temoin)
        return True
    except OSError:
        return False


def racine_application():
    """Dossier ou sont ecrits les rapports.

    A cote de l'executable en priorite, ce qui est le plus simple pour
    l'operateur. Un executable place dans un dossier protege (Program Files,
    partage reseau en lecture seule) rendrait cette ecriture impossible : on
    se rabat alors sur les Documents de l'utilisateur, puis sur son dossier
    personnel.
    """
    candidats = []
    if getattr(sys, "frozen", False):
        candidats.append(os.path.dirname(sys.executable))
    else:
        candidats.append(os.getcwd())
    foyer = os.path.expanduser("~")
    candidats.append(os.path.join(foyer, "Documents", "TestMSA"))
    candidats.append(os.path.join(foyer, "TestMSA"))

    for candidat in candidats:
        if candidat and _est_inscriptible(candidat):
            return candidat
    return tempfile.gettempdir()


def ouvrir_dans_l_explorateur(chemin):
    """Ouvre un fichier ou un dossier avec l'application par defaut.

    `webbrowser` ne sait pas ouvrir un .txt de facon fiable sous Windows :
    on passe par os.startfile, puis par les commandes systeme habituelles.
    """
    chemin = os.path.abspath(chemin)
    if hasattr(os, "startfile"):  # Windows
        os.startfile(chemin)  # noqa: S606
        return
    commande = "open" if sys.platform == "darwin" else "xdg-open"
    subprocess.Popen([commande, chemin])
