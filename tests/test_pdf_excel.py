"""Export PDF des PV par automatisation d'Excel (COM).

Excel n'existe pas sur les machines de test : il est remplace par une
doublure qui enregistre les appels. On verifie ainsi ce que le logiciel
demande a Excel (macros desactivees avant l'ouverture, lecture seule,
fermeture sans enregistrer, Excel toujours referme).
"""

import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from msa_test import pdf_excel
from msa_test.pdf_excel import (
    MSO_SECURITE_MACROS_DESACTIVEES,
    XL_TYPE_PDF,
    ErreurPDF,
    chemin_pdf,
    exporter_pdfs,
)


class ClasseurFactice:
    def __init__(self, excel, chemin, echouer):
        self.excel, self.chemin, self.echouer = excel, chemin, echouer

    def ExportAsFixedFormat(self, type_, destination, qualite, proprietes, ignorer_zones):
        self.excel.journal.append(("export", type_, destination, ignorer_zones))
        if self.echouer:
            raise RuntimeError("erreur Excel simulee")
        with open(destination, "wb") as fichier:
            fichier.write(b"%PDF-1.7 factice")

    def Close(self, SaveChanges):
        self.excel.journal.append(("fermeture", SaveChanges))


class ClasseursFactices:
    def __init__(self, excel):
        self.excel = excel

    def Open(self, chemin, UpdateLinks, ReadOnly):
        # Etat de la securite des macros au moment precis de l'ouverture.
        self.excel.journal.append(
            ("ouverture", chemin, ReadOnly, self.excel.AutomationSecurity)
        )
        return ClasseurFactice(
            self.excel, chemin, os.path.basename(chemin) in self.excel.en_echec
        )


class ExcelFactice:
    def __init__(self):
        self.journal = []
        self.en_echec = set()
        self.AutomationSecurity = 1  # macros autorisees par defaut
        self.Workbooks = ClasseursFactices(self)

    def CalculateFull(self):
        self.journal.append(("recalcul",))

    def Quit(self):
        self.journal.append(("quitter",))


@pytest.fixture
def excel(monkeypatch):
    """Installe un Excel factice et un pywin32 factice, sous 'Windows'."""
    instance = ExcelFactice()
    compteurs = {"init": 0, "fin": 0}

    pythoncom = types.ModuleType("pythoncom")
    pythoncom.CoInitialize = lambda: compteurs.__setitem__("init", compteurs["init"] + 1)
    pythoncom.CoUninitialize = lambda: compteurs.__setitem__("fin", compteurs["fin"] + 1)

    client = types.ModuleType("win32com.client")
    client.DispatchEx = lambda nom: instance
    paquet = types.ModuleType("win32com")
    paquet.client = client

    monkeypatch.setitem(sys.modules, "pythoncom", pythoncom)
    monkeypatch.setitem(sys.modules, "win32com", paquet)
    monkeypatch.setitem(sys.modules, "win32com.client", client)
    monkeypatch.setattr(pdf_excel.sys, "platform", "win32")
    instance.compteurs = compteurs
    return instance


@pytest.fixture
def classeurs(tmp_path):
    chemins = []
    for numero in ("0051200_0001", "0051200_0002"):
        chemin = tmp_path / ("X255082-1_MP14_MSA_Fiche-de-Test-SAV_%s.xlsm" % numero)
        chemin.write_bytes(b"classeur")
        chemins.append(str(chemin))
    return chemins


def test_un_pdf_a_cote_de_chaque_pv(excel, classeurs):
    pdfs, anomalies = exporter_pdfs(classeurs)
    assert anomalies == []
    assert pdfs == [os.path.abspath(chemin_pdf(c)) for c in classeurs]
    assert all(os.path.isfile(pdf) for pdf in pdfs)
    assert pdfs[0].endswith("_0051200_0001.pdf")


def test_macros_desactivees_avant_l_ouverture(excel, classeurs):
    exporter_pdfs(classeurs)
    ouvertures = [e for e in excel.journal if e[0] == "ouverture"]
    assert len(ouvertures) == 2
    for _, _, lecture_seule, securite in ouvertures:
        assert lecture_seule is True
        assert securite == MSO_SECURITE_MACROS_DESACTIVEES


def test_export_pdf_respecte_la_mise_en_page(excel, classeurs):
    exporter_pdfs(classeurs)
    exports = [e for e in excel.journal if e[0] == "export"]
    assert all(type_ == XL_TYPE_PDF for _, type_, _, _ in exports)
    assert all(ignorer is False for _, _, _, ignorer in exports)  # zones d'impression


def test_classeur_recalcule_puis_ferme_sans_enregistrer(excel, classeurs):
    exporter_pdfs(classeurs[:1])
    etapes = [e[0] for e in excel.journal]
    assert etapes == ["ouverture", "recalcul", "export", "fermeture", "quitter"]
    assert ("fermeture", False) in excel.journal


def test_une_seule_instance_d_excel_toujours_refermee(excel, classeurs):
    exporter_pdfs(classeurs)
    assert excel.journal.count(("quitter",)) == 1
    assert excel.compteurs == {"init": 1, "fin": 1}


def test_un_echec_n_arrete_pas_les_autres(excel, classeurs):
    excel.en_echec.add(os.path.basename(classeurs[0]))
    pdfs, anomalies = exporter_pdfs(classeurs)
    assert len(pdfs) == 1 and pdfs[0].endswith("_0002.pdf")
    assert len(anomalies) == 1 and "0051200_0001" in anomalies[0]
    # le classeur en echec est quand meme referme, et Excel quitte
    assert excel.journal.count(("fermeture", False)) == 2
    assert excel.journal[-1] == ("quitter",)


def test_pdf_existant_remplace(excel, classeurs):
    ancien = chemin_pdf(classeurs[0])
    with open(ancien, "wb") as fichier:
        fichier.write(b"ancienne version")
    exporter_pdfs(classeurs[:1])
    assert open(ancien, "rb").read().startswith(b"%PDF")


def test_classeur_introuvable(excel, tmp_path):
    pdfs, anomalies = exporter_pdfs([str(tmp_path / "absent.xlsm")])
    assert pdfs == [] and "introuvable" in anomalies[0]


def test_liste_vide_n_ouvre_pas_excel(excel):
    assert exporter_pdfs([]) == ([], [])
    assert excel.journal == [] and excel.compteurs["init"] == 0


def test_excel_absent_du_poste(excel, classeurs, monkeypatch):
    def introuvable(nom):
        raise OSError("Classe non enregistree")

    monkeypatch.setattr(sys.modules["win32com.client"], "DispatchEx", introuvable)
    pdfs, anomalies = exporter_pdfs(classeurs)
    assert pdfs == []
    assert len(anomalies) == 1 and "Excel est introuvable" in anomalies[0]
    assert excel.compteurs == {"init": 1, "fin": 1}  # COM libere malgre tout


def test_hors_windows(classeurs, monkeypatch):
    monkeypatch.setattr(pdf_excel.sys, "platform", "linux")
    pdfs, anomalies = exporter_pdfs(classeurs)
    assert pdfs == []
    assert "Windows" in anomalies[0]


def test_pywin32_absent(classeurs, monkeypatch):
    monkeypatch.setattr(pdf_excel.sys, "platform", "win32")
    monkeypatch.setitem(sys.modules, "win32com", None)
    monkeypatch.setitem(sys.modules, "win32com.client", None)
    with pytest.raises(ErreurPDF, match="pywin32"):
        pdf_excel._modules_com()
