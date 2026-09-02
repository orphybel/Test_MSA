"""Relevé des adresses MAC via l'interface web du NVR."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from msa_test.web_mac import (
    ErreurWeb,
    donnees_de_connexion,
    extraire_macs,
    formulaire_de_connexion,
    normaliser_mac,
    normaliser_url,
)


# ---------------------------------------------------------------------- #
# Normalisation des adresses
# ---------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "brut,attendu",
    [
        ("00:11:22:33:44:55", "00:11:22:33:44:55"),
        ("00-11-22-33-44-55", "00:11:22:33:44:55"),
        ("0011.2233.4455", "00:11:22:33:44:55"),
        ("AA:BB:CC:DD:EE:FF", "aa:bb:cc:dd:ee:ff"),
        ("00:11:22:33:44", None),  # trop court
        ("pas une adresse", None),
    ],
)
def test_normalisation_des_adresses(brut, attendu):
    assert normaliser_mac(brut) == attendu


# ---------------------------------------------------------------------- #
# Extraction depuis la page
# ---------------------------------------------------------------------- #
# Reconstitution de la page "Administration : Versions" du NVR : un intitule
# de section dans un tableau d'une cellule, puis le tableau des modules.
PAGE = """<html><body><script>var x="de:ad:be:ef:00:00";</script>
<table><tr><td>NVR</td></tr></table>
<table>
  <tr><th>Param&egrave;tre</th><th>Version logicielle</th><th>Checksum</th>
      <th>Adresse MAC</th><th>Etat mise &agrave; jour</th></tr>
  <tr><td>Module Contr&ocirc;le Switch</td><td>11</td>
      <td>0ff573d73d3c3f3e060dbfb83141e036</td><td>00:10:02:0F:D7:D7</td><td></td></tr>
  <tr><td>Module CPU Enregistreur 0</td><td>0.28</td>
      <td>efa1fecec398587d39f7363f43559a1a</td><td>00:E0:4B:7B:E8:0A</td><td></td></tr>
  <tr><td>Module CPU Enregistreur 1</td><td>0.28</td>
      <td>efa1fecec398587d39f7363f43559a1a</td><td>00-E0-4B-7B-E8-3B</td><td></td></tr>
  <tr><td>Diffusion</td><td>?</td><td>?</td><td>ff:ff:ff:ff:ff:ff</td><td></td></tr>
  <tr><td>Vide</td><td>?</td><td>?</td><td>00:00:00:00:00:00</td><td></td></tr>
</table>
<table><tr><td>Cam&eacute;ras int&eacute;rieures</td></tr></table>
<table>
  <tr><th>Param&egrave;tre</th><th>Version logicielle</th><th>Adresse MAC</th></tr>
  <tr><td>CamInt1_S1</td><td>1.3.0</td><td>00:90:E8:9E:94:CD</td></tr>
  <tr><td>CamInt2_S1</td><td>?</td><td>?</td></tr>
  <tr><td>CamInt1_N11</td><td>1.3.0</td><td>00:90:E8:9E:94:CD</td></tr>
</table></body></html>"""


def test_extraction_depuis_la_colonne_adresse_mac():
    assert extraire_macs(PAGE) == [
        {"interface": "NVR - Module Contrôle Switch", "mac": "00:10:02:0f:d7:d7"},
        {"interface": "NVR - Module CPU Enregistreur 0", "mac": "00:e0:4b:7b:e8:0a"},
        {"interface": "NVR - Module CPU Enregistreur 1", "mac": "00:e0:4b:7b:e8:3b"},
        {"interface": "Caméras intérieures - CamInt1_S1", "mac": "00:90:e8:9e:94:cd"},
        {"interface": "Caméras intérieures - CamInt1_N11", "mac": "00:90:e8:9e:94:cd"},
    ]


def test_le_checksum_n_est_pas_pris_pour_une_adresse():
    """Le checksum est une longue chaine hexadecimale sur la meme ligne."""
    macs = [entree["mac"] for entree in extraire_macs(PAGE)]
    assert all(len(mac) == 17 for mac in macs)
    assert not any("efa1fecec" in entree["interface"] for entree in extraire_macs(PAGE))


def test_les_cellules_sans_adresse_sont_ignorees():
    """Les modules absents affichent "?" dans la colonne."""
    intitules = [entree["interface"] for entree in extraire_macs(PAGE)]
    assert not any("CamInt2_S1" in intitule for intitule in intitules)


def test_les_adresses_de_diffusion_et_nulles_sont_ecartees():
    macs = [entree["mac"] for entree in extraire_macs(PAGE)]
    assert "ff:ff:ff:ff:ff:ff" not in macs
    assert "00:00:00:00:00:00" not in macs


def test_le_contenu_des_scripts_est_ignore():
    macs = [entree["mac"] for entree in extraire_macs(PAGE)]
    assert "de:ad:be:ef:00:00" not in macs


def test_deux_modules_partageant_une_adresse_restent_distincts():
    """Les cameras affichent la meme adresse : aucune ligne ne doit disparaitre."""
    intitules = [entree["interface"] for entree in extraire_macs(PAGE)]
    assert "Caméras intérieures - CamInt1_S1" in intitules
    assert "Caméras intérieures - CamInt1_N11" in intitules


# ---------------------------------------------------------------------- #
# Repli : page sans colonne "Adresse MAC"
# ---------------------------------------------------------------------- #
PAGE_SANS_TABLEAU = """<html><body>
<p>Port 1 : 00:11:22:33:44:55</p>
<p>Port 2 : 00:11:22:33:44:66</p>
<p>Rappel : 00:11:22:33:44:55</p>
</body></html>"""


def test_repli_sur_les_lignes_de_texte():
    assert extraire_macs(PAGE_SANS_TABLEAU) == [
        {"interface": "Port 1", "mac": "00:11:22:33:44:55"},
        {"interface": "Port 2", "mac": "00:11:22:33:44:66"},
    ]


def test_les_doublons_sont_ecartes_en_mode_texte():
    macs = [entree["mac"] for entree in extraire_macs(PAGE_SANS_TABLEAU)]
    assert len(macs) == len(set(macs))


def test_page_sans_adresse():
    assert extraire_macs("<html><body>Aucune donnée</body></html>") == []


# ---------------------------------------------------------------------- #
# Formulaire de connexion
# ---------------------------------------------------------------------- #
FORMULAIRE = """<html><body>
<form method="post" action="/login">
  <input type="hidden" name="csrf" value="jeton123">
  <input type="text" name="utilisateur">
  <input type="password" name="motdepasse">
  <input type="submit" name="ok" value="Valider">
</form></body></html>"""


def test_detection_du_formulaire_de_connexion():
    formulaire = formulaire_de_connexion(FORMULAIRE)
    assert formulaire is not None
    assert formulaire["action"] == "/login"
    assert formulaire["methode"] == "post"


def test_une_page_sans_champ_mot_de_passe_n_est_pas_un_formulaire_de_connexion():
    assert formulaire_de_connexion(PAGE) is None


def test_les_champs_caches_sont_conserves():
    donnees = donnees_de_connexion(
        formulaire_de_connexion(FORMULAIRE), "admin", "secret"
    )
    assert donnees["utilisateur"] == "admin"
    assert donnees["motdepasse"] == "secret"
    assert donnees["csrf"] == "jeton123"  # jeton anti-rejeu preserve


def test_formulaire_sans_champ_identifiant():
    sans_identifiant = (
        '<form method="post"><input type="password" name="pw"></form>'
    )
    with pytest.raises(ErreurWeb):
        donnees_de_connexion(
            formulaire_de_connexion(sans_identifiant), "admin", "secret"
        )


# ---------------------------------------------------------------------- #
# URL
# ---------------------------------------------------------------------- #
VERSIONS = "/cgi-bin/cgi_fh?URL=SUAdminVersions"


@pytest.mark.parametrize(
    "saisie,attendu",
    [
        # rien de saisi : page des versions de la carte Controle/Switch
        ("", "http://192.168.0.196" + VERSIONS),
        # la seule adresse suffit, le chemin est complete
        ("192.168.0.196", "http://192.168.0.196" + VERSIONS),
        ("http://192.168.0.196", "http://192.168.0.196" + VERSIONS),
        ("http://192.168.0.196/", "http://192.168.0.196" + VERSIONS),
        # un chemin explicite est respecte
        ("/status.html", "http://192.168.0.196/status.html"),
        ("192.168.0.196/infos", "http://192.168.0.196/infos"),
        ("http://autre.local/x", "http://autre.local/x"),
        ("http://192.168.0.196" + VERSIONS, "http://192.168.0.196" + VERSIONS),
    ],
)
def test_completion_de_l_url(saisie, attendu):
    assert normaliser_url(saisie, "192.168.0.196") == attendu
