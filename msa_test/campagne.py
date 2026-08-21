"""Deroulement d'une campagne de relevé SMART sur 1 a 6 modules MSA.

Phase "avant"  -> etapes 12, 13, 14 et 15 de la procedure X301773.
Phase "apres"  -> etape 24 (memes relevés + comparaison avec la phase avant).
"""

import datetime
import ipaddress

from .smart_parser import (
    ATTRIBUTS,
    SmartIntrouvable,
    releve_partition,
    valeur_est_nulle,
)
from .ssh_client import ErreurMSA, SessionMSA

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


def liste_ip(premiere_ip, nombre):
    """Etape 15 : une IP par module MSA, incrementee de 1 (cf. Figure 12).

    MSA0 = premiere IP saisie, MSA1 = +1, ... jusqu'a MSA5.
    """
    if not 1 <= nombre <= NB_MSA_MAX:
        raise ValueError(
            "Le nombre de MSA doit etre compris entre 1 et %d." % NB_MSA_MAX
        )
    try:
        base = ipaddress.IPv4Address(premiere_ip.strip())
    except (ipaddress.AddressValueError, ValueError):
        raise ValueError("Adresse IP invalide : %r" % premiere_ip)
    return [str(base + i) for i in range(nombre)]


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
    ips = liste_ip(config["premiere_ip"], config["nombre_msa"])
    campagne = {
        "phase": config["phase"],
        "libelle_phase": LIBELLE_PHASE[config["phase"]],
        "premiere_ip": config["premiere_ip"],
        "nombre_msa": config["nombre_msa"],
        "operateur": config.get("operateur", ""),
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
