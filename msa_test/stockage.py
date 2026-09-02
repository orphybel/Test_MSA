"""Relevé de la capacité de stockage des modules CPU enregistreur.

La procedure demande d'envoyer, avec un client HTTP (INSOMNIA), la requete :

    GET http://<adresse du MSA>:8080/storage/status

Chaque module repond en JSON, avec notamment la capacite de stockage :

    {"capacity": 3755205, "hdd_status_entries": [ ... ]}

Ce module effectue la meme requete et en extrait la capacite, afin de
verifier que la capacite totale de chaque MSA est suffisante.
"""

import json

import requests

DELAI_HTTP = 20  # secondes
PORT_STOCKAGE = 8080
CHEMIN_STOCKAGE = "/storage/status"

MO_PAR_GO = 1024
MO_PAR_TO = 1024 * 1024


class ErreurStockage(Exception):
    """Erreur fonctionnelle remontee a l'operateur (message en clair)."""


def url_stockage(ip, port=PORT_STOCKAGE):
    return "http://%s:%d%s" % (ip, port, CHEMIN_STOCKAGE)


def formater_capacite(capacite_mo):
    """Presente une capacite en Mo, avec son equivalent en Go et To."""
    if capacite_mo is None:
        return "non relevée"
    mo = "{:,}".format(int(capacite_mo)).replace(",", " ")
    return "%s Mo (%.1f Go / %.2f To)" % (
        mo,
        capacite_mo / MO_PAR_GO,
        capacite_mo / MO_PAR_TO,
    )


def _chercher_capacite(donnees):
    """Retourne la valeur de "capacity", meme imbriquee dans la reponse."""
    if isinstance(donnees, dict):
        for cle, valeur in donnees.items():
            if cle.lower() == "capacity" and isinstance(valeur, (int, float)):
                return valeur
        for valeur in donnees.values():
            trouvee = _chercher_capacite(valeur)
            if trouvee is not None:
                return trouvee
    elif isinstance(donnees, list):
        for element in donnees:
            trouvee = _chercher_capacite(element)
            if trouvee is not None:
                return trouvee
    return None


def analyser_reponse(texte):
    """Extrait la capacite et les entrees disque de la reponse JSON."""
    try:
        donnees = json.loads(texte)
    except ValueError:
        raise ErreurStockage(
            "La reponse du module n'est pas du JSON exploitable."
        )
    capacite = _chercher_capacite(donnees)
    if capacite is None:
        raise ErreurStockage(
            "La reponse ne contient pas de champ 'capacity'."
        )
    entrees = donnees.get("hdd_status_entries") if isinstance(donnees, dict) else None
    return {
        "capacite_mo": capacite,
        "entrees": entrees if isinstance(entrees, list) else [],
        "brut": donnees,
    }


def interroger(ip, port=PORT_STOCKAGE, login=None, mot_de_passe=None):
    """Envoie la requete GET /storage/status et retourne la capacite lue."""
    url = url_stockage(ip, port)
    try:
        reponse = requests.get(url, timeout=DELAI_HTTP)
        if reponse.status_code == 401 and login:
            reponse = requests.get(
                url, timeout=DELAI_HTTP, auth=(login, mot_de_passe or "")
            )
        reponse.raise_for_status()
    except requests.exceptions.ConnectionError:
        raise ErreurStockage("connexion refusée sur le port %d" % port)
    except requests.exceptions.Timeout:
        raise ErreurStockage("delai depasse (%d s)" % DELAI_HTTP)
    except requests.exceptions.HTTPError as err:
        code = getattr(err.response, "status_code", "?")
        raise ErreurStockage("reponse HTTP %s" % code)
    except requests.RequestException as err:
        raise ErreurStockage("requete impossible : %s" % type(err).__name__)
    releve = analyser_reponse(reponse.text)
    releve["url"] = url
    return releve


def verdict(capacite_mo, minimum_mo):
    """Sanction du relevé : (texte, conforme).

    La procedure demande de verifier que la capacite totale est suffisante
    sans fixer de valeur : sans minimum renseigne, la capacite est seulement
    relevée et l'operateur tranche.
    """
    if capacite_mo is None:
        return "NON RELEVE", False
    if not minimum_mo:
        return "relevé - a comparer au minimum attendu", None
    if capacite_mo >= minimum_mo:
        return "SUFFISANTE (minimum %s Mo)" % "{:,}".format(
            int(minimum_mo)
        ).replace(",", " "), True
    return "INSUFFISANTE (minimum %s Mo)" % "{:,}".format(
        int(minimum_mo)
    ).replace(",", " "), False
