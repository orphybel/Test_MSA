"""Sauvegarde des campagnes et generation des rapports pour le PV de test."""

import csv
import datetime
import glob
import json
import os
import re

from .campagne import (
    LIBELLE_PHASE,
    PARTITIONS,
    PHASE_AVANT,
    alertes_avant_apres,
    comparer,
)

DOSSIER_RESULTATS = "resultats_msa"


def dossier_resultats(racine=None):
    """Dossier de travail, cree au besoin, a cote de l'executable."""
    racine = racine or os.getcwd()
    chemin = os.path.join(racine, DOSSIER_RESULTATS)
    os.makedirs(chemin, exist_ok=True)
    return chemin


# Caracteres refuses par l'explorateur Windows dans un nom de fichier.
_CARACTERES_INTERDITS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def fragment_nom(serie_nvr):
    """Transforme un n de serie NVR en fragment de nom de fichier sur.

    Retourne une chaine vide si aucun numero n'est renseigne, sinon un
    fragment prefixe d'un souligne, nettoye des caracteres refuses par
    Windows et borne a 40 caracteres.
    """
    if not serie_nvr:
        return ""
    nettoye = _CARACTERES_INTERDITS.sub("_", str(serie_nvr))
    nettoye = re.sub(r"\s+", "_", nettoye.strip())
    nettoye = re.sub(r"_+", "_", nettoye).strip("._")
    if not nettoye:
        return ""
    return "_" + nettoye[:40]


def _valeur(brut):
    """Rend lisible une valeur absente dans le PV."""
    return "non relevé" if brut in (None, "") else brut


def _horodatage(campagne):
    date = campagne.get("date") or datetime.datetime.now().isoformat()
    return date.replace(":", "-").replace("T", "_")


def sauvegarder(campagne, racine=None):
    """Ecrit la campagne en JSON (relecture par la phase 'apres')."""
    nom = "campagne_%s%s_%s.json" % (
        campagne["phase"],
        fragment_nom(campagne.get("serie_nvr")),
        _horodatage(campagne),
    )
    chemin = os.path.join(dossier_resultats(racine), nom)
    with open(chemin, "w", encoding="utf-8") as fichier:
        json.dump(campagne, fichier, indent=2, ensure_ascii=False)
    return chemin


def charger(chemin):
    with open(chemin, "r", encoding="utf-8") as fichier:
        return _migrer(json.load(fichier))


def _migrer(campagne):
    """Rend lisibles les relevés produits par les versions precedentes.

    Les modules y etaient identifies par la cle "cpu" avant que la
    terminologie de la procedure ("module MSA") ne soit reprise partout.
    """
    for module in campagne.get("modules", []):
        if "msa" not in module and "cpu" in module:
            module["msa"] = module.pop("cpu")
    return campagne


def derniere_campagne_avant(racine=None):
    """Retourne le dernier relevé 'avant' enregistre, ou None."""
    motif = os.path.join(dossier_resultats(racine), "campagne_%s_*.json" % PHASE_AVANT)
    fichiers = sorted(glob.glob(motif), key=os.path.getmtime, reverse=True)
    for chemin in fichiers:
        try:
            return charger(chemin), chemin
        except (OSError, ValueError):
            continue
    return None, None


def exporter_csv(campagne, racine=None):
    """Tableau des relevés, une ligne par partition."""
    nom = "releves_%s%s_%s.csv" % (
        campagne["phase"],
        fragment_nom(campagne.get("serie_nvr")),
        _horodatage(campagne),
    )
    chemin = os.path.join(dossier_resultats(racine), nom)
    with open(chemin, "w", newline="", encoding="utf-8-sig") as fichier:
        redacteur = csv.writer(fichier, delimiter=";")
        redacteur.writerow(
            [
                "N° de serie NVR",
                "Phase",
                "MSA",
                "Adresse IP",
                "Partition",
                "ID#188 Command_Timeout (RAW_VALUE)",
                "ID#199 UDMA_CRC_Error_Count (RAW_VALUE)",
                "Etat",
            ]
        )
        for module in campagne["modules"]:
            for partition in PARTITIONS:
                releve = module["partitions"].get(partition)
                if releve is None:
                    redacteur.writerow(
                        [
                            campagne.get("serie_nvr", ""),
                            campagne["libelle_phase"],
                            "MSA%d" % module["msa"],
                            module["ip"],
                            partition,
                            "",
                            "",
                            module.get("erreur") or "non relevé",
                        ]
                    )
                    continue
                redacteur.writerow(
                    [
                        campagne.get("serie_nvr", ""),
                        campagne["libelle_phase"],
                        "MSA%d" % module["msa"],
                        module["ip"],
                        partition,
                        releve["command_timeout"] or "",
                        releve["udma_crc_error_count"] or "",
                        "OK" if not releve["manquants"] else "attribut manquant",
                    ]
                )
    return chemin


def exporter_pv(campagne_apres, campagne_avant, racine=None):
    """Synthese texte reprenant la mise en forme du PV de test (etape 24)."""
    lignes_comparaison, conforme = comparer(campagne_avant, campagne_apres)
    nom = "PV_comparaison%s_%s.txt" % (
        fragment_nom(campagne_apres.get("serie_nvr")),
        _horodatage(campagne_apres),
    )
    chemin = os.path.join(dossier_resultats(racine), nom)

    with open(chemin, "w", encoding="utf-8") as fichier:
        ecrire = fichier.write
        ecrire("PV DE TEST - Procedure X301773 (RERNG-NVR-2-DISQ / MP14-NVR-DISQ)\n")
        ecrire("Verification SMART avant / apres enregistrement (etapes 12 a 15 et 24)\n")
        ecrire("=" * 78 + "\n\n")
        ecrire("Date            : %s\n" % campagne_apres.get("date", ""))
        ecrire("Operateur       : %s\n" % (campagne_apres.get("operateur") or "..."))
        ecrire("N° de serie NVR : %s\n" % (campagne_apres.get("serie_nvr") or "..."))
        ecrire("Relevé avant    : %s\n" % campagne_avant.get("date", ""))
        ecrire("Nombre de MSA   : %s\n\n" % campagne_apres.get("nombre_msa", ""))

        for ligne in lignes_comparaison:
            ecrire("-" * 78 + "\n")
            ecrire("MSA%d (%s) - %s\n" % (ligne["msa"], ligne["ip"], ligne["partition"]))
            ecrire(
                "  ID#188 Command_Timeout      : avant=%s   apres=%s\n"
                % (_valeur(ligne["avant_188"]), _valeur(ligne["apres_188"]))
            )
            ecrire(
                "  ID#199 UDMA_CRC_Error_Count : avant=%s   apres=%s\n"
                % (_valeur(ligne["avant_199"]), _valeur(ligne["apres_199"]))
            )
            ecrire("  Sanction : %s\n" % ligne["verdict"])

        alertes = alertes_avant_apres(campagne_avant, campagne_apres)
        if alertes:
            ecrire("\n" + "=" * 78 + "\n")
            ecrire("ATTENTION - RAW_VALUE non nulles (erreurs deja comptabilisees\n")
            ecrire("par le disque). La procedure ne sanctionne que l'egalite des\n")
            ecrire("valeurs avant/apres, mais ces relevés sont a examiner :\n\n")
            for alerte in alertes:
                ecrire(
                    "  MSA%d (%s) %s : ID#%d %s = %s\n"
                    % (
                        alerte["msa"],
                        alerte["ip"],
                        alerte["partition"],
                        alerte["attribut_id"],
                        alerte["attribut"],
                        alerte["valeur"],
                    )
                )

        ecrire("\n" + "=" * 78 + "\n")
        ecrire(
            "CONCLUSION : %s\n"
            % ("CONFORME" if conforme else "NON CONFORME - voir les ecarts ci-dessus")
        )
        if alertes and conforme:
            ecrire(
                "             (valeurs inchangees, mais %d RAW_VALUE non nulle(s) "
                "signalee(s) ci-dessus)\n" % len(alertes)
            )
    return chemin, conforme


def libelle_phase(phase):
    return LIBELLE_PHASE.get(phase, phase)
