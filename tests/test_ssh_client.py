"""Regressions sur la detection du compte root et sur l'appel a smartctl."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from msa_test.ssh_client import ErreurMSA, SessionMSA


class SessionFactice(SessionMSA):
    """Session dont `executer` est remplace par un scenario fige."""

    def __init__(self, reponses):
        super().__init__("192.168.0.187", "operateur", "motdepasse")
        self.reponses = reponses
        self.commandes = []

    def executer(self, commande, delai=None):
        self.commandes.append(commande)
        for motif, reponse in self.reponses:
            if motif in commande:
                return reponse
        raise AssertionError("commande inattendue : %s" % commande)


@pytest.mark.parametrize("uid", ["1000", "1010", "500", "10", "20"])
def test_un_uid_terminant_par_zero_n_est_pas_root(uid):
    """Regression : `endswith('0')` prenait l'UID 1000 pour l'UID 0."""
    session = SessionFactice([("id -u", (uid, 0))])
    assert session.est_root() is False


def test_uid_zero_est_root():
    session = SessionFactice([("id -u", ("0", 0))])
    assert session.est_root() is True


def test_uid_lu_sur_la_derniere_ligne():
    """L'echo du terminal peut preceder la valeur retournee par `id -u`."""
    session = SessionFactice([("id -u", ("id -u\r\n0", 0))])
    assert session.est_root() is True


def test_uid_illisible_remonte_une_erreur():
    session = SessionFactice([("id -u", ("   \r\n", 0))])
    with pytest.raises(ErreurMSA):
        session.est_root()


def test_smartctl_refuse_hors_super_utilisateur():
    session = SessionFactice([("smartctl", ("smartctl: Permission denied", 2))])
    with pytest.raises(ErreurMSA) as erreur:
        session.smartctl("/dev/sda1")
    assert "Super Utilisateur" in str(erreur.value)


def test_smartctl_bascule_sur_le_chemin_absolu():
    """Le PATH du compte SSH n'inclut pas toujours /usr/sbin."""
    sortie = "199 UDMA_CRC_Error_Count 0x003e 200 200 000 Old_age Always - 0"
    session = SessionFactice(
        [
            ("/usr/sbin/smartctl", (sortie, 0)),
            ("smartctl", ("bash: smartctl: command not found", 127)),
        ]
    )
    assert session.smartctl("/dev/sda1") == sortie
    assert any("/usr/sbin/smartctl" in c for c in session.commandes)
