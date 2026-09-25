"""Sauvegarde, relecture et migration des relevés."""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from msa_test.rapport import charger


def test_les_anciens_releves_sont_migres(tmp_path):
    """Les relevés produits avant le renommage utilisaient la cle "cpu"."""
    ancien = {
        "phase": "avant",
        "modules": [{"cpu": 0, "ip": "192.168.0.187", "partitions": {}}],
    }
    chemin = tmp_path / "campagne_avant_ancienne.json"
    chemin.write_text(json.dumps(ancien), encoding="utf-8")

    campagne = charger(str(chemin))
    assert campagne["modules"][0]["msa"] == 0
    assert "cpu" not in campagne["modules"][0]


def test_un_releve_recent_est_inchange(tmp_path):
    recent = {"phase": "avant", "modules": [{"msa": 2, "ip": "1.2.3.4", "partitions": {}}]}
    chemin = tmp_path / "campagne_avant_recente.json"
    chemin.write_text(json.dumps(recent), encoding="utf-8")

    assert charger(str(chemin))["modules"][0]["msa"] == 2


import pytest

from msa_test.rapport import (
    exporter_comparaisons,
    exporter_csv,
    fragment_nom,
    sauvegarder,
)
from msa_test.rapport_html import exporter_html


@pytest.mark.parametrize(
    "serie,attendu",
    [
        ("NVR-2026-017", "_NVR-2026-017"),
        ("NVR 2026/017", "_NVR_2026_017"),  # espaces et separateurs neutralises
        ('bad:*?"<>|name', "_bad_name"),  # caracteres refuses par Windows
        ("", ""),
        (None, ""),
        ("...", ""),  # un nom vide apres nettoyage n'ajoute rien
        ("X" * 60, "_" + "X" * 40),  # borne a 40 caracteres
    ],
)
def test_fragment_de_nom_de_fichier(serie, attendu):
    assert fragment_nom(serie) == attendu


def _campagne(phase="avant", serie="NVR-2026-017"):
    return {
        "phase": phase,
        "libelle_phase": "Avant enregistrement (etapes 12 a 15)",
        "date": "2026-08-21T09:00:00",
        "operateur": "J. DURAND",
        "serie_nvr": serie,
        "ip_switch": "192.168.0.186",
        "nombre_msa": 1,
        "modules": [
            {
                "msa": 0,
                "ip": "192.168.0.187",
                "erreur": None,
                "partitions": {
                    "/dev/sda1": {
                        "command_timeout": "0",
                        "udma_crc_error_count": "0",
                        "ligne_188": "188 Command_Timeout 0x0032 100 100 000 Old_age Always - 0",
                        "ligne_199": "199 UDMA_CRC_Error_Count 0x003e 200 200 000 Old_age Always - 0",
                        "manquants": [],
                    },
                    "/dev/sdb1": {
                        "command_timeout": "0",
                        "udma_crc_error_count": "0",
                        "ligne_188": "188 Command_Timeout 0x0032 100 100 000 Old_age Always - 0",
                        "ligne_199": "199 UDMA_CRC_Error_Count 0x003e 200 200 000 Old_age Always - 0",
                        "manquants": [],
                    },
                },
            }
        ],
    }


def test_le_numero_de_serie_apparait_dans_les_noms_de_fichiers(tmp_path):
    avant = _campagne()
    apres = _campagne(phase="apres")
    racine = str(tmp_path)

    noms = [
        os.path.basename(sauvegarder(avant, racine)),
        os.path.basename(exporter_csv(avant, racine)),
        os.path.basename(exporter_html(avant, None, racine)),
        os.path.basename(exporter_html(avant, apres, racine)),
    ]
    assert all("NVR-2026-017" in nom for nom in noms), noms


def test_sans_numero_de_serie_les_noms_restent_valides(tmp_path):
    avant = _campagne(serie="")
    nom = os.path.basename(sauvegarder(avant, str(tmp_path)))
    assert nom.startswith("campagne_avant_2026-08-21")


def test_le_numero_de_serie_est_repris_dans_le_rapport_et_le_pv(tmp_path):
    avant = _campagne()
    apres = _campagne(phase="apres")
    html = open(exporter_html(avant, apres, str(tmp_path)), encoding="utf-8").read()
    assert "N° de série du NVR" in html and "NVR-2026-017" in html

    chemin, _ = exporter_comparaisons(apres, avant, {0: "0051200_0001"}, str(tmp_path))[0]
    assert "N° de serie NVR : NVR-2026-017" in open(chemin, encoding="utf-8").read()


# ---------------------------------------------------------------------- #
# Rapport de comparaison par MSA
# ---------------------------------------------------------------------- #
def _module(msa, sda_199, sdb_199, erreur=None):
    def partition(valeur_199):
        return {"command_timeout": "0", "udma_crc_error_count": valeur_199}

    return {
        "msa": msa,
        "ip": "192.168.0.%d" % (187 + msa),
        "erreur": erreur,
        "partitions": {}
        if erreur
        else {"/dev/sda1": partition(sda_199), "/dev/sdb1": partition(sdb_199)},
    }


def _campagnes():
    avant = _campagne()
    apres = _campagne(phase="apres")
    avant["modules"] = [_module(0, "0", "0"), _module(1, "0", "0"), _module(2, "0", "0")]
    apres["modules"] = [
        _module(0, "0", "0"),
        _module(1, "0", "5"),
        _module(2, None, None, erreur="SSH KO"),
    ]
    return avant, apres


def test_un_rapport_de_comparaison_par_msa(tmp_path):
    avant, apres = _campagnes()
    produits = exporter_comparaisons(
        apres, avant, {0: "0051200_0001", 1: "0051200_0002"}, str(tmp_path)
    )
    noms = [os.path.basename(chemin) for chemin, _ in produits]
    assert len(noms) == 3
    assert noms[0].startswith("comparaison_MSA0_0051200_0001_")
    assert noms[1].startswith("comparaison_MSA1_0051200_0002_")
    assert noms[2].startswith("comparaison_MSA2_2026")  # sans numero saisi
    assert all(nom.endswith(".txt") for nom in noms)


def test_chaque_rapport_ne_contient_que_son_msa(tmp_path):
    avant, apres = _campagnes()
    produits = exporter_comparaisons(apres, avant, {0: "N0", 1: "N1"}, str(tmp_path))
    contenu_msa0 = open(produits[0][0], encoding="utf-8").read()
    assert "N° du MSA       : N0" in contenu_msa0
    assert "192.168.0.187" in contenu_msa0
    assert "192.168.0.188" not in contenu_msa0
    assert contenu_msa0.count("/dev/sda1") == 1


def test_conclusion_propre_a_chaque_msa(tmp_path):
    avant, apres = _campagnes()
    produits = exporter_comparaisons(apres, avant, {}, str(tmp_path))
    conformes = [conforme for _, conforme in produits]
    assert conformes == [True, False, False]
    msa1 = open(produits[1][0], encoding="utf-8").read()
    assert "CONCLUSION MSA1 : NON CONFORME" in msa1
    assert "0 -> 5" in msa1
    msa2 = open(produits[2][0], encoding="utf-8").read()
    assert "NON TESTE" in msa2 and "SSH KO" in msa2


def test_les_alertes_sont_rattachees_au_bon_msa(tmp_path):
    avant, apres = _campagnes()
    avant["modules"][1] = _module(1, "0", "5")
    apres["modules"][1] = _module(1, "0", "5")  # non nul mais inchange
    produits = exporter_comparaisons(apres, avant, {}, str(tmp_path))
    msa0 = open(produits[0][0], encoding="utf-8").read()
    msa1 = open(produits[1][0], encoding="utf-8").read()
    assert "RAW_VALUE non nulles" not in msa0
    assert "RAW_VALUE non nulles" in msa1
    assert produits[1][1] is True
