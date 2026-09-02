"""Relevé de la capacité de stockage des modules CPU enregistreur.

La procedure demande d'envoyer, avec un client HTTP (INSOMNIA), la requete :

    GET http://<adresse du MSA>:8080/storage/status

Chaque module repond en JSON, avec notamment la capacite de stockage :

    {"capacity": 3755205, "hdd_status_entries": [ ... ]}

Ce module effectue la meme requete et en extrait la capacite, afin de
verifier que la capacite totale de chaque MSA est suffisante.
"""

import json
import re

import requests
from requests.auth import HTTPBasicAuth, HTTPDigestAuth

DELAI_HTTP = 20  # secondes
PORT_STOCKAGE = 8080
CHEMIN_STOCKAGE = "/storage/status"

# Compte de l'interface REST des modules CPU enregistreur.
LOGIN_REST = "rest"
MOT_DE_PASSE_REST = "rest1234"

# Seuil d'acceptation : la capacite relevée doit valoir au moins 3 700 000 Ko.
CAPACITE_MINIMALE = 3700000

# La reponse exprime la capacite en Ko ; les equivalents facilitent la lecture.
KO_PAR_MO = 1024
KO_PAR_GO = 1024 * 1024


class ErreurStockage(Exception):
    """Erreur fonctionnelle remontee a l'operateur (message en clair)."""


def url_stockage(ip, port=PORT_STOCKAGE):
    return "http://%s:%d%s" % (ip, port, CHEMIN_STOCKAGE)


def formater_capacite(capacite_ko):
    """Presente une capacite en Ko, avec ses equivalents en Mo et Go."""
    if capacite_ko is None:
        return "non relevée"
    ko = "{:,}".format(int(capacite_ko)).replace(",", " ")
    return "%s Ko (%.0f Mo / %.2f Go)" % (
        ko,
        capacite_ko / KO_PAR_MO,
        capacite_ko / KO_PAR_GO,
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
        "capacite_ko": capacite,
        "entrees": entrees if isinstance(entrees, list) else [],
        "brut": donnees,
    }


def schemas_annonces(reponse):
    """Schemas d'authentification annonces par l'en-tete WWW-Authenticate."""
    entete = reponse.headers.get("WWW-Authenticate", "")
    return {mot.lower() for mot in re.findall(r"^\s*(\w+)|,\s*(\w+)\s+realm", entete) for mot in mot if mot}


def _defi(reponse):
    """Resume l'en-tete d'authentification, pour le diagnostic."""
    entete = reponse.headers.get("WWW-Authenticate", "")
    return entete.strip()[:80] if entete else "aucun en-tete WWW-Authenticate"


def interroger(ip, port=PORT_STOCKAGE, login=LOGIN_REST, mot_de_passe=MOT_DE_PASSE_REST):
    """Envoie la requete GET /storage/status et retourne la capacite lue.

    L'interface REST des modules demande une authentification. Le compte est
    d'abord presente en HTTP Basic, des la premiere requete : certains
    services repondent 401 sans annoncer d'en-tete d'authentification. Si le
    module refuse et reclame du Digest, la requete est rejouee avec ce
    schema, qui negocie son propre defi.
    """
    url = url_stockage(ip, port)
    mot_de_passe = mot_de_passe or ""
    try:
        reponse = requests.get(
            url,
            timeout=DELAI_HTTP,
            auth=HTTPBasicAuth(login, mot_de_passe) if login else None,
        )
        if reponse.status_code == 401 and login:
            schemas = schemas_annonces(reponse)
            # Sans annonce exploitable, le Digest est tente malgre tout :
            # c'est le seul autre schema courant sur ces equipements.
            if "digest" in schemas or not schemas:
                reponse = requests.get(
                    url,
                    timeout=DELAI_HTTP,
                    auth=HTTPDigestAuth(login, mot_de_passe),
                )
        if reponse.status_code in (401, 403):
            raise ErreurStockage(
                "identifiants REST refuses (HTTP %d, le module annonce : %s)"
                % (reponse.status_code, _defi(reponse))
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


def verdict(capacite_ko, minimum_ko=CAPACITE_MINIMALE):
    """Sanction du relevé : (texte, conforme).

    La capacite doit valoir au moins le minimum attendu (3 700 000 Ko par
    defaut). Un minimum vide laisse le relevé sans sanction.
    """
    if capacite_ko is None:
        return "NON RELEVE", False
    if not minimum_ko:
        return "relevé - a comparer au minimum attendu", None
    minimum = "{:,}".format(int(minimum_ko)).replace(",", " ")
    if capacite_ko >= minimum_ko:
        return "SUFFISANTE (minimum %s Ko)" % minimum, True
    return "INSUFFISANTE (minimum %s Ko)" % minimum, False
