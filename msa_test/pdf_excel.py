"""Export en PDF des fiches de test Excel (PV) produites.

Les PV sont des classeurs .xlsm comportant des macros et plus d'une centaine
de controles ActiveX : seul Excel les rend fidelement (LibreOffice ne sait pas
les ouvrir). L'export pilote donc Excel en arriere-plan, par automatisation
COM, exactement comme "Fichier > Exporter > PDF" :

  - instance d'Excel dediee et invisible (les classeurs deja ouverts par
    l'operateur ne sont pas touches) ;
  - macros desactivees a l'ouverture, classeur ouvert en lecture seule et
    referme sans enregistrer ;
  - classeur recalcule avant l'export, pour que l'en-tete de chaque feuille
    affiche bien le numero du MSA ;
  - seules les feuilles visibles sont exportees, selon leurs zones
    d'impression.

Necessite Windows, Microsoft Excel et le module pywin32.
"""

import os
import sys

# Constantes Excel (XlFixedFormatType, XlFixedFormatQuality, MsoAutomationSecurity)
XL_TYPE_PDF = 0
XL_QUALITE_STANDARD = 0
MSO_SECURITE_MACROS_DESACTIVEES = 3


class ErreurPDF(Exception):
    """Erreur fonctionnelle remontee a l'operateur (message en clair)."""


def _modules_com():
    """Charge pywin32, ou explique pourquoi l'export PDF est impossible."""
    if sys.platform != "win32":
        raise ErreurPDF(
            "l'export PDF necessite Windows et Microsoft Excel."
        )
    try:
        import pythoncom
        import win32com.client
    except ImportError:
        raise ErreurPDF("le module pywin32 est absent de l'installation.")
    return pythoncom, win32com.client


def chemin_pdf(chemin_classeur):
    return os.path.splitext(chemin_classeur)[0] + ".pdf"


class ExportateurExcel:
    """Instance d'Excel dediee a l'export, refermee a la sortie du bloc `with`."""

    def __init__(self):
        self._pythoncom, self._client = _modules_com()
        self.excel = None

    def __enter__(self):
        # Chaque fil d'execution qui utilise COM doit l'initialiser.
        self._pythoncom.CoInitialize()
        try:
            self.excel = self._client.DispatchEx("Excel.Application")
        except Exception as err:
            self._pythoncom.CoUninitialize()
            raise ErreurPDF("Microsoft Excel est introuvable sur ce poste (%s)." % err)
        for propriete, valeur in (
            ("Visible", False),
            ("DisplayAlerts", False),
            ("ScreenUpdating", False),
            ("EnableEvents", False),
            # Avant toute ouverture : aucune macro ne s'execute.
            ("AutomationSecurity", MSO_SECURITE_MACROS_DESACTIVEES),
        ):
            try:
                setattr(self.excel, propriete, valeur)
            except Exception:
                pass  # propriete absente d'une version ancienne : sans effet
        return self

    def exporter(self, chemin_classeur, destination=None):
        """Exporte le classeur en PDF et retourne le chemin du PDF."""
        source = os.path.abspath(chemin_classeur)
        destination = os.path.abspath(destination or chemin_pdf(chemin_classeur))
        if not os.path.isfile(source):
            raise ErreurPDF("Classeur introuvable : %s" % source)

        try:
            classeur = self.excel.Workbooks.Open(source, UpdateLinks=0, ReadOnly=True)
        except Exception as err:
            raise ErreurPDF("Excel n'a pas pu ouvrir %s : %s" % (os.path.basename(source), err))
        try:
            try:
                self.excel.CalculateFull()
            except Exception:
                pass
            if os.path.exists(destination):
                os.remove(destination)  # un PDF ouvert ailleurs bloquerait l'export
            classeur.ExportAsFixedFormat(
                XL_TYPE_PDF,
                destination,
                XL_QUALITE_STANDARD,
                True,   # IncludeDocProperties
                False,  # IgnorePrintAreas : respecte la mise en page du PV
            )
        except OSError as err:
            raise ErreurPDF("PDF %s non remplacable (fichier ouvert ?) : %s"
                            % (os.path.basename(destination), err))
        except Exception as err:
            raise ErreurPDF("Export PDF de %s impossible : %s" % (os.path.basename(source), err))
        finally:
            try:
                classeur.Close(SaveChanges=False)
            except Exception:
                pass
        if not os.path.isfile(destination):
            raise ErreurPDF("Excel n'a produit aucun PDF pour %s." % os.path.basename(source))
        return destination

    def __exit__(self, *_):
        try:
            if self.excel is not None:
                self.excel.Quit()
        except Exception:
            pass
        finally:
            self.excel = None
            self._pythoncom.CoUninitialize()


def exporter_pdfs(chemins, journal=None):
    """Exporte chaque PV en PDF a cote du classeur.

    Retourne (PDF produits, anomalies). Si Excel est indisponible, aucun PDF
    n'est produit et une seule anomalie l'explique : les PV Excel restent
    valables.
    """
    journal = journal or (lambda message: None)
    produits, anomalies = [], []
    if not chemins:
        return produits, anomalies
    try:
        with ExportateurExcel() as exportateur:
            for chemin in chemins:
                try:
                    pdf = exportateur.exporter(chemin)
                except ErreurPDF as err:
                    anomalies.append(str(err))
                    journal("PDF : %s" % err)
                    continue
                produits.append(pdf)
                journal("PDF : %s" % pdf)
    except ErreurPDF as err:
        anomalies.append("PDF non generes : %s" % err)
        journal("PDF non generes : %s" % err)
    return produits, anomalies
