"""Remplissage des fiches de test Excel (PV) a partir des releves.

Les PV fournis (X255082-1_MP14_MSA_... et X255082-1_RERNG_MSA_...) sont des
classeurs .xlsm comportant des macros, plus d'une centaine de controles
ActiveX et de la mise en forme conditionnelle etendue. openpyxl ne sait pas
tout conserver en reenregistrant : ce module modifie donc directement le XML
des seules cellules a renseigner, et recopie a l'identique tout le reste du
classeur.

Cellules renseignees (une fiche par module MSA) :
  - "Constit produit"   F12 : numero du MSA
                        B23 : date du jour
                        B24 : operateur
  - "Test final (1_1) " C20 : RAW_VALUE ID#199 du disque 1 (/dev/sda1), apres
                        C21 : RAW_VALUE ID#199 du disque 2 (/dev/sdb1), apres
                        D20 / D21 : PASS si la valeur est identique au releve
                                    avant enregistrement, FAIL sinon
"""

import datetime
import os
import re
import zipfile
from xml.sax.saxutils import escape

FEUILLE_CONSTITUTION = "Constit produit"
FEUILLE_TEST_FINAL = "Test final (1_1) "

CELLULE_NUMERO = "F12"
CELLULE_DATE = "B23"
CELLULE_OPERATEUR = "B24"
CELLULE_199_DISQUE_1 = "C20"
CELLULE_199_DISQUE_2 = "C21"
CELLULE_SANCTION_1 = "D20"
CELLULE_SANCTION_2 = "D21"

PARTITION_DISQUE_1 = "/dev/sda1"
PARTITION_DISQUE_2 = "/dev/sdb1"

# Formule qui reprend le numero du MSA dans l'en-tete de chaque feuille.
_FORMULE_NUMERO = "'Constit produit'!F12"
_FORMULE_EN_TETE = "'Constit produit'!C2"

_ORIGINE_EXCEL = datetime.date(1899, 12, 30)


class ErreurPV(Exception):
    """Erreur fonctionnelle remontee a l'operateur (message en clair)."""


# ---------------------------------------------------------------------- #
# Lecture de la structure du classeur
# ---------------------------------------------------------------------- #
def _chemins_feuilles(archive):
    """Associe chaque nom de feuille au chemin de son XML dans l'archive."""
    classeur = archive.read("xl/workbook.xml").decode("utf-8")
    liens = archive.read("xl/_rels/workbook.xml.rels").decode("utf-8")
    cibles = {
        m.group(1): m.group(2)
        for m in re.finditer(r'<Relationship [^>]*?Id="([^"]+)"[^>]*?Target="([^"]+)"', liens)
    }
    # L'ordre des attributs n'est pas garanti : on accepte Target avant Id.
    for m in re.finditer(r'<Relationship [^>]*?Target="([^"]+)"[^>]*?Id="([^"]+)"', liens):
        cibles.setdefault(m.group(2), m.group(1))

    feuilles = {}
    for m in re.finditer(r"<sheet [^>]*/>", classeur):
        balise = m.group(0)
        nom = re.search(r'name="([^"]*)"', balise)
        rid = re.search(r'r:id="([^"]*)"', balise)
        if not nom or not rid or rid.group(1) not in cibles:
            continue
        cible = cibles[rid.group(1)].lstrip("/")
        if not cible.startswith("xl/"):
            cible = "xl/" + cible
        feuilles[_desechapper(nom.group(1))] = cible
    return feuilles


def _desechapper(texte):
    return (
        texte.replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&apos;", "'")
        .replace("&amp;", "&")
    )


def _lire_chaines_partagees(archive):
    try:
        xml = archive.read("xl/sharedStrings.xml").decode("utf-8")
    except KeyError:
        return []
    chaines = []
    for si in re.finditer(r"<si>(.*?)</si>", xml, re.S):
        morceaux = re.findall(r"<t[^>]*>(.*?)</t>", si.group(1), re.S)
        chaines.append(_desechapper("".join(morceaux)))
    return chaines


def lire_cellule(chemin_xlsm, feuille, reference):
    """Valeur affichee d'une cellule (utile aux controles et aux tests)."""
    with zipfile.ZipFile(chemin_xlsm) as archive:
        feuilles = _chemins_feuilles(archive)
        if feuille not in feuilles:
            raise ErreurPV("Feuille %r absente du classeur." % feuille)
        xml = archive.read(feuilles[feuille]).decode("utf-8")
        chaines = _lire_chaines_partagees(archive)
    cellule = _trouver_cellule(xml, reference)
    if cellule is None:
        return None
    balise = cellule.group(0)
    type_ = re.search(r'\bt="([^"]*)"', balise.split(">", 1)[0])
    type_ = type_.group(1) if type_ else "n"
    if type_ == "inlineStr":
        morceaux = re.findall(r"<t[^>]*>(.*?)</t>", balise, re.S)
        return _desechapper("".join(morceaux))
    valeur = re.search(r"<v>(.*?)</v>", balise, re.S)
    if valeur is None:
        return None
    brut = valeur.group(1)
    if type_ == "s":
        return chaines[int(brut)]
    if type_ in ("str", "e"):
        return _desechapper(brut)
    return brut


# ---------------------------------------------------------------------- #
# Ecriture des cellules
# ---------------------------------------------------------------------- #
def _trouver_cellule(xml, reference):
    return re.search(
        r'<c r="%s"(?:\s[^>]*)?(?:/>|>.*?</c>)' % re.escape(reference), xml, re.S
    )


def _style(balise):
    style = re.search(r'\bs="(\d+)"', balise.split(">", 1)[0])
    return ' s="%s"' % style.group(1) if style else ""


def _cellule_texte(reference, style, texte):
    return '<c r="%s"%s t="inlineStr"><is><t xml:space="preserve">%s</t></is></c>' % (
        reference,
        style,
        escape(str(texte)),
    )


def _cellule_nombre(reference, style, nombre):
    return '<c r="%s"%s><v>%s</v></c>' % (reference, style, nombre)


def _valeur_cellule(reference, style, valeur):
    """Nombre si la valeur en est un (conserve le format), texte sinon."""
    if isinstance(valeur, datetime.date):
        return _cellule_nombre(reference, style, (valeur - _ORIGINE_EXCEL).days)
    texte = "" if valeur is None else str(valeur).strip()
    if re.fullmatch(r"-?\d+", texte):
        return _cellule_nombre(reference, style, int(texte))
    return _cellule_texte(reference, style, texte)


def _remplacer_cellule(xml, reference, valeur):
    """Remplace une cellule existante en conservant son style."""
    trouvee = _trouver_cellule(xml, reference)
    if trouvee is None:
        raise ErreurPV(
            "Cellule %s introuvable : le modele de PV ne correspond pas a la "
            "fiche attendue." % reference
        )
    nouvelle = _valeur_cellule(reference, _style(trouvee.group(0)), valeur)
    return xml[: trouvee.start()] + nouvelle + xml[trouvee.end() :]


def _actualiser_formules(xml, formule, valeur):
    """Met a jour la valeur en cache des cellules qui portent une formule.

    Excel recalcule a l'ouverture (fullCalcOnLoad), mais un apercu ou une
    impression sans recalcul afficherait l'ancienne valeur : on la remplace.
    """
    motif = re.compile(
        # La valeur en cache peut manquer, etre vide (<v/>, <v />) ou remplie.
        r'(<c r="[A-Z]+\d+"[^>]*>)<f>%s</f>(?:<v\s*/>|<v>.*?</v>)?(</c>)'
        % re.escape(formule),
        re.S,
    )

    def remplacer(m):
        ouverture = m.group(1)
        if ' t="' in ouverture:
            ouverture = re.sub(r'\bt="[^"]*"', 't="str"', ouverture)
        else:
            ouverture = ouverture[:-1] + ' t="str">'
        return "%s<f>%s</f><v>%s</v>%s" % (ouverture, formule, escape(str(valeur)), m.group(2))

    return motif.sub(remplacer, xml)


def _forcer_recalcul(classeur_xml):
    """Demande a Excel de recalculer tout le classeur a l'ouverture."""
    if re.search(r"<calcPr\b[^>]*\bfullCalcOnLoad=", classeur_xml):
        return re.sub(r'fullCalcOnLoad="[^"]*"', 'fullCalcOnLoad="1"', classeur_xml)
    if "<calcPr" in classeur_xml:
        return re.sub(r"<calcPr\b", '<calcPr fullCalcOnLoad="1"', classeur_xml, count=1)
    return classeur_xml.replace("</workbook>", '<calcPr fullCalcOnLoad="1"/></workbook>')


# ---------------------------------------------------------------------- #
# Fiche d'un module
# ---------------------------------------------------------------------- #
def valeurs_du_module(module_apres, module_avant):
    """Valeurs ID#199 apres enregistrement et sanction de chaque disque."""
    resultat = {}
    for partition, cle in ((PARTITION_DISQUE_1, 1), (PARTITION_DISQUE_2, 2)):
        apres = (module_apres or {}).get("partitions", {}).get(partition) or {}
        avant = (module_avant or {}).get("partitions", {}).get(partition) or {}
        valeur_apres = apres.get("udma_crc_error_count")
        valeur_avant = avant.get("udma_crc_error_count")
        identique = (
            valeur_apres is not None
            and valeur_avant is not None
            and str(valeur_apres).strip() == str(valeur_avant).strip()
        )
        resultat[cle] = (valeur_apres, "PASS" if identique else "FAIL")
    return resultat


def nom_du_pv(modele, numero_msa):
    """Nom du PV produit, sur le modele du fichier source.

    Les PV fournis portent le numero du MSA dans leur nom
    (X255082-1_MP14_MSA_Fiche-de-Test-SAV_0051137_0006.xlsm) : ce numero est
    remplace par celui du module teste. A defaut, le numero est ajoute.
    """
    dossier, fichier = os.path.split(modele)
    racine, extension = os.path.splitext(fichier)
    numero = _nettoyer_nom(numero_msa)
    try:
        ancien = lire_cellule(modele, FEUILLE_CONSTITUTION, CELLULE_NUMERO)
    except (ErreurPV, KeyError, zipfile.BadZipFile):
        ancien = None
    ancien = _nettoyer_nom(ancien) if ancien else ""
    if ancien and ancien in racine:
        return racine.replace(ancien, numero) + extension
    return "%s_%s%s" % (racine, numero, extension)


def _nettoyer_nom(texte):
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(texte).strip())


def remplir_pv(modele, destination, numero_msa, operateur, valeurs, date=None):
    """Produit une fiche de test a partir du modele.

    `valeurs` vaut {1: (raw_199, "PASS"|"FAIL"), 2: (...)} pour les deux
    disques. Seules les cellules de la fiche sont modifiees : macros,
    controles ActiveX, mise en forme et feuilles cachees sont recopies tels
    quels.
    """
    if not numero_msa or not str(numero_msa).strip():
        raise ErreurPV("Le numero du MSA est vide.")
    date = date or datetime.date.today()

    try:
        source = zipfile.ZipFile(modele)
    except (OSError, zipfile.BadZipFile) as err:
        raise ErreurPV("Modele de PV illisible (%s) : %s" % (modele, err))

    with source:
        feuilles = _chemins_feuilles(source)
        for feuille in (FEUILLE_CONSTITUTION, FEUILLE_TEST_FINAL):
            if feuille not in feuilles:
                raise ErreurPV(
                    "La feuille %r est absente du modele %s."
                    % (feuille.strip(), os.path.basename(modele))
                )

        modifications = {}

        constitution = source.read(feuilles[FEUILLE_CONSTITUTION]).decode("utf-8")
        constitution = _remplacer_cellule(constitution, CELLULE_NUMERO, str(numero_msa).strip())
        constitution = _remplacer_cellule(constitution, CELLULE_DATE, date)
        constitution = _remplacer_cellule(constitution, CELLULE_OPERATEUR, operateur or "")
        modifications[feuilles[FEUILLE_CONSTITUTION]] = constitution

        final = source.read(feuilles[FEUILLE_TEST_FINAL]).decode("utf-8")
        valeur_1, sanction_1 = valeurs[1]
        valeur_2, sanction_2 = valeurs[2]
        final = _remplacer_cellule(final, CELLULE_199_DISQUE_1, valeur_1)
        final = _remplacer_cellule(final, CELLULE_199_DISQUE_2, valeur_2)
        final = _remplacer_cellule(final, CELLULE_SANCTION_1, sanction_1)
        final = _remplacer_cellule(final, CELLULE_SANCTION_2, sanction_2)
        modifications[feuilles[FEUILLE_TEST_FINAL]] = final

        # Le numero du MSA est repris par formule en en-tete de chaque feuille.
        for chemin in set(feuilles.values()):
            xml = modifications.get(chemin)
            if xml is None:
                xml = source.read(chemin).decode("utf-8")
            actualise = _actualiser_formules(xml, _FORMULE_NUMERO, numero_msa)
            actualise = _actualiser_formules(actualise, _FORMULE_EN_TETE, numero_msa)
            if actualise != xml:
                modifications[chemin] = actualise

        modifications["xl/workbook.xml"] = _forcer_recalcul(
            source.read("xl/workbook.xml").decode("utf-8")
        )

        os.makedirs(os.path.dirname(os.path.abspath(destination)), exist_ok=True)
        temporaire = destination + ".tmp"
        with zipfile.ZipFile(temporaire, "w") as sortie:
            for info in source.infolist():
                if info.filename in modifications:
                    sortie.writestr(info, modifications[info.filename].encode("utf-8"))
                else:
                    sortie.writestr(info, source.read(info.filename))
    os.replace(temporaire, destination)
    return destination


def generer_pvs(modele, dossier, numeros, campagne_avant, campagne_apres, operateur,
                date=None, journal=None):
    """Produit une fiche par module MSA releve.

    `numeros` associe le rang du module (0 pour MSA0...) a son numero. Un
    module sans numero, ou absent du releve apres enregistrement, est signale
    et ignore. Retourne la liste des fichiers produits et celle des anomalies.
    """
    journal = journal or (lambda message: None)
    avant = {m["msa"]: m for m in (campagne_avant or {}).get("modules", [])}
    produits, anomalies = [], []

    for module in (campagne_apres or {}).get("modules", []):
        rang = module["msa"]
        numero = (numeros.get(rang) or "").strip()
        if not numero:
            anomalies.append("MSA%d : numero du module non renseigne, PV non genere." % rang)
            continue
        if module.get("erreur") or not module.get("partitions"):
            anomalies.append(
                "MSA%d (%s) : pas de releve apres enregistrement, PV non genere."
                % (rang, numero)
            )
            continue
        valeurs = valeurs_du_module(module, avant.get(rang))
        destination = os.path.join(dossier, nom_du_pv(modele, numero))
        try:
            remplir_pv(modele, destination, numero, operateur, valeurs, date)
        except ErreurPV as err:
            anomalies.append("MSA%d (%s) : %s" % (rang, numero, err))
            continue
        produits.append(destination)
        journal(
            "PV MSA%d (%s) : disque 1 = %s (%s), disque 2 = %s (%s) -> %s"
            % (
                rang,
                numero,
                valeurs[1][0],
                valeurs[1][1],
                valeurs[2][0],
                valeurs[2][1],
                destination,
            )
        )
        for disque in (1, 2):
            if valeurs[disque][1] == "FAIL":
                anomalies.append(
                    "MSA%d (%s) : disque %d en FAIL (ID#199 different du releve "
                    "avant enregistrement)." % (rang, numero, disque)
                )
    return produits, anomalies
