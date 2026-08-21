"""Extraction des attributs SMART utiles a la procedure X301773.

La procedure (etape 14) demande la donnee "RAW_VALUE" de :
  - ID#188 Command_Timeout
  - ID#199 UDMA_CRC_Error_Count

Format attendu d'une ligne smartctl :
ID# ATTRIBUTE_NAME  FLAG  VALUE WORST THRESH TYPE  UPDATED WHEN_FAILED RAW_VALUE
188 Command_Timeout 0x0032 100   100   000    Old_age Always      -          0
"""

import re

# Attributs releves par la procedure : id -> nom attendu
ATTRIBUTS = {
    188: "Command_Timeout",
    199: "UDMA_CRC_Error_Count",
}

_LIGNE_ATTRIBUT = re.compile(
    r"^\s*(?P<id>\d{1,3})\s+"
    r"(?P<nom>\S+)\s+"
    r"(?P<flag>0x[0-9a-fA-F]+)\s+"
    r"(?P<value>\d+)\s+"
    r"(?P<worst>\d+)\s+"
    r"(?P<thresh>\d+)\s+"
    r"(?P<type>\S+)\s+"
    r"(?P<updated>\S+)\s+"
    r"(?P<when_failed>\S+)\s+"
    r"(?P<raw>.+?)\s*$"
)


class SmartIntrouvable(Exception):
    """La sortie smartctl ne contient pas les attributs recherches."""


def parser_attributs(sortie):
    """Retourne {188: 'RAW', 199: 'RAW'} a partir d'une sortie `smartctl -a`.

    La RAW_VALUE peut contenir des espaces (ex : "0 0 0" ou "30 (Min/Max 20/45)"),
    elle est donc renvoyee telle quelle, sans reformatage.
    """
    trouves, _ = parser_attributs_et_lignes(sortie)
    return trouves


def parser_attributs_et_lignes(sortie):
    """Comme `parser_attributs`, en retournant aussi la ligne smartctl entiere.

    La ligne complete est reprise telle quelle dans le rapport visuel afin que
    l'operateur retrouve l'affichage de la console (Figure 11 de la procedure).
    """
    trouves = {}
    lignes_brutes = {}
    for ligne in sortie.splitlines():
        m = _LIGNE_ATTRIBUT.match(ligne)
        if not m:
            continue
        attribut_id = int(m.group("id"))
        if attribut_id in ATTRIBUTS:
            trouves[attribut_id] = m.group("raw").strip()
            lignes_brutes[attribut_id] = ligne.rstrip()
    return trouves, lignes_brutes


def verifier_sortie(sortie):
    """Controle qu'on est bien face a une sortie smartctl exploitable."""
    if not sortie or not sortie.strip():
        raise SmartIntrouvable("Aucune sortie renvoyee par smartctl.")
    basse = sortie.lower()
    if "command not found" in basse:
        raise SmartIntrouvable("La commande smartctl n'existe pas sur ce MSA.")
    if "permission denied" in basse or "operation not permitted" in basse:
        raise SmartIntrouvable(
            "Acces refuse : le mode Super Utilisateur (su) n'est pas actif."
        )
    if "unable to detect device type" in basse or "no such device" in basse:
        raise SmartIntrouvable("Peripherique introuvable sur le MSA.")


def releve_partition(sortie):
    """Retourne le releve d'une partition : valeurs 188/199 + sortie brute."""
    verifier_sortie(sortie)
    attributs, lignes_brutes = parser_attributs_et_lignes(sortie)
    manquants = [
        "ID#%d (%s)" % (i, ATTRIBUTS[i]) for i in ATTRIBUTS if i not in attributs
    ]
    return {
        "command_timeout": attributs.get(188),
        "udma_crc_error_count": attributs.get(199),
        # Lignes smartctl completes, telles qu'affichees dans la console.
        "ligne_188": lignes_brutes.get(188),
        "ligne_199": lignes_brutes.get(199),
        "manquants": manquants,
        "brut": sortie,
    }
