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
PAGE = """<html><body><script>var x="de:ad:be:ef:00:00";</script>
<table>
  <tr><th>Module</th><th>Adresse MAC</th></tr>
  <tr><td>Control switch eth0</td><td>00:11:22:33:44:55</td></tr>
  <tr><td>MSA0</td><td>AA-BB-CC-DD-EE-01</td></tr>
  <tr><td>MSA1</td><td>aa:bb:cc:dd:ee:02</td></tr>
  <tr><td>Diffusion</td><td>ff:ff:ff:ff:ff:ff</td></tr>
  <tr><td>Vide</td><td>00:00:00:00:00:00</td></tr>
  <tr><td>Doublon</td><td>00:11:22:33:44:55</td></tr>
</table></body></html>"""


def test_extraction_des_adresses_avec_leur_intitule():
    assert extraire_macs(PAGE) == [
        {"interface": "Control switch eth0", "mac": "00:11:22:33:44:55"},
        {"interface": "MSA0", "mac": "aa:bb:cc:dd:ee:01"},
        {"interface": "MSA1", "mac": "aa:bb:cc:dd:ee:02"},
    ]


def test_les_adresses_de_diffusion_et_nulles_sont_ecartees():
    macs = [entree["mac"] for entree in extraire_macs(PAGE)]
    assert "ff:ff:ff:ff:ff:ff" not in macs
    assert "00:00:00:00:00:00" not in macs


def test_le_contenu_des_scripts_est_ignore():
    macs = [entree["mac"] for entree in extraire_macs(PAGE)]
    assert "de:ad:be:ef:00:00" not in macs


def test_les_doublons_sont_ecartes():
    macs = [entree["mac"] for entree in extraire_macs(PAGE)]
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
@pytest.mark.parametrize(
    "saisie,attendu",
    [
        ("", "http://192.168.0.186/"),
        ("/status.html", "http://192.168.0.186/status.html"),
        ("192.168.0.186/infos", "http://192.168.0.186/infos"),
        ("http://autre.local/x", "http://autre.local/x"),
        ("https://192.168.0.186/", "https://192.168.0.186/"),
    ],
)
def test_completion_de_l_url(saisie, attendu):
    assert normaliser_url(saisie, "192.168.0.186") == attendu
