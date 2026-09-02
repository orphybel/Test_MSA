"""Relevé des adresses MAC : adressage, parcours des equipements et fichier."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from msa_test.campagne import equipements_mac, ip_carte_switch
from msa_test.rapport import exporter_macs
from msa_test.ssh_client import _parser_interfaces, _parser_ip_link


# ---------------------------------------------------------------------- #
# Adressage de la carte control switch
# ---------------------------------------------------------------------- #
def test_la_carte_switch_precede_le_premier_msa():
    assert ip_carte_switch("192.168.0.187") == "192.168.0.186"


def test_la_carte_switch_suit_la_premiere_ip_saisie():
    assert ip_carte_switch("10.20.30.100") == "10.20.30.99"


def test_le_changement_de_sous_reseau_est_respecte():
    assert ip_carte_switch("192.168.1.0") == "192.168.0.255"


def test_adresse_invalide_refusee():
    with pytest.raises(ValueError):
        ip_carte_switch("192.168.0")


def test_aucune_adresse_avant_la_premiere():
    with pytest.raises(ValueError):
        ip_carte_switch("0.0.0.0")


# ---------------------------------------------------------------------- #
# Equipements interrogés
# ---------------------------------------------------------------------- #
def _config(**extra):
    config = {
        "premiere_ip": "192.168.0.187",
        "nombre_msa": 3,
        "login": "operateur",
        "mot_de_passe": "motdepasse",
        "login_switch": "admin",
        "mot_de_passe_switch": "autre",
    }
    config.update(extra)
    return config


def test_la_carte_switch_est_interrogee_en_premier_avec_son_compte():
    equipements = equipements_mac(_config())
    assert [e["libelle"] for e in equipements] == [
        "Carte control switch",
        "MSA0",
        "MSA1",
        "MSA2",
    ]
    switch = equipements[0]
    assert switch["ip"] == "192.168.0.186"
    assert switch["login"] == "admin" and switch["mot_de_passe"] == "autre"
    assert all(e["login"] == "operateur" for e in equipements[1:])


@pytest.mark.parametrize("login_switch", ["", "   ", None])
def test_sans_identifiant_seuls_les_msa_sont_interroges(login_switch):
    equipements = equipements_mac(_config(login_switch=login_switch))
    assert [e["libelle"] for e in equipements] == ["MSA0", "MSA1", "MSA2"]


# ---------------------------------------------------------------------- #
# Lecture des interfaces
# ---------------------------------------------------------------------- #
def test_lecture_depuis_sys_class_net():
    sortie = "lo 00:00:00:00:00:00\neth0 00:11:22:33:44:55\neth1 AA:BB:CC:DD:EE:FF\n"
    assert _parser_interfaces(sortie) == [
        {"interface": "eth0", "mac": "00:11:22:33:44:55"},
        {"interface": "eth1", "mac": "aa:bb:cc:dd:ee:ff"},
    ]


def test_les_adresses_nulles_et_la_boucle_locale_sont_ecartees():
    sortie = "lo 00:00:00:00:00:00\ndummy0 00:00:00:00:00:00\nbidon pas-une-mac\n"
    assert _parser_interfaces(sortie) == []


def test_repli_sur_ip_link():
    sortie = (
        "1: lo: <LOOPBACK,UP> mtu 65536 state UNKNOWN "
        "link/loopback 00:00:00:00:00:00 brd 00:00:00:00:00:00\n"
        "2: eth0: <BROADCAST,UP> mtu 1500 state UP "
        "link/ether 00:11:22:33:44:55 brd ff:ff:ff:ff:ff:ff\n"
    )
    assert _parser_ip_link(sortie) == [
        {"interface": "eth0", "mac": "00:11:22:33:44:55"}
    ]


# ---------------------------------------------------------------------- #
# Fichier texte
# ---------------------------------------------------------------------- #
def _campagne(**extra):
    campagne = {
        "type": "mac",
        "date": "2026-08-21T09:00:00",
        "operateur": "J. DURAND",
        "serie_nvr": "NVR-2026-017",
        "nombre_msa": 1,
        "carte_switch_relevee": True,
        "equipements": [
            {
                "libelle": "Carte control switch",
                "ip": "192.168.0.186",
                "erreur": None,
                "interfaces": [{"interface": "eth0", "mac": "00:11:22:33:44:55"}],
            },
            {
                "libelle": "MSA0",
                "ip": "192.168.0.187",
                "erreur": None,
                "interfaces": [{"interface": "eth0", "mac": "aa:bb:cc:dd:ee:ff"}],
            },
        ],
    }
    campagne.update(extra)
    return campagne


def test_le_fichier_contient_chaque_equipement(tmp_path):
    chemin, echecs = exporter_macs(_campagne(), str(tmp_path))
    contenu = open(chemin, encoding="utf-8").read()
    assert echecs == 0
    assert "NVR-2026-017" in os.path.basename(chemin)
    assert "Carte control switch (192.168.0.186)" in contenu
    assert "00:11:22:33:44:55" in contenu
    assert "MSA0 (192.168.0.187)" in contenu
    assert "aa:bb:cc:dd:ee:ff" in contenu
    assert "Tous les equipements ont ete relevés." in contenu


def test_les_equipements_en_echec_sont_comptes(tmp_path):
    campagne = _campagne()
    campagne["equipements"][0].update(erreur="Authentification refusee", interfaces=[])
    chemin, echecs = exporter_macs(campagne, str(tmp_path))
    contenu = open(chemin, encoding="utf-8").read()
    assert echecs == 1
    assert "ECHEC : Authentification refusee" in contenu
    assert "1 equipement(s) n'ont pas pu etre relevés" in contenu


def test_la_carte_switch_non_relevee_est_signalee(tmp_path):
    campagne = _campagne(carte_switch_relevee=False)
    campagne["equipements"] = campagne["equipements"][1:]
    contenu = open(exporter_macs(campagne, str(tmp_path))[0], encoding="utf-8").read()
    assert "Carte control switch : non relevée" in contenu
