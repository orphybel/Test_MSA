import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from msa_test.campagne import (
    alertes_avant_apres,
    alertes_valeurs_non_nulles,
    comparer,
    liste_ip,
)


def test_ip_incrementees_selon_la_figure_12():
    assert liste_ip("192.168.0.187", 6) == [
        "192.168.0.187",
        "192.168.0.188",
        "192.168.0.189",
        "192.168.0.190",
        "192.168.0.191",
        "192.168.0.192",
    ]


def test_premiere_ip_libre():
    assert liste_ip("10.1.2.250", 3) == ["10.1.2.250", "10.1.2.251", "10.1.2.252"]


@pytest.mark.parametrize("nombre", [0, 7, -1])
def test_nombre_de_msa_borne_a_six(nombre):
    with pytest.raises(ValueError):
        liste_ip("192.168.0.187", nombre)


def test_ip_invalide():
    with pytest.raises(ValueError):
        liste_ip("192.168.0", 1)


def _module(msa, sda, sdb, erreur=None):
    return {
        "msa": msa,
        "ip": "192.168.0.%d" % (187 + msa),
        "erreur": erreur,
        "partitions": {
            "/dev/sda1": {"command_timeout": sda[0], "udma_crc_error_count": sda[1]},
            "/dev/sdb1": {"command_timeout": sdb[0], "udma_crc_error_count": sdb[1]},
        },
    }


def test_comparaison_conforme():
    avant = {"modules": [_module(0, ("0", "0"), ("0", "0"))]}
    apres = {"modules": [_module(0, ("0", "0"), ("0", "0"))]}
    lignes, conforme = comparer(avant, apres)
    assert conforme is True
    assert all(l["verdict"].startswith("CONFORME") for l in lignes)


def test_comparaison_detecte_une_derive():
    avant = {"modules": [_module(0, ("0", "0"), ("0", "0"))]}
    apres = {"modules": [_module(0, ("0", "0"), ("0", "5"))]}
    lignes, conforme = comparer(avant, apres)
    assert conforme is False
    assert "ID#199" in lignes[1]["verdict"]


def test_module_en_erreur_non_conforme():
    avant = {"modules": [_module(0, ("0", "0"), ("0", "0"))]}
    apres = {"modules": [_module(0, ("0", "0"), ("0", "0"), erreur="SSH KO")]}
    lignes, conforme = comparer(avant, apres)
    assert conforme is False
    assert all("NON TESTE" in l["verdict"] for l in lignes)


def test_releve_avant_manquant():
    avant = {"modules": []}
    apres = {"modules": [_module(0, ("0", "0"), ("0", "0"))]}
    lignes, conforme = comparer(avant, apres)
    assert conforme is False
    assert all(l["verdict"] == "PAS DE RELEVE AVANT" for l in lignes)


def test_alertes_sur_les_valeurs_non_nulles():
    campagne = {"modules": [_module(0, ("0", "0"), ("0 0 0", "12"))]}
    alertes = alertes_valeurs_non_nulles(campagne)
    assert len(alertes) == 1
    assert alertes[0]["attribut_id"] == 199
    assert alertes[0]["partition"] == "/dev/sdb1"
    assert alertes[0]["valeur"] == "12"


def test_aucune_alerte_quand_tout_est_a_zero():
    campagne = {"modules": [_module(0, ("0", "0"), ("0 0 0", "0"))]}
    assert alertes_valeurs_non_nulles(campagne) == []


def test_une_valeur_non_nulle_reste_conforme_si_elle_n_a_pas_bouge():
    """La procedure (etape 24) ne sanctionne que l'evolution des valeurs."""
    avant = {"modules": [_module(0, ("0", "12"), ("0", "12"))]}
    apres = {"modules": [_module(0, ("0", "12"), ("0", "12"))]}
    _, conforme = comparer(avant, apres)
    assert conforme is True
    assert len(alertes_valeurs_non_nulles(apres)) == 2


def test_alertes_consolidees_sur_les_deux_phases():
    """Un module injoignable a l'etape 24 garde les alertes de son relevé avant."""
    avant = {"modules": [_module(0, ("0", "12"), ("0", "0"))]}
    apres = {"modules": [_module(0, ("0", "0"), ("0", "0"), erreur="SSH KO")]}
    alertes = alertes_avant_apres(avant, apres)
    assert len(alertes) == 1
    assert alertes[0]["valeur"] == "12"


def test_la_phase_apres_fait_foi_quand_elle_existe():
    avant = {"modules": [_module(0, ("0", "0"), ("0", "0"))]}
    apres = {"modules": [_module(0, ("0", "9"), ("0", "0"))]}
    alertes = alertes_avant_apres(avant, apres)
    assert [a["valeur"] for a in alertes] == ["9"]
