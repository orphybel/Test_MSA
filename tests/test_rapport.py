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

from msa_test.rapport import exporter_csv, exporter_pv, fragment_nom, sauvegarder
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
        os.path.basename(exporter_pv(apres, avant, racine)[0]),
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

    pv = open(exporter_pv(apres, avant, str(tmp_path))[0], encoding="utf-8").read()
    assert "N° de serie NVR : NVR-2026-017" in pv
