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
