"""Report des adresses MAC relevees dans la fiche de test du NVR.

Deux familles de fiches de test (PV) existent :
  - X301226 "MP14_FicheTest_MP14-NVR-X" : NVR MP14 a 4, 5 ou 6 modules CPU
    (MP14-NVR-4 / -5 / -6), une carte Controle/Switch et six slots ;
  - X301281 "RERNG_NVR_Fiche-de-Test" : NVR RERNG a deux modules CPU.

Dans les deux cas, la feuille de constitution du produit comporte, a la fin du
bloc de chaque module (carte Controle/Switch, puis module CPU du slot n°k),
une ligne dont la colonne B vaut "@MAC" ; l'adresse se saisit dans la colonne
"N° Série" (F) de cette ligne, seule cellule laissee libre.

Les lignes @MAC sont reperees a la lecture, d'apres l'intitule du bloc qui
les precede : le report suit les revisions du modele sans dependre de numeros
de ligne figes. Comme pour les PV de test, seules les cellules visees sont
modifiees dans le XML du classeur (macros et controles ActiveX conserves).
"""

import datetime
import glob
import os
import re
import shutil
import zipfile

from .pv_excel import (
    ErreurPV,
    _chemins_feuilles,
    _desechapper,
    _lire_chaines_partagees,
    _remplacer_cellule,
    ecrire_archive,
)

MARQUEUR_MAC = "@MAC"
CLE_SWITCH = "switch"

_MAC = re.compile(r"^(?:[0-9a-f]{2}:){5}[0-9a-f]{2}$", re.IGNORECASE)


def formater_mac(mac):
    """Ecriture des PV : majuscules separees par ":" (affichage du NVR)."""
    return mac.strip().upper() if mac else mac


def libelle(cle):
    return "Carte Contrôle/Switch" if cle == CLE_SWITCH else "CPU slot n°%d" % cle


# ---------------------------------------------------------------------- #
# Lecture du releve des adresses MAC (adresses_MAC_*.txt)
# ---------------------------------------------------------------------- #
_LIGNE_RECAP = re.compile(
    r"^(?P<equipement>Carte Controle/Switch|Carte control switch|Interface web du NVR|MSA\d+)"
    r"\s+(?P<ip>\S*)\s+(?P<module>.+?)\s+(?P<mac>(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2})\s*$"
)
_INTERFACES_VIRTUELLES = re.compile(r"^(lo|ifb|veth|docker|br-|virbr|tun|tap|sit|dummy)")


def lire_releve_mac(chemin):
    """Analyse un fichier adresses_MAC_*.txt produit par le logiciel.

    Les adresses de la page web du NVR ("Module Contrôle Switch", "Module CPU
    Enregistreur k") font foi ; celles relevees en SSH sur chaque MSA servent
    de repli et de controle croise. Retourne un dictionnaire :
      serie_nvr, nombre_msa, date, adresses {"switch": mac, 0: mac, ...},
      sources {cle: texte}, incoherences [texte].
    """
    try:
        with open(chemin, "r", encoding="utf-8", errors="replace") as fichier:
            lignes = fichier.read().splitlines()
    except OSError as err:
        raise ErreurPV("Releve des adresses MAC illisible : %s" % err)

    entete = {}
    for ligne in lignes[:20]:
        m = re.match(r"^(N° de serie NVR|Nombre de MSA|Date|Operateur)\s*:\s*(.*)$", ligne)
        if m:
            entete[m.group(1)] = m.group(2).strip()

    web, ssh = {}, {}
    if "RECAPITULATIF" not in "\n".join(lignes):
        raise ErreurPV(
            "%s n'est pas un releve d'adresses MAC du logiciel (section "
            "RECAPITULATIF absente)." % os.path.basename(chemin)
        )
    dans_recap = False
    for ligne in lignes:
        if ligne.startswith("RECAPITULATIF"):
            dans_recap = True
            continue
        if ligne.startswith("DETAIL"):
            break
        if not dans_recap:
            continue
        m = _LIGNE_RECAP.match(ligne.rstrip())
        if not m:
            continue
        equipement, module = m.group("equipement"), m.group("module").strip()
        mac = m.group("mac").lower()
        slot = re.search(r"CPU Enregistreur\s*(\d+)", module, re.IGNORECASE)
        if re.search(r"Contr[oô]le\s*Switch", module, re.IGNORECASE):
            web.setdefault(CLE_SWITCH, mac)
        elif slot:
            web.setdefault(int(slot.group(1)), mac)
        elif equipement.startswith("MSA"):
            if not _INTERFACES_VIRTUELLES.match(module):
                ssh.setdefault(int(equipement[3:]), mac)
        elif equipement.lower().startswith("carte control") and not re.match(
            r"^(cam|module)", module, re.IGNORECASE
        ):
            # Carte relevee en SSH : interfaces reseau (eth0...)
            if not _INTERFACES_VIRTUELLES.match(module):
                ssh.setdefault(CLE_SWITCH, mac)

    adresses, sources, incoherences = {}, {}, []
    for cle in sorted(set(web) | set(ssh), key=lambda c: -1 if c == CLE_SWITCH else c):
        if cle in web:
            adresses[cle], sources[cle] = web[cle], "interface web"
            if cle in ssh and ssh[cle] != web[cle]:
                incoherences.append(
                    "%s : %s sur la page web du NVR, %s relevée en SSH."
                    % (libelle(cle), formater_mac(web[cle]), formater_mac(ssh[cle]))
                )
        else:
            adresses[cle], sources[cle] = ssh[cle], "SSH"
    if not adresses:
        raise ErreurPV(
            "Aucune adresse MAC exploitable dans %s." % os.path.basename(chemin)
        )

    try:
        nombre = int(entete.get("Nombre de MSA", ""))
    except ValueError:
        nombre = None
    return {
        "chemin": chemin,
        "serie_nvr": entete.get("N° de serie NVR", "").strip(" ."),
        "operateur": entete.get("Operateur", ""),
        "date": entete.get("Date", ""),
        "nombre_msa": nombre,
        "adresses": adresses,
        "sources": sources,
        "incoherences": incoherences,
    }


def dernier_releve_mac(dossier):
    """Releve d'adresses MAC le plus recent du dossier, ou None."""
    fichiers = glob.glob(os.path.join(dossier, "adresses_MAC*.txt"))
    return max(fichiers, key=os.path.getmtime) if fichiers else None


# ---------------------------------------------------------------------- #
# Reperage des cellules @MAC dans le PV
# ---------------------------------------------------------------------- #
_CELLULE = re.compile(r'<c r="([A-Z]+)(\d+)"([^>]*?)(?:/>|>(.*?)</c>)', re.S)


def _textes(xml, chaines):
    """{(colonne, ligne): texte} des cellules texte d'une feuille."""
    textes = {}
    for m in _CELLULE.finditer(xml):
        colonne, ligne, attributs, contenu = m.groups()
        contenu = contenu or ""
        type_ = re.search(r'\bt="([^"]*)"', attributs)
        type_ = type_.group(1) if type_ else "n"
        if type_ == "s":
            v = re.search(r"<v>(\d+)</v>", contenu)
            texte = chaines[int(v.group(1))] if v and int(v.group(1)) < len(chaines) else ""
        elif type_ == "inlineStr":
            texte = _desechapper("".join(re.findall(r"<t[^>]*>(.*?)</t>", contenu, re.S)))
        elif type_ == "str":
            v = re.search(r"<v>(.*?)</v>", contenu, re.S)
            texte = _desechapper(v.group(1)) if v else ""
        else:
            v = re.search(r"<v>(.*?)</v>", contenu, re.S)
            texte = v.group(1) if v else ""
        if texte != "":
            textes[(colonne, int(ligne))] = texte
    return textes


def _normaliser(texte):
    return re.sub(r"\s+", " ", texte).strip().lower()


def analyser_pv(chemin_pv):
    """Repere le modele de NVR et les cellules @MAC de la fiche de test.

    Retourne : modele ("MP14-NVR" | "RERNG-NVR" | ""), variante (4, 5, 6,
    "X" ou None, d'apres le nom du fichier), feuille, cellules
    {"switch": "F27", 0: "F32", ...}, valeurs {ref: valeur actuelle}.
    """
    try:
        archive = zipfile.ZipFile(chemin_pv)
    except (OSError, zipfile.BadZipFile) as err:
        raise ErreurPV("PV illisible (%s) : %s" % (os.path.basename(chemin_pv), err))

    candidats = []
    with archive:
        feuilles = _chemins_feuilles(archive)
        chaines = _lire_chaines_partagees(archive)
        for nom, chemin in feuilles.items():
            textes = _textes(archive.read(chemin).decode("utf-8"), chaines)
            lignes_mac = sorted(
                l for (col, l), t in textes.items() if col == "B" and t.strip() == MARQUEUR_MAC
            )
            if not lignes_mac:
                continue

            # Colonne de saisie : en-tete "N° Série" de la zone a completer.
            colonne = "F"
            for (col, l), t in textes.items():
                if re.search(r"n°\s*s[ée]rie", t, re.IGNORECASE) and col > "C":
                    colonne = col
                    break

            # Bloc courant = dernier intitule de module rencontre en colonne A.
            blocs = {}
            for ligne in sorted({l for (_, l) in textes}):
                titre = textes.get(("A", ligne), "")
                if re.search(r"Contr[oô]le\s*/\s*Switch", titre, re.IGNORECASE) and \
                        "module" in titre.lower():
                    blocs[ligne] = CLE_SWITCH
                    continue
                slot = re.search(r"slot\s*n°\s*(\d+)", titre, re.IGNORECASE)
                if slot and "cpu" in titre.lower():
                    blocs[ligne] = int(slot.group(1))
                elif titre.lower().startswith("module"):
                    blocs[ligne] = None  # autre module (alimentation, stockage...)

            cellules = {}
            for ligne_mac in lignes_mac:
                precedents = [l for l in blocs if l < ligne_mac]
                if not precedents:
                    continue
                cle = blocs[max(precedents)]
                if cle is not None and cle not in cellules:
                    cellules[cle] = "%s%d" % (colonne, ligne_mac)
            if not cellules:
                continue

            tout = " ".join(textes.values())
            if "RERNG-NVR" in tout:
                modele = "RERNG-NVR"
            elif "MP14-NVR" in tout:
                modele = "MP14-NVR"
            else:
                modele = ""
            valeurs = {}
            for ref in cellules.values():
                col, ligne = re.match(r"([A-Z]+)(\d+)$", ref).groups()
                valeurs[ref] = textes.get((col, int(ligne)), "")
            candidats.append(
                {
                    "chemin": chemin_pv,
                    "modele": modele,
                    "variante": variante_du_nom(chemin_pv),
                    "feuille": nom,
                    "cellules": cellules,
                    "valeurs": valeurs,
                }
            )
    return _choisir_feuille(chemin_pv, candidats)


def _choisir_feuille(chemin_pv, candidats):
    """Retient la feuille de constitution du produit, sans jamais deviner.

    Les fiches comportent d'autres onglets (tests, mesures...) qui ne doivent
    pas etre modifies. La feuille "Constit produit..." est preferee ; s'il
    reste plusieurs feuilles possibles, l'ecriture est refusee plutot que de
    risquer d'ecrire au mauvais endroit.
    """
    if not candidats:
        raise ErreurPV(
            "Aucune ligne « @MAC » trouvée dans %s : ce n'est pas une fiche de "
            "test NVR attendue." % os.path.basename(chemin_pv)
        )
    preferes = [c for c in candidats if _normaliser(c["feuille"]).startswith("constit")]
    retenus = preferes or candidats
    if len(retenus) > 1:
        raise ErreurPV(
            "Plusieurs onglets de %s comportent des lignes « @MAC » (%s) : "
            "impossible de savoir lequel compléter."
            % (
                os.path.basename(chemin_pv),
                ", ".join("« %s »" % c["feuille"] for c in retenus),
            )
        )
    retenu = retenus[0]
    retenu["autres_feuilles_mac"] = [
        c["feuille"] for c in candidats if c["feuille"] != retenu["feuille"]
    ]
    return retenu


def variante_du_nom(chemin):
    """4, 5, 6 pour MP14-NVR-4/5/6, "X" pour MP14-NVR-X, sinon None."""
    m = re.search(r"MP14-NVR-([0-9X])", os.path.basename(chemin), re.IGNORECASE)
    if not m:
        return None
    return m.group(1).upper() if not m.group(1).isdigit() else int(m.group(1))


# ---------------------------------------------------------------------- #
# Recherche du PV concordant
# ---------------------------------------------------------------------- #
def numero_du_pv(nom_fichier):
    """Numero de serie porte par le nom : "...N°260212-0154864-00107.xlsx"."""
    m = re.search(r"N\s*°\s*([0-9][0-9 _-]*[0-9])", nom_fichier)
    return m.group(1).strip() if m else ""


def pv_concordants(dossier, serie_nvr):
    """Fiches de test du dossier dont le numero correspond au NVR.

    Le numero saisi dans le logiciel est souvent la fin du numero de serie
    complet (390 pour ...-00390) : on compare alors au dernier groupe de
    chiffres. Un numero complet est compare tel quel. Les plus recents
    d'abord ; les fichiers temporaires d'Excel (~$...) sont ignores.
    """
    if not dossier or not os.path.isdir(dossier) or not serie_nvr:
        return []
    serie = re.sub(r"\s", "", str(serie_nvr))
    trouves = []
    for chemin in glob.glob(os.path.join(dossier, "*.xls[xm]")):
        nom = os.path.basename(chemin)
        if nom.startswith("~$"):
            continue
        numero = re.sub(r"\s", "", numero_du_pv(nom))
        if not numero:
            continue
        dernier = re.findall(r"\d+", numero)[-1]
        if numero == serie or (serie.isdigit() and int(dernier) == int(serie)):
            trouves.append(chemin)
    return sorted(trouves, key=os.path.getmtime, reverse=True)


# ---------------------------------------------------------------------- #
# Preparation et ecriture
# ---------------------------------------------------------------------- #
def preparer(chemin_pv, releve):
    """Plan d'ecriture des adresses dans le PV, a montrer avant d'ecrire.

    Retourne {"pv": analyse, "lignes": [...], "alertes": [...], "erreurs": [...]}.
    Chaque ligne vaut {cle, libelle, cellule, mac, actuelle, source}.
    """
    analyse = analyser_pv(chemin_pv)
    adresses = releve["adresses"]
    lignes, alertes, erreurs = [], list(releve.get("incoherences", [])), []

    slots_releves = sorted(c for c in adresses if c != CLE_SWITCH)
    slots_pv = sorted(c for c in analyse["cellules"] if c != CLE_SWITCH)
    hors_pv = [s for s in slots_releves if s not in analyse["cellules"]]
    if hors_pv:
        erreurs.append(
            "Le relevé contient %d module(s) CPU mais la fiche n'a que %d slot(s) "
            "(%s) : ce n'est pas le PV de ce NVR."
            % (len(slots_releves), len(slots_pv), analyse["modele"] or "modèle inconnu")
        )

    variante = analyse["variante"]
    if isinstance(variante, int) and slots_releves and len(slots_releves) != variante:
        alertes.append(
            "Le nom du PV indique un MP14-NVR-%d, mais le relevé contient %d "
            "module(s) CPU." % (variante, len(slots_releves))
        )
    if releve.get("nombre_msa") and slots_releves and releve["nombre_msa"] != len(slots_releves):
        alertes.append(
            "Le relevé annonce %d MSA mais contient les adresses de %d module(s) CPU."
            % (releve["nombre_msa"], len(slots_releves))
        )
    if CLE_SWITCH not in adresses:
        alertes.append("Adresse de la carte Contrôle/Switch absente du relevé.")
    if analyse.get("autres_feuilles_mac"):
        alertes.append(
            "Lignes « @MAC » aussi présentes dans %s : seul l'onglet « %s » est complété."
            % (
                ", ".join("« %s »" % f for f in analyse["autres_feuilles_mac"]),
                analyse["feuille"],
            )
        )

    for cle, cellule in sorted(
        analyse["cellules"].items(), key=lambda c: -1 if c[0] == CLE_SWITCH else c[0]
    ):
        mac = adresses.get(cle)
        if mac is None:
            continue  # slot non equipe : cellule laissee vide
        lignes.append(
            {
                "cle": cle,
                "libelle": libelle(cle),
                "cellule": cellule,
                "mac": formater_mac(mac),
                "actuelle": analyse["valeurs"].get(cellule, ""),
                "source": releve["sources"].get(cle, ""),
            }
        )
    return {"pv": analyse, "lignes": lignes, "alertes": alertes, "erreurs": erreurs}


def remplacements(plan):
    """Lignes dont la cellule contient deja une autre valeur."""
    return [
        l for l in plan["lignes"]
        if l["actuelle"].strip() and l["actuelle"].strip().upper() != l["mac"]
    ]


def ecrire(plan, dossier_sauvegarde=None):
    """Ecrit les adresses du plan dans le PV, sur place.

    Une copie du PV d'origine est faite au prealable dans `dossier_sauvegarde`
    si fourni. Retourne le chemin de la sauvegarde (ou None).
    """
    if plan["erreurs"]:
        raise ErreurPV(" ".join(plan["erreurs"]))
    analyse = plan["pv"]
    chemin = analyse["chemin"]

    sauvegarde = None
    if dossier_sauvegarde:
        os.makedirs(dossier_sauvegarde, exist_ok=True)
        racine, extension = os.path.splitext(os.path.basename(chemin))
        sauvegarde = os.path.join(
            dossier_sauvegarde,
            "%s_avant_MAC_%s%s"
            % (racine, datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S"), extension),
        )
        shutil.copy2(chemin, sauvegarde)

    with zipfile.ZipFile(chemin) as source:
        feuilles = _chemins_feuilles(source)
        xml = source.read(feuilles[analyse["feuille"]]).decode("utf-8")
        for ligne in plan["lignes"]:
            xml = _remplacer_cellule(xml, ligne["cellule"], ligne["mac"])
        ecrire_archive(source, chemin, {feuilles[analyse["feuille"]]: xml})
    return sauvegarde


# ---------------------------------------------------------------------- #
# Traitement par lot : un dossier de releves, un dossier de PV
# ---------------------------------------------------------------------- #
PRET = "pret"
A_VERIFIER = "a_verifier"
A_JOUR = "a_jour"
REMPLACEMENT = "remplacement"
SANS_PV = "sans_pv"
PLUSIEURS_PV = "plusieurs_pv"
SANS_NUMERO = "sans_numero"
ERREUR = "erreur"
IGNORE = "ignore"

LIBELLES_ETATS = {
    PRET: "Prêt à écrire",
    A_VERIFIER: "À vérifier avant écriture",
    A_JOUR: "Déjà à jour",
    REMPLACEMENT: "Remplacement à confirmer",
    SANS_PV: "PV introuvable",
    PLUSIEURS_PV: "Plusieurs PV possibles",
    SANS_NUMERO: "N° de NVR absent du relevé",
    ERREUR: "Erreur",
    IGNORE: "Relevé plus ancien, ignoré",
}

# Etats dont l'ecriture est possible ; les deux derniers demandent une
# confirmation de l'operateur (alerte, ou adresse deja presente et differente).
ETATS_ECRIVABLES = (PRET, A_VERIFIER, REMPLACEMENT)
ETATS_A_CONFIRMER = (A_VERIFIER, REMPLACEMENT)


def releves_du_dossier(dossier):
    """Releves d'adresses MAC du dossier et de ses sous-dossiers."""
    if not dossier or not os.path.isdir(dossier):
        return []
    trouves = []
    for racine, _, fichiers in os.walk(dossier):
        for nom in fichiers:
            if nom.startswith("adresses_MAC") and nom.lower().endswith(".txt"):
                trouves.append(os.path.join(racine, nom))
    return sorted(trouves)


def _cle_nvr(serie):
    """Identifiant de comparaison : 390, 0390 et ...-00390 designent le meme NVR."""
    serie = re.sub(r"\s", "", serie or "")
    groupes = re.findall(r"\d+", serie)
    return str(int(groupes[-1])) if groupes else serie.lower()


def _recence(entree):
    return (entree["releve"].get("date") or "", os.path.getmtime(entree["chemin_releve"]))


def _etat_du_plan(plan):
    if plan["erreurs"]:
        return ERREUR, " ".join(plan["erreurs"])
    if remplacements(plan):
        return REMPLACEMENT, "%d cellule(s) contiennent une autre adresse." % len(remplacements(plan))
    if all(l["actuelle"].strip().upper() == l["mac"] for l in plan["lignes"]):
        return A_JOUR, "Toutes les adresses sont déjà dans le PV."
    return PRET, ""


def preparer_entree(entree, chemin_pv):
    """(Re)calcule le plan d'une entree pour le PV donne."""
    entree["pv"] = chemin_pv
    entree["plan"] = None
    try:
        entree["plan"] = preparer(chemin_pv, entree["releve"])
    except ErreurPV as err:
        entree["etat"], entree["message"] = ERREUR, str(err)
        return entree
    entree["etat"], entree["message"] = _etat_du_plan(entree["plan"])
    if entree["plan"]["alertes"] and entree["etat"] != ERREUR:
        if entree["etat"] == PRET:
            entree["etat"] = A_VERIFIER  # pas d'ecriture sans accord
        entree["message"] = " ".join(
            filter(None, [entree["message"]] + entree["plan"]["alertes"])
        )
    return entree


def preparer_lot(dossier_releves, dossier_pv):
    """Associe chaque releve du dossier a la fiche de test de son NVR.

    Retourne une entree par releve, triee par numero de NVR :
      {chemin_releve, releve, serie, pv, pvs_possibles, plan, etat, message}
    Pour un meme NVR, seul le releve le plus recent est retenu. Un NVR dont
    plusieurs PV correspondent n'est pas traite sans choix de l'operateur.
    """
    entrees = []
    for chemin in releves_du_dossier(dossier_releves):
        entree = {
            "chemin_releve": chemin,
            "releve": None,
            "serie": "",
            "pv": None,
            "pvs_possibles": [],
            "plan": None,
            "etat": ERREUR,
            "message": "",
        }
        try:
            entree["releve"] = lire_releve_mac(chemin)
        except ErreurPV as err:
            entree["message"] = str(err)
            entrees.append(entree)
            continue
        entree["serie"] = entree["releve"]["serie_nvr"]
        entrees.append(entree)

    # Un seul releve par NVR : le plus recent.
    par_nvr = {}
    for entree in entrees:
        if entree["releve"] is not None and entree["serie"]:
            par_nvr.setdefault(_cle_nvr(entree["serie"]), []).append(entree)
    for groupe in par_nvr.values():
        groupe.sort(key=_recence, reverse=True)
        for ancien in groupe[1:]:
            ancien["etat"] = IGNORE
            ancien["message"] = "Relevé plus récent : %s" % os.path.basename(
                groupe[0]["chemin_releve"]
            )

    for entree in entrees:
        if entree["releve"] is None or entree["etat"] == IGNORE:
            continue
        if not entree["serie"]:
            entree["etat"] = SANS_NUMERO
            entree["message"] = "Le relevé ne porte pas de n° de NVR : associez le PV à la main."
            continue
        possibles = pv_concordants(dossier_pv, entree["serie"])
        entree["pvs_possibles"] = possibles
        if not possibles:
            entree["etat"] = SANS_PV
            entree["message"] = "Aucun PV pour le NVR n° %s dans le dossier des PV." % entree["serie"]
        elif len(possibles) > 1:
            entree["etat"] = PLUSIEURS_PV
            entree["message"] = "PV possibles : " + ", ".join(os.path.basename(p) for p in possibles)
        else:
            preparer_entree(entree, possibles[0])

    def ordre(entree):
        cle = _cle_nvr(entree["serie"]) if entree["serie"] else ""
        return (cle.zfill(12) if cle.isdigit() else "~" + cle, entree["etat"] == IGNORE)

    return sorted(entrees, key=ordre)


def ecrire_lot(entrees, dossier_sauvegarde=None, avec_confirmation=False):
    """Ecrit les adresses dans chaque PV pret.

    Les entrees a verifier ou en remplacement ne sont ecrites que si
    `avec_confirmation` (accord donne par l'operateur).
    Une erreur sur un PV (fichier ouvert dans Excel...) n'empeche pas les
    autres. Retourne la liste des (entree, sauvegarde ou None, erreur ou None)
    des PV traites.
    """
    resultats = []
    for entree in entrees:
        if entree["etat"] == PRET or (
            avec_confirmation and entree["etat"] in ETATS_A_CONFIRMER
        ):
            try:
                sauvegarde = ecrire(entree["plan"], dossier_sauvegarde)
            except (ErreurPV, OSError) as err:
                resultats.append((entree, None, str(err)))
                continue
            resultats.append((entree, sauvegarde, None))
    return resultats
