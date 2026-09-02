"""Choix du dossier ou sont ecrits les fichiers produits."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from msa_test import chemins


def test_le_dossier_courant_est_retenu_s_il_est_inscriptible(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    assert chemins.racine_application() == str(tmp_path)


def test_repli_sur_les_documents_si_le_dossier_est_protege(tmp_path, monkeypatch):
    """Un executable place dans Program Files ne peut pas y ecrire."""
    protege = tmp_path / "protege"
    foyer = tmp_path / "foyer"
    foyer.mkdir()

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(protege / "TestMSA.exe"), raising=False)
    monkeypatch.setattr(os.path, "expanduser", lambda _: str(foyer))
    monkeypatch.setattr(
        chemins, "_est_inscriptible", lambda d: not d.startswith(str(protege))
    )

    assert chemins.racine_application() == os.path.join(str(foyer), "Documents", "TestMSA")


def test_dernier_repli_sur_le_dossier_temporaire(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.setattr(chemins, "_est_inscriptible", lambda d: False)
    racine = chemins.racine_application()
    assert racine and os.path.isdir(racine)


def test_detection_d_un_dossier_inscriptible(tmp_path):
    assert chemins._est_inscriptible(str(tmp_path)) is True
    assert chemins._est_inscriptible("/proc/interdit/impossible") is False
