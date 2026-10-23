"""Report des adresses MAC dans la fiche de test du NVR."""

import os
import re
import sys
import time
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import openpyxl
import pytest
from openpyxl.styles import Border, Side

from msa_test import mac_pv
from msa_test.mac_pv import CLE_SWITCH
from msa_test.pv_excel import ErreurPV, lire_cellule

TRAIT = Side(style="thin")
CADRE = Border(left=TRAIT, right=TRAIT, top=TRAIT, bottom=TRAIT)


# ---------------------------------------------------------------------- #
# Modeles de fiche reproduisant la structure X301226 / X301281
# ---------------------------------------------------------------------- #
def _fiche(chemin, modele, slots, feuille="Constit produit"):
    """Fiche avec, pour chaque module, une ligne @MAC dont F est vide."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = feuille
    ws["A11"], ws["F11"] = "Nom de l’article", "N° Série"
    ws["B12"] = modele
    ligne = 14
    blocs = [("Module Contrôle / Switch Ethernet", "Carte Contrôle / Switch")]
    blocs += [("Module CPU Enreg. Vidéo (slot n°%d)" % k, "Carte Enregistreur Vidéo") for k in range(slots)]
    for titre, carte in blocs:
        ws["A%d" % ligne] = titre
        ws["A%d" % (ligne + 1)] = carte
        ws["B%d" % (ligne + 2)] = "@MAC                                    "
        for colonne in "BCDEFG":
            ws["%s%d" % (colonne, ligne + 2)].border = CADRE  # F reste vide mais stylee
        ligne += 3
    ws["A%d" % ligne] = "Module Stockage Amovible (Slot n°0)"
    ws["B%d" % (ligne + 1)] = "@MAC"  # @MAC hors bloc CPU : ignore
    wb.save(chemin)
    return str(chemin)


@pytest.fixture
def pv_rerng(tmp_path):
    return _fiche(tmp_path / "X301281-9_RERNG_NVR_Fiche-de-Test-DUP N°2609026-0152011-00390.xlsx",
                  "RERNG-NVR-2", 2)


@pytest.fixture
def pv_mp14(tmp_path):
    return _fiche(tmp_path / "X301226_9-MP14_FicheTest_MP14-NVR-4_N°260212-0154864-00107.xlsx",
                  "MP14-NVR-4", 6, feuille="Constit produit(1_2)")


RELEVE = """RELEVE DES ADRESSES MAC
Equipement NVR - procedure X301773
==============================================================================

Date            : 2026-10-23T11:31:15
N° de serie NVR : 390
Operateur       : LG
Nombre de MSA   : 2

Carte Controle/Switch : relevée via son interface web.

RECAPITULATIF
----------------------------------------------------------------------------------------------------
EQUIPEMENT             ADRESSE IP       MODULE / INTERFACE                     ADRESSE MAC
Carte Controle/Switch  192.168.0.186    Module Contrôle Switch                 00:10:02:0f:da:ad
Carte Controle/Switch  192.168.0.186    Module CPU Enregistreur 0              00:e0:4b:8c:4b:cf
Carte Controle/Switch  192.168.0.186    Module CPU Enregistreur 1              00:e0:4b:8c:4b:ad
Carte Controle/Switch  192.168.0.186    cam1_Z11                               00:90:e8:71:f3:71
MSA0                   192.168.0.187    enp4s0                                 00:e0:4b:8c:4b:cf
MSA1                   192.168.0.188    enp4s0                                 00:e0:4b:8c:4b:ad

DETAIL PAR EQUIPEMENT
----------------------------------------------------------------------------------------------------
Carte Controle/Switch (http://192.168.0.186/) - source : interface web
  Module CPU Enregistreur 5                00:00:00:00:00:55
"""


def _releve(tmp_path, texte=RELEVE, nom="adresses_MAC_390_2026-10-23_11-31-15.txt"):
    chemin = tmp_path / nom
    chemin.write_text(texte, encoding="utf-8")
    return str(chemin)


# ---------------------------------------------------------------------- #
# Lecture du releve
# ---------------------------------------------------------------------- #
def test_lecture_du_releve(tmp_path):
    releve = mac_pv.lire_releve_mac(_releve(tmp_path))
    assert releve["serie_nvr"] == "390"
    assert releve["nombre_msa"] == 2
    assert releve["adresses"] == {
        CLE_SWITCH: "00:10:02:0f:da:ad",
        0: "00:e0:4b:8c:4b:cf",
        1: "00:e0:4b:8c:4b:ad",
    }
    assert set(releve["sources"].values()) == {"interface web"}
    assert releve["incoherences"] == []


def test_seul_le_recapitulatif_est_lu(tmp_path):
    """La section DETAIL (ici un slot 5 fictif) n'est pas prise en compte."""
    assert 5 not in mac_pv.lire_releve_mac(_releve(tmp_path))["adresses"]


def test_cameras_ignorees(tmp_path):
    adresses = mac_pv.lire_releve_mac(_releve(tmp_path))["adresses"].values()
    assert "00:90:e8:71:f3:71" not in adresses


def test_repli_sur_le_releve_ssh(tmp_path):
    texte = "\n".join(l for l in RELEVE.splitlines() if "CPU Enregistreur 1" not in l)
    releve = mac_pv.lire_releve_mac(_releve(tmp_path, texte))
    assert releve["adresses"][1] == "00:e0:4b:8c:4b:ad"
    assert releve["sources"][1] == "SSH"


def test_incoherence_web_ssh_signalee(tmp_path):
    texte = RELEVE.replace(
        "MSA1                   192.168.0.188    enp4s0                                 00:e0:4b:8c:4b:ad",
        "MSA1                   192.168.0.188    enp4s0                                 00:e0:4b:8c:4b:99",
    )
    releve = mac_pv.lire_releve_mac(_releve(tmp_path, texte))
    assert releve["adresses"][1] == "00:e0:4b:8c:4b:ad"  # la page web fait foi
    assert len(releve["incoherences"]) == 1 and "slot n°1" in releve["incoherences"][0]


def test_interfaces_virtuelles_ignorees(tmp_path):
    texte = RELEVE.replace(
        "MSA0                   192.168.0.187    enp4s0",
        "MSA0                   192.168.0.187    ifb0                                   02:00:00:00:00:01\n"
        "MSA0                   192.168.0.187    enp4s0",
    ).replace("Module CPU Enregistreur 0              00:e0:4b:8c:4b:cf\n", "")
    releve = mac_pv.lire_releve_mac(_releve(tmp_path, texte))
    assert releve["adresses"][0] == "00:e0:4b:8c:4b:cf"


def test_fichier_qui_n_est_pas_un_releve(tmp_path):
    with pytest.raises(ErreurPV):
        mac_pv.lire_releve_mac(_releve(tmp_path, "un autre fichier"))


def test_dernier_releve_du_dossier(tmp_path):
    ancien = _releve(tmp_path, nom="adresses_MAC_1.txt")
    time.sleep(0.01)
    recent = _releve(tmp_path, nom="adresses_MAC_2.txt")
    os.utime(ancien, (1, 1))
    assert mac_pv.dernier_releve_mac(str(tmp_path)) == recent


# ---------------------------------------------------------------------- #
# Reperage des cellules @MAC
# ---------------------------------------------------------------------- #
def test_cellules_du_pv_rerng(pv_rerng):
    analyse = mac_pv.analyser_pv(pv_rerng)
    assert analyse["modele"] == "RERNG-NVR"
    assert analyse["cellules"] == {CLE_SWITCH: "F16", 0: "F19", 1: "F22"}


def test_cellules_du_pv_mp14(pv_mp14):
    analyse = mac_pv.analyser_pv(pv_mp14)
    assert analyse["modele"] == "MP14-NVR"
    assert analyse["feuille"] == "Constit produit(1_2)"
    assert list(analyse["cellules"]) == [CLE_SWITCH, 0, 1, 2, 3, 4, 5]
    assert analyse["variante"] == 4


def test_pv_sans_ligne_mac(tmp_path):
    wb = openpyxl.Workbook()
    wb.save(tmp_path / "autre.xlsx")
    with pytest.raises(ErreurPV, match="@MAC"):
        mac_pv.analyser_pv(str(tmp_path / "autre.xlsx"))


@pytest.mark.parametrize(
    "nom,attendu",
    [
        ("X301226_9-MP14_FicheTest_MP14-NVR-4_N°260212-0154864-00107.xlsx", 4),
        ("X301226_9-MP14_FicheTest_MP14-NVR-X_N°260408-0147460-00196.xlsx", "X"),
        ("X301226_8-MP14_FicheTest_MP14-NVR-6 N° 250411-0135006-00057.xlsx", 6),
        ("X301281-9_RERNG_NVR_Fiche-de-Test-DUP N°2609026-0152011-00385.xlsm", None),
    ],
)
def test_variante_d_apres_le_nom(nom, attendu):
    assert mac_pv.variante_du_nom(nom) == attendu


# ---------------------------------------------------------------------- #
# PV concordant
# ---------------------------------------------------------------------- #
NOMS = [
    "X301226_9-MP14_FicheTest_MP14-NVR-4_N°260212-0154864-00107.xlsx",
    "X301226_9-MP14_FicheTest_MP14-NVR-X_N°260408-0147460-00196.xlsx",
    "X301226_8-MP14_FicheTest_MP14-NVR-6 N° 250411-0135006-00057.xlsx",
    "X301281-9_RERNG_NVR_Fiche-de-Test-DUP N°2609026-0152011-00385.xlsm",
    "~$X301281-9_RERNG_NVR_Fiche-de-Test-DUP N°2609026-0152011-00385.xlsm",
    "notes.txt",
]


@pytest.fixture
def dossier_pv(tmp_path):
    for nom in NOMS:
        (tmp_path / nom).write_bytes(b"x")
    return str(tmp_path)


@pytest.mark.parametrize(
    "serie,attendu",
    [
        ("107", NOMS[0]),
        ("196", NOMS[1]),
        ("57", NOMS[2]),  # 00057
        ("385", NOMS[3]),  # le fichier temporaire ~$ est ignore
        ("2609026-0152011-00385", NOMS[3]),
    ],
)
def test_pv_concordant(dossier_pv, serie, attendu):
    assert [os.path.basename(p) for p in mac_pv.pv_concordants(dossier_pv, serie)] == [attendu]


def test_aucun_pv_concordant(dossier_pv):
    assert mac_pv.pv_concordants(dossier_pv, "999") == []
    assert mac_pv.pv_concordants(dossier_pv, "") == []
    assert mac_pv.pv_concordants("/dossier/absent", "107") == []


# ---------------------------------------------------------------------- #
# Preparation et ecriture
# ---------------------------------------------------------------------- #
def test_plan_d_ecriture(pv_rerng, tmp_path):
    plan = mac_pv.preparer(pv_rerng, mac_pv.lire_releve_mac(_releve(tmp_path)))
    assert plan["erreurs"] == [] and plan["alertes"] == []
    assert [(l["cellule"], l["mac"]) for l in plan["lignes"]] == [
        ("F16", "00:10:02:0F:DA:AD"),
        ("F19", "00:E0:4B:8C:4B:CF"),
        ("F22", "00:E0:4B:8C:4B:AD"),
    ]


def test_ecriture_et_conservation_du_classeur(pv_rerng, tmp_path):
    releve = mac_pv.lire_releve_mac(_releve(tmp_path))
    with zipfile.ZipFile(pv_rerng) as archive:
        avant = {n: archive.read(n) for n in archive.namelist()}
    sauvegarde = mac_pv.ecrire(mac_pv.preparer(pv_rerng, releve), str(tmp_path / "sauv"))

    assert lire_cellule(pv_rerng, "Constit produit", "F16") == "00:10:02:0F:DA:AD"
    assert lire_cellule(pv_rerng, "Constit produit", "F19") == "00:E0:4B:8C:4B:CF"
    assert lire_cellule(pv_rerng, "Constit produit", "F22") == "00:E0:4B:8C:4B:AD"

    with zipfile.ZipFile(pv_rerng) as archive:
        apres = {n: archive.read(n) for n in archive.namelist()}
    assert list(avant) == list(apres)
    assert {n for n in avant if avant[n] != apres[n]} == {"xl/worksheets/sheet1.xml"}

    # aucune autre cellule ne disparait (cellules F vides auto-fermantes)
    cellules = lambda xml: re.findall(r'<c r="([A-Z]+\d+)"', xml.decode())
    assert cellules(avant["xl/worksheets/sheet1.xml"]) == cellules(apres["xl/worksheets/sheet1.xml"])
    ws = openpyxl.load_workbook(pv_rerng)["Constit produit"]
    assert ws["A17"].value == "Module CPU Enreg. Vidéo (slot n°0)"
    assert ws["G16"].border.left.style == "thin"

    # copie du PV d'origine
    assert os.path.basename(sauvegarde).startswith(
        "X301281-9_RERNG_NVR_Fiche-de-Test-DUP N°2609026-0152011-00390_avant_MAC_"
    )
    with zipfile.ZipFile(sauvegarde) as archive:
        assert {n: archive.read(n) for n in archive.namelist()} == avant


def test_seconde_ecriture_sans_remplacement(pv_rerng, tmp_path):
    releve = mac_pv.lire_releve_mac(_releve(tmp_path))
    mac_pv.ecrire(mac_pv.preparer(pv_rerng, releve))
    plan = mac_pv.preparer(pv_rerng, releve)
    assert [l["actuelle"] for l in plan["lignes"]] == [l["mac"] for l in plan["lignes"]]
    assert mac_pv.remplacements(plan) == []


def test_adresse_differente_signalee(pv_rerng, tmp_path):
    releve = mac_pv.lire_releve_mac(_releve(tmp_path))
    mac_pv.ecrire(mac_pv.preparer(pv_rerng, releve))
    releve["adresses"][0] = "aa:bb:cc:dd:ee:ff"
    remplacees = mac_pv.remplacements(mac_pv.preparer(pv_rerng, releve))
    assert [(l["cellule"], l["actuelle"], l["mac"]) for l in remplacees] == [
        ("F19", "00:E0:4B:8C:4B:CF", "AA:BB:CC:DD:EE:FF")
    ]


def test_slots_non_equipes_laisses_vides(pv_mp14, tmp_path):
    releve = mac_pv.lire_releve_mac(_releve(tmp_path))
    plan = mac_pv.preparer(pv_mp14, releve)
    assert [l["cle"] for l in plan["lignes"]] == [CLE_SWITCH, 0, 1]
    mac_pv.ecrire(plan)
    assert lire_cellule(pv_mp14, "Constit produit(1_2)", "F25") in (None, "")


def test_trop_de_modules_pour_le_pv(pv_rerng, tmp_path):
    releve = mac_pv.lire_releve_mac(_releve(tmp_path))
    releve["adresses"].update({k: "00:00:00:00:00:%02x" % k for k in range(2, 6)})
    plan = mac_pv.preparer(pv_rerng, releve)
    assert plan["erreurs"] and "ce n'est pas le PV de ce NVR" in plan["erreurs"][0]
    with pytest.raises(ErreurPV):
        mac_pv.ecrire(plan)


def test_variante_incoherente_signalee(pv_mp14, tmp_path):
    """Le nom indique MP14-NVR-4 mais seulement 2 modules ont ete releves."""
    plan = mac_pv.preparer(pv_mp14, mac_pv.lire_releve_mac(_releve(tmp_path)))
    assert any("MP14-NVR-4" in a for a in plan["alertes"])
    assert plan["erreurs"] == []


def test_pv_ouvert_dans_excel(pv_rerng, tmp_path, monkeypatch):
    """Le remplacement echoue (fichier verrouille) : message clair, PV intact."""
    plan = mac_pv.preparer(pv_rerng, mac_pv.lire_releve_mac(_releve(tmp_path)))
    avant = open(pv_rerng, "rb").read()

    def verrouille(source, destination):
        raise PermissionError("fichier utilise par un autre processus")

    monkeypatch.setattr("msa_test.pv_excel.os.replace", verrouille)
    with pytest.raises(ErreurPV, match="fermez-le dans Excel"):
        mac_pv.ecrire(plan)
    assert open(pv_rerng, "rb").read() == avant
    assert not os.path.exists(pv_rerng + ".tmp")
