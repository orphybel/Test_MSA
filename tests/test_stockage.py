"""Relevé de la capacité de stockage (GET :8080/storage/status)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from msa_test.rapport import exporter_stockage
from msa_test.stockage import (
    CAPACITE_MINIMALE,
    ErreurStockage,
    LOGIN_REST,
    MOT_DE_PASSE_REST,
    analyser_reponse,
    formater_capacite,
    url_stockage,
    verdict,
)


# ---------------------------------------------------------------------- #
# Requete
# ---------------------------------------------------------------------- #
def test_url_conforme_a_la_procedure():
    assert url_stockage("192.168.0.187") == "http://192.168.0.187:8080/storage/status"


def test_port_modifiable():
    assert url_stockage("192.168.0.187", 8081).startswith("http://192.168.0.187:8081/")


# ---------------------------------------------------------------------- #
# Lecture de la reponse
# ---------------------------------------------------------------------- #
REPONSE = (
    '{"capacity": 3755205, "hdd_status_entries": ['
    '{"index": 0, "device": "/dev/sda1", "state": "OK"},'
    '{"index": 1, "device": "/dev/sdb1", "state": "OK"}]}'
)


def test_lecture_de_la_capacite():
    releve = analyser_reponse(REPONSE)
    assert releve["capacite_ko"] == 3755205
    assert len(releve["entrees"]) == 2


def test_capacite_imbriquee():
    """La capacite est retrouvee meme si elle n'est pas au premier niveau."""
    assert analyser_reponse('{"storage": {"capacity": 42}}')["capacite_ko"] == 42


def test_reponse_sans_entrees_disque():
    assert analyser_reponse('{"capacity": 100}')["entrees"] == []


def test_reponse_non_json():
    with pytest.raises(ErreurStockage):
        analyser_reponse("<html>erreur</html>")


def test_reponse_sans_capacite():
    with pytest.raises(ErreurStockage):
        analyser_reponse('{"hdd_status_entries": []}')


def test_mise_en_forme_de_la_capacite():
    """L'exemple de la procedure : Capacity = 3 755 205."""
    texte = formater_capacite(3755205)
    assert texte.startswith("3 755 205 Ko")
    assert "Mo" in texte and "Go" in texte


# ---------------------------------------------------------------------- #
# Sanction
# ---------------------------------------------------------------------- #
def test_seuil_par_defaut():
    """Le seuil d'acceptation est de 3 700 000 Ko."""
    assert CAPACITE_MINIMALE == 3700000
    assert verdict(3755205)[1] is True
    assert verdict(3699999)[1] is False


def test_capacite_exactement_au_seuil_acceptee():
    """La regle est "capacite >= 3 700 000 Ko"."""
    assert verdict(3700000)[1] is True


def test_capacite_suffisante():
    sanction, conforme = verdict(3755205, 3700000)
    assert conforme is True and "SUFFISANTE" in sanction


def test_capacite_insuffisante():
    sanction, conforme = verdict(1900000, 3700000)
    assert conforme is False and "INSUFFISANTE" in sanction


def test_identifiants_rest_par_defaut():
    assert (LOGIN_REST, MOT_DE_PASSE_REST) == ("rest", "rest1234")


def test_sans_minimum_aucune_sanction():
    """La procedure ne fixe pas de valeur : l'operateur tranche."""
    sanction, conforme = verdict(3755205, None)
    assert conforme is None
    assert "relevé" in sanction


def test_capacite_absente():
    assert verdict(None, 3700000)[1] is False


# ---------------------------------------------------------------------- #
# Fichier produit
# ---------------------------------------------------------------------- #
def _campagne(**extra):
    campagne = {
        "type": "stockage",
        "date": "2026-08-21T09:00:00",
        "operateur": "J. DURAND",
        "serie_nvr": "NVR-2026-017",
        "nombre_msa": 2,
        "capacite_minimale_ko": 3700000,
        "modules": [
            {
                "msa": 0,
                "ip": "192.168.0.187",
                "capacite_ko": 3755205,
                "entrees": [{"index": 0, "device": "/dev/sda1", "state": "OK"}],
                "sanction": "SUFFISANTE (minimum 3 700 000 Ko)",
                "conforme": True,
                "erreur": None,
            },
            {
                "msa": 1,
                "ip": "192.168.0.188",
                "capacite_ko": 3699999,
                "entrees": [],
                "sanction": "INSUFFISANTE (minimum 3 700 000 Ko)",
                "conforme": False,
                "erreur": None,
            },
        ],
    }
    campagne.update(extra)
    return campagne


def test_le_fichier_reprend_chaque_module(tmp_path):
    chemin, anomalies = exporter_stockage(_campagne(), str(tmp_path))
    contenu = open(chemin, encoding="utf-8").read()
    assert anomalies == 1
    assert "NVR-2026-017" in os.path.basename(chemin)
    assert "MSA0" in contenu and "3 755 205 Ko" in contenu
    assert "MSA1" in contenu and "INSUFFISANTE" in contenu
    assert "/dev/sda1" in contenu  # detail des entrées disque
    assert "1 module(s) non conforme(s)" in contenu


def test_sans_minimum_le_fichier_le_signale(tmp_path):
    campagne = _campagne(capacite_minimale_ko=None)
    for module in campagne["modules"]:
        module["conforme"] = None
        module["sanction"] = "relevé - a comparer au minimum attendu"
    chemin, anomalies = exporter_stockage(campagne, str(tmp_path))
    contenu = open(chemin, encoding="utf-8").read()
    assert anomalies == 0
    assert "non renseignée" in contenu
    assert "a reporter sur la Fiche de Test" in contenu


# ---------------------------------------------------------------------- #
# Schema d'authentification annonce par le module
# ---------------------------------------------------------------------- #
class _Reponse:
    def __init__(self, entete=None):
        self.headers = {"WWW-Authenticate": entete} if entete else {}


@pytest.mark.parametrize(
    "entete,attendu",
    [
        ('Basic realm="REST"', {"basic"}),
        ('Digest realm="NVR", qop="auth", nonce="abc"', {"digest"}),
        ('Basic realm="a", Digest realm="b"', {"basic", "digest"}),
        (None, set()),
    ],
)
def test_lecture_du_schema_annonce(entete, attendu):
    """Basic et Digest affichent la meme fenetre dans le navigateur."""
    from msa_test.stockage import schemas_annonces

    assert schemas_annonces(_Reponse(entete)) == attendu
