"""Deroulement d'une campagne de relevé SMART sur 1 a 6 modules MSA.

Phase "avant"  -> etapes 12, 13, 14 et 15 de la procedure X301773.
Phase "apres"  -> etape 24 (memes relevés + comparaison avec la phase avant).
"""

import datetime
import ipaddress

from .smart_parser import ATTRIBUTS, SmartIntrouvable, releve_partition
from .ssh_client import ErreurMSA, SessionMSA

NB_MSA_MAX = 6
PARTITIONS = ("/dev/sda1", "/dev/sdb1")

PHASE_AVANT = "avant"
PHASE_APRES = "apres"
LIBELLE_PHASE = {
    PHASE_AVANT: "Avant enregistrement (etapes 12 a 15)",
    PHASE_APRES: "Apres enregistrement (etape 24)",
}


def liste_ip(premiere_ip, nombre):
    """Etape 15 : une IP par carte CPU, incrementee de 1 (cf. Figure 12).

    CPU0 = premiere IP saisie, CPU1 = +1, ... jusqu'a CPU5.
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


def relever_msa(cpu, ip, login, mot_de_passe, mot_de_passe_root, port, journal):
    """Relevé complet d'un module : connexion, su, smartctl sda1 + sdb1."""
    resultat = {
        "cpu": cpu,
        "ip": ip,
        "partitions": {},
        "erreur": None,
        "horodatage": datetime.datetime.now().isoformat(timespec="seconds"),
    }
    try:
        journal("CPU%d (%s) : connexion SSH..." % (cpu, ip))
        with SessionMSA(ip, login, mot_de_passe, mot_de_passe_root, port) as session:
            journal("CPU%d (%s) : passage en Super Utilisateur..." % (cpu, ip))
            session.passer_root()
            for partition in PARTITIONS:
                journal("CPU%d (%s) : smartctl -a %s" % (cpu, ip, partition))
                sortie = session.smartctl(partition)
                releve = releve_partition(sortie)
                resultat["partitions"][partition] = releve
                journal(
                    "CPU%d (%s) %s : ID#188=%s | ID#199=%s"
                    % (
                        cpu,
                        ip,
                        partition,
                        releve["command_timeout"],
                        releve["udma_crc_error_count"],
                    )
                )
                if releve["manquants"]:
                    journal(
                        "CPU%d (%s) %s : ATTENTION, attribut(s) absent(s) : %s"
                        % (cpu, ip, partition, ", ".join(releve["manquants"]))
                    )
    except (ErreurMSA, SmartIntrouvable) as err:
        resultat["erreur"] = str(err)
        journal("CPU%d (%s) : ECHEC - %s" % (cpu, ip, err))
    except Exception as err:  # garde-fou : un MSA en echec n'arrete pas la campagne
        resultat["erreur"] = "Erreur inattendue : %s" % err
        journal("CPU%d (%s) : ECHEC - %s" % (cpu, ip, err))
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
        "numero_msa": config.get("numero_msa", ""),
        "date": datetime.datetime.now().isoformat(timespec="seconds"),
        "modules": [],
    }
    for cpu, ip in enumerate(ips):
        if arret is not None and arret.is_set():
            journal("Campagne interrompue par l'operateur.")
            break
        resultat = relever_msa(
            cpu,
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
    avant_par_cpu = {m["cpu"]: m for m in campagne_avant.get("modules", [])}
    lignes = []
    conforme = True

    for module in campagne_apres.get("modules", []):
        cpu = module["cpu"]
        reference = avant_par_cpu.get(cpu)
        for partition in PARTITIONS:
            ligne = {
                "cpu": cpu,
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
