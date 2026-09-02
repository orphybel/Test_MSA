"""Deroulement d'une campagne de relevé SMART sur 1 a 6 modules MSA.

Phase "avant"  -> etapes 12, 13, 14 et 15 de la procedure X301773.
Phase "apres"  -> etape 24 (memes relevés + comparaison avec la phase avant).
"""

import datetime
import ipaddress
import os

from .smart_parser import (
    ATTRIBUTS,
    SmartIntrouvable,
    releve_partition,
    valeur_est_nulle,
)
from .ssh_client import ErreurMSA, SessionMSA
from .stockage import (
    CAPACITE_MINIMALE,
    ErreurStockage,
    LOGIN_REST,
    MOT_DE_PASSE_REST,
    formater_capacite,
    interroger,
    verdict,
)
from .web_mac import ErreurWeb, extraire_macs, normaliser_url, relever_macs_web

NB_MSA_MAX = 6
PARTITIONS = ("/dev/sda1", "/dev/sdb1")

# (identifiant SMART, cle correspondante dans un relevé de partition)
CLES_ATTRIBUTS = ((188, "command_timeout"), (199, "udma_crc_error_count"))

PHASE_AVANT = "avant"
PHASE_APRES = "apres"
LIBELLE_PHASE = {
    PHASE_AVANT: "Avant enregistrement (etapes 12 a 15)",
    PHASE_APRES: "Apres enregistrement (etape 24)",
}


def valider_ip(ip_switch):
    """Controle l'adresse saisie pour la carte Controle/Switch."""
    try:
        return ipaddress.IPv4Address(str(ip_switch).strip())
    except (ipaddress.AddressValueError, ValueError):
        raise ValueError("Adresse IP invalide : %r" % ip_switch)


def liste_ip(ip_switch, nombre):
    """Etape 15 : une adresse par module MSA, a partir de la carte Controle/Switch.

    Le plan d'adressage du NVR part de la carte Controle/Switch et s'incremente
    de 1 par module implante : MSA0 = adresse de la carte + 1, MSA1 = +2, et
    ainsi de suite jusqu'a MSA5.
    """
    if not 1 <= nombre <= NB_MSA_MAX:
        raise ValueError(
            "Le nombre de MSA doit etre compris entre 1 et %d." % NB_MSA_MAX
        )
    base = valider_ip(ip_switch)
    dernier = int(base) + nombre
    if dernier > int(ipaddress.IPv4Address("255.255.255.255")):
        raise ValueError(
            "Le plan d'adressage depasse la derniere adresse IPv4 a partir "
            "de %s." % base
        )
    return [str(base + i) for i in range(1, nombre + 1)]


def relever_msa(msa, ip, login, mot_de_passe, mot_de_passe_root, port, journal):
    """Relevé complet d'un module : connexion, su, smartctl sda1 + sdb1."""
    resultat = {
        "msa": msa,
        "ip": ip,
        "partitions": {},
        "erreur": None,
        "horodatage": datetime.datetime.now().isoformat(timespec="seconds"),
    }
    try:
        journal("MSA%d (%s) : connexion SSH..." % (msa, ip))
        with SessionMSA(ip, login, mot_de_passe, mot_de_passe_root, port) as session:
            journal("MSA%d (%s) : passage en Super Utilisateur..." % (msa, ip))
            session.passer_root()
            for partition in PARTITIONS:
                journal("MSA%d (%s) : smartctl -a %s" % (msa, ip, partition))
                sortie = session.smartctl(partition)
                releve = releve_partition(sortie)
                resultat["partitions"][partition] = releve
                journal(
                    "MSA%d (%s) %s : ID#188=%s | ID#199=%s"
                    % (
                        msa,
                        ip,
                        partition,
                        releve["command_timeout"],
                        releve["udma_crc_error_count"],
                    )
                )
                for attribut_id, cle in CLES_ATTRIBUTS:
                    if valeur_est_nulle(releve[cle]) is False:
                        journal(
                            "MSA%d (%s) %s : ATTENTION, ID#%d (%s) non nul : %s"
                            % (
                                msa,
                                ip,
                                partition,
                                attribut_id,
                                ATTRIBUTS[attribut_id],
                                releve[cle],
                            )
                        )
                if releve["manquants"]:
                    journal(
                        "MSA%d (%s) %s : ATTENTION, attribut(s) absent(s) : %s"
                        % (msa, ip, partition, ", ".join(releve["manquants"]))
                    )
    except (ErreurMSA, SmartIntrouvable) as err:
        resultat["erreur"] = str(err)
        journal("MSA%d (%s) : ECHEC - %s" % (msa, ip, err))
    except Exception as err:  # garde-fou : un MSA en echec n'arrete pas la campagne
        resultat["erreur"] = "Erreur inattendue : %s" % err
        journal("MSA%d (%s) : ECHEC - %s" % (msa, ip, err))
    return resultat


def executer_campagne(config, journal, sur_resultat=None, arret=None):
    """Parcourt les modules MSA et retourne la campagne complete."""
    ips = liste_ip(config["ip_switch"], config["nombre_msa"])
    campagne = {
        "phase": config["phase"],
        "libelle_phase": LIBELLE_PHASE[config["phase"]],
        "ip_switch": config["ip_switch"],
        "nombre_msa": config["nombre_msa"],
        "operateur": config.get("operateur", ""),
        "serie_nvr": config.get("serie_nvr", ""),
        "date": datetime.datetime.now().isoformat(timespec="seconds"),
        "modules": [],
    }
    for msa, ip in enumerate(ips):
        if arret is not None and arret.is_set():
            journal("Campagne interrompue par l'operateur.")
            break
        resultat = relever_msa(
            msa,
            ip,
            config["login"],
            config["mot_de_passe"],
            config.get("mot_de_passe_root"),
            config.get("port", 22),
            journal,
        )
        campagne["modules"].append(resultat)
        if sur_resultat is not None:
            sur_resultat(resultat)
    return campagne


# ---------------------------------------------------------------------- #
# Etape 24 : comparaison avant / apres
# ---------------------------------------------------------------------- #
def comparer(campagne_avant, campagne_apres):
    """Compare les RAW_VALUE des deux phases, module par module et partition.

    Retourne une liste de lignes de verdict et un booleen global de conformite.
    """
    avant_par_msa = {m["msa"]: m for m in campagne_avant.get("modules", [])}
    lignes = []
    conforme = True

    for module in campagne_apres.get("modules", []):
        msa = module["msa"]
        reference = avant_par_msa.get(msa)
        for partition in PARTITIONS:
            ligne = {
                "msa": msa,
                "ip": module["ip"],
                "partition": partition,
                "avant_188": None,
                "apres_188": None,
                "avant_199": None,
                "apres_199": None,
                "verdict": "",
            }
            apres = module["partitions"].get(partition)
            ref = reference["partitions"].get(partition) if reference else None

            if module.get("erreur") or apres is None:
                ligne["verdict"] = "NON TESTE (%s)" % (
                    module.get("erreur") or "relevé absent"
                )
                conforme = False
                lignes.append(ligne)
                continue
            if ref is None:
                ligne["verdict"] = "PAS DE RELEVE AVANT"
                ligne["apres_188"] = apres["command_timeout"]
                ligne["apres_199"] = apres["udma_crc_error_count"]
                conforme = False
                lignes.append(ligne)
                continue

            ligne["avant_188"] = ref["command_timeout"]
            ligne["apres_188"] = apres["command_timeout"]
            ligne["avant_199"] = ref["udma_crc_error_count"]
            ligne["apres_199"] = apres["udma_crc_error_count"]

            ecarts = []
            for cle, attribut_id in (("188", 188), ("199", 199)):
                valeur_avant = ligne["avant_%s" % cle]
                valeur_apres = ligne["apres_%s" % cle]
                if valeur_avant is None or valeur_apres is None:
                    ecarts.append("ID#%d non relevé" % attribut_id)
                elif valeur_avant.strip() != valeur_apres.strip():
                    ecarts.append(
                        "ID#%d (%s) : %s -> %s"
                        % (attribut_id, ATTRIBUTS[attribut_id], valeur_avant, valeur_apres)
                    )
            if ecarts:
                ligne["verdict"] = "NON CONFORME - " + " ; ".join(ecarts)
                conforme = False
            else:
                ligne["verdict"] = "CONFORME (valeurs identiques)"
            lignes.append(ligne)

    if not lignes:
        conforme = False
    return lignes, conforme


def alertes_valeurs_non_nulles(campagne):
    """Liste les RAW_VALUE non nulles relevées sur une campagne.

    La procedure ne sanctionne que l'egalite des valeurs avant/apres
    (etape 24) : une valeur non nulle n'est donc pas un echec au sens du PV,
    mais elle traduit des erreurs deja comptabilisees par le disque et doit
    etre portee a la connaissance de l'operateur.
    """
    alertes = []
    for module in campagne.get("modules", []):
        for partition in PARTITIONS:
            releve = module.get("partitions", {}).get(partition)
            if not releve:
                continue
            for attribut_id, cle in CLES_ATTRIBUTS:
                if valeur_est_nulle(releve.get(cle)) is False:
                    alertes.append(
                        {
                            "msa": module["msa"],
                            "ip": module["ip"],
                            "partition": partition,
                            "attribut_id": attribut_id,
                            "attribut": ATTRIBUTS[attribut_id],
                            "valeur": releve.get(cle),
                        }
                    )
    return alertes


def alertes_avant_apres(campagne_avant, campagne_apres=None):
    """Alertes consolidees sur les deux phases.

    Pour chaque module, la phase "apres" fait foi ; on retombe sur la phase
    "avant" lorsqu'elle n'a rien releve (module injoignable a l'etape 24),
    afin qu'une valeur non nulle deja mesuree ne disparaisse pas du rapport.
    """
    avant_par_msa = {m["msa"]: m for m in (campagne_avant or {}).get("modules", [])}
    apres_par_msa = {m["msa"]: m for m in (campagne_apres or {}).get("modules", [])}
    modules = []
    for numero in sorted(set(avant_par_msa) | set(apres_par_msa)):
        module = apres_par_msa.get(numero)
        if not module or module.get("erreur") or not module.get("partitions"):
            # Relevé "apres" absent ou incomplet : le relevé "avant" fait foi.
            module = avant_par_msa.get(numero) or module
        if module:
            modules.append(module)
    return alertes_valeurs_non_nulles({"modules": modules})


# ---------------------------------------------------------------------- #
# Relevé des adresses MAC
# ---------------------------------------------------------------------- #
def relever_mac(libelle, ip, login, mot_de_passe, port, journal):
    """Relevé des adresses MAC d'un equipement (MSA ou carte control switch).

    La lecture des adresses MAC ne demande pas les droits root : aucun `su`
    n'est effectue ici.
    """
    resultat = {
        "libelle": libelle,
        "ip": ip,
        "interfaces": [],
        "erreur": None,
        "horodatage": datetime.datetime.now().isoformat(timespec="seconds"),
    }
    try:
        journal("%s (%s) : connexion SSH..." % (libelle, ip))
        with SessionMSA(ip, login, mot_de_passe, None, port) as session:
            resultat["interfaces"] = session.adresses_mac()
        for interface in resultat["interfaces"]:
            journal(
                "%s (%s) : %s = %s"
                % (libelle, ip, interface["interface"], interface["mac"])
            )
    except ErreurMSA as err:
        resultat["erreur"] = str(err)
        journal("%s (%s) : ECHEC - %s" % (libelle, ip, err))
    except Exception as err:  # un equipement en echec n'arrete pas le relevé
        resultat["erreur"] = "Erreur inattendue : %s" % err
        journal("%s (%s) : ECHEC - %s" % (libelle, ip, err))
    return resultat


SOURCE_SWITCH_WEB = "web"
SOURCE_SWITCH_SSH = "ssh"
SOURCE_SWITCH_AUCUNE = "aucune"


def relever_mac_switch_web(config, journal):
    """Relevé des MAC de la carte control switch via son interface web.

    Les identifiants SSH de cette carte ne sont pas toujours connus alors que
    ceux de l'interface web le sont : la page qui affiche les adresses est
    alors lue directement en HTTP.
    """
    ip = str(valider_ip(config["ip_switch"]))
    url = normaliser_url(config.get("url_web"), ip)
    resultat = {
        "libelle": "Carte Controle/Switch",
        "ip": ip,
        "url": url,
        "source": "interface web",
        "interfaces": [],
        "erreur": None,
        "horodatage": datetime.datetime.now().isoformat(timespec="seconds"),
    }
    try:
        resultat["interfaces"] = relever_macs_web(
            url, config.get("login_web", ""), config.get("mot_de_passe_web", ""), journal
        )
    except ErreurWeb as err:
        resultat["erreur"] = str(err)
        journal("Interface web (%s) : ECHEC - %s" % (url, err))
    except Exception as err:  # un echec ici n'arrete pas le relevé des MSA
        resultat["erreur"] = "Erreur inattendue : %s" % err
        journal("Interface web (%s) : ECHEC - %s" % (url, err))
    return resultat


def equipements_mac(config):
    """Liste des equipements a interroger : carte control switch puis MSA.

    La carte Controle/Switch n'y figure que lorsqu'elle est relevée en SSH :
    par defaut elle passe par son interface web, traitee separement.
    """
    equipements = []
    login_switch = (config.get("login_switch") or "").strip()
    if config.get("source_switch", SOURCE_SWITCH_WEB) == SOURCE_SWITCH_SSH and login_switch:
        equipements.append(
            {
                "libelle": "Carte Controle/Switch",
                "ip": str(valider_ip(config["ip_switch"])),
                "login": login_switch,
                "mot_de_passe": config.get("mot_de_passe_switch", ""),
                "source": "SSH",
            }
        )
    for numero, ip in enumerate(liste_ip(config["ip_switch"], config["nombre_msa"])):
        equipements.append(
            {
                "libelle": "MSA%d" % numero,
                "ip": ip,
                "login": config["login"],
                "mot_de_passe": config["mot_de_passe"],
                "source": "SSH",
            }
        )
    return equipements


def executer_campagne_mac(config, journal, sur_resultat=None, arret=None):
    """Relève les adresses MAC de la carte control switch et des MSA."""
    source_switch = config.get("source_switch", SOURCE_SWITCH_WEB)
    equipements = equipements_mac(config)
    campagne = {
        "type": "mac",
        "ip_switch": config["ip_switch"],
        "nombre_msa": config["nombre_msa"],
        "operateur": config.get("operateur", ""),
        "serie_nvr": config.get("serie_nvr", ""),
        "source_switch": source_switch,
        "date": datetime.datetime.now().isoformat(timespec="seconds"),
        "equipements": [],
    }
    if source_switch == SOURCE_SWITCH_WEB:
        resultat = relever_mac_switch_web(config, journal)
        campagne["equipements"].append(resultat)
        if sur_resultat is not None:
            sur_resultat(resultat)

    for equipement in equipements:
        if arret is not None and arret.is_set():
            journal("Relevé des adresses MAC interrompu par l'operateur.")
            break
        resultat = relever_mac(
            equipement["libelle"],
            equipement["ip"],
            equipement["login"],
            equipement["mot_de_passe"],
            config.get("port", 22),
            journal,
        )
        resultat["source"] = equipement.get("source", "SSH")
        campagne["equipements"].append(resultat)
        if sur_resultat is not None:
            sur_resultat(resultat)
    return campagne


def campagne_mac_depuis_page(chemin, config, journal):
    """Construit un relevé a partir d'une page de l'interface web enregistrée.

    Sert de recours lorsque l'authentification de l'interface web ne peut pas
    etre automatisee : l'operateur enregistre la page depuis son navigateur
    (Ctrl+S) et l'application en extrait les adresses.
    """
    with open(chemin, "r", encoding="utf-8", errors="replace") as fichier:
        contenu = fichier.read()
    interfaces = extraire_macs(contenu)
    journal("Page enregistrée %s : %d adresse(s) MAC extraite(s)."
            % (chemin, len(interfaces)))
    if not interfaces:
        raise ErreurWeb(
            "Aucune adresse MAC trouvée dans %s." % os.path.basename(chemin)
        )
    for interface in interfaces:
        journal("Page enregistrée : %s = %s"
                % (interface["interface"], interface["mac"]))
    return {
        "type": "mac",
        "ip_switch": config.get("ip_switch", ""),
        "nombre_msa": config.get("nombre_msa", 0),
        "operateur": config.get("operateur", ""),
        "serie_nvr": config.get("serie_nvr", ""),
        "source_switch": "page",
        "date": datetime.datetime.now().isoformat(timespec="seconds"),
        "equipements": [
            {
                "libelle": "Interface web du NVR",
                "ip": str(valider_ip(config["ip_switch"]))
                if config.get("ip_switch")
                else "",
                "url": os.path.basename(chemin),
                "source": "page enregistrée",
                "interfaces": interfaces,
                "erreur": None,
                "horodatage": datetime.datetime.now().isoformat(timespec="seconds"),
            }
        ],
    }


# ---------------------------------------------------------------------- #
# Capacite de stockage (GET http://<MSA>:8080/storage/status)
# ---------------------------------------------------------------------- #
def relever_stockage(msa, ip, config, journal):
    """Interroge un module CPU enregistreur sur sa capacite de stockage."""
    resultat = {
        "msa": msa,
        "ip": ip,
        "capacite_ko": None,
        "entrees": [],
        "sanction": "",
        "conforme": None,
        "erreur": None,
        "horodatage": datetime.datetime.now().isoformat(timespec="seconds"),
    }
    try:
        journal("MSA%d (%s) : GET %s:8080/storage/status" % (msa, ip, ip))
        releve = interroger(
            ip,
            config.get("port_stockage", 8080),
            config.get("login_rest", LOGIN_REST),
            config.get("mot_de_passe_rest", MOT_DE_PASSE_REST),
        )
        resultat["capacite_ko"] = releve["capacite_ko"]
        resultat["entrees"] = releve["entrees"]
        resultat["url"] = releve["url"]
        journal(
            "MSA%d (%s) : capacite = %s"
            % (msa, ip, formater_capacite(releve["capacite_ko"]))
        )
        if releve["entrees"]:
            journal(
                "MSA%d (%s) : %d entrée(s) disque signalée(s)"
                % (msa, ip, len(releve["entrees"]))
            )
    except ErreurStockage as err:
        resultat["erreur"] = str(err)
        journal("MSA%d (%s) : ECHEC - %s" % (msa, ip, err))
    except Exception as err:  # un module en echec n'arrete pas la campagne
        resultat["erreur"] = "Erreur inattendue : %s" % err
        journal("MSA%d (%s) : ECHEC - %s" % (msa, ip, err))

    sanction, conforme = verdict(
        resultat["capacite_ko"],
        config.get("capacite_minimale_ko", CAPACITE_MINIMALE),
    )
    if resultat["erreur"]:
        sanction, conforme = "NON RELEVE (%s)" % resultat["erreur"], False
    resultat["sanction"] = sanction
    resultat["conforme"] = conforme
    return resultat


def executer_campagne_stockage(config, journal, sur_resultat=None, arret=None):
    """Relève la capacite de stockage de chaque module CPU enregistreur."""
    campagne = {
        "type": "stockage",
        "ip_switch": config["ip_switch"],
        "nombre_msa": config["nombre_msa"],
        "operateur": config.get("operateur", ""),
        "serie_nvr": config.get("serie_nvr", ""),
        "capacite_minimale_ko": config.get("capacite_minimale_ko", CAPACITE_MINIMALE),
        "date": datetime.datetime.now().isoformat(timespec="seconds"),
        "modules": [],
    }
    for msa, ip in enumerate(liste_ip(config["ip_switch"], config["nombre_msa"])):
        if arret is not None and arret.is_set():
            journal("Relevé des capacites interrompu par l'operateur.")
            break
        resultat = relever_stockage(msa, ip, config, journal)
        campagne["modules"].append(resultat)
        if sur_resultat is not None:
            sur_resultat(resultat)
    return campagne
