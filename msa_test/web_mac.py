"""Relevé des adresses MAC depuis l'interface web du NVR.

La carte mere control switch heberge l'interface web du NVR (etape 6 de la
procedure : http://192.168.0.186). Ses identifiants SSH ne sont pas toujours
connus de l'operateur, alors que ceux de l'interface web le sont : ce module
recupere la page qui affiche les adresses MAC et en extrait les valeurs.

Deux modes d'authentification sont pris en charge, essayes dans cet ordre :
  - authentification HTTP Basic ;
  - formulaire de connexion HTML (les champs sont detectes dans la page).
"""

import html
import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import requests

DELAI_HTTP = 20  # secondes

# Les separateurs varient d'un equipement a l'autre : 00:11:22, 00-11-22, 001122
_MAC = re.compile(
    r"\b(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b"
    r"|\b[0-9A-Fa-f]{4}(?:\.[0-9A-Fa-f]{4}){2}\b"
)
_MAC_NULLE = "00:00:00:00:00:00"
_BROADCAST = "ff:ff:ff:ff:ff:ff"


class ErreurWeb(Exception):
    """Erreur fonctionnelle remontee a l'operateur (message en clair)."""


# ---------------------------------------------------------------------- #
# Normalisation
# ---------------------------------------------------------------------- #
def normaliser_mac(brut):
    """Ramene une adresse MAC a la forme aa:bb:cc:dd:ee:ff."""
    chiffres = re.sub(r"[^0-9A-Fa-f]", "", brut)
    if len(chiffres) != 12:
        return None
    chiffres = chiffres.lower()
    return ":".join(chiffres[i : i + 2] for i in range(0, 12, 2))


def _mac_exploitable(mac):
    return mac not in (_MAC_NULLE, _BROADCAST)


# ---------------------------------------------------------------------- #
# Extraction depuis une page
# ---------------------------------------------------------------------- #
class _Texte(HTMLParser):
    """Reduit une page HTML a son texte, une ligne par cellule ou paragraphe."""

    _COUPURES = {
        "tr", "table", "div", "p", "br", "li", "h1", "h2", "h3", "h4",
        "option", "pre", "form",
    }

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.lignes = []
        self._courante = []
        self._ignore = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._ignore += 1
        elif tag in ("td", "th"):
            self._courante.append("  ")
        elif tag in self._COUPURES:
            self._couper()

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._ignore = max(0, self._ignore - 1)
        elif tag in self._COUPURES:
            self._couper()

    def handle_data(self, donnees):
        if not self._ignore:
            self._courante.append(donnees)

    def _couper(self):
        ligne = re.sub(r"\s+", " ", "".join(self._courante)).strip()
        if ligne:
            self.lignes.append(ligne)
        self._courante = []

    def close(self):
        super().close()
        self._couper()


def texte_de_la_page(page_html):
    parseur = _Texte()
    parseur.feed(page_html)
    parseur.close()
    return parseur.lignes


def extraire_macs(page_html):
    """Retourne les adresses MAC de la page, avec leur ligne d'origine.

    Chaque entree vaut {"interface": <ligne de la page>, "mac": <adresse>}.
    La ligne sert de libelle : elle porte en general le nom du port ou du
    module auquel l'adresse se rapporte. Les doublons sont ecartes en
    conservant la premiere occurrence.
    """
    trouvees = []
    deja_vues = set()
    for ligne in texte_de_la_page(page_html):
        for brut in _MAC.findall(ligne):
            mac = normaliser_mac(brut)
            if not mac or not _mac_exploitable(mac) or mac in deja_vues:
                continue
            deja_vues.add(mac)
            libelle = _libelle(ligne, brut)
            trouvees.append({"interface": libelle, "mac": mac})
    return trouvees


def _libelle(ligne, brut, longueur_max=60):
    """Ne garde de la ligne que ce qui precede l'adresse, comme intitule."""
    intitule = ligne.split(brut)[0].strip(" \t:=|-")
    intitule = re.sub(r"\s+", " ", intitule)
    if not intitule:
        intitule = ligne.replace(brut, "").strip(" \t:=|-") or "adresse relevée"
    return intitule[-longueur_max:].strip()


# ---------------------------------------------------------------------- #
# Formulaire de connexion
# ---------------------------------------------------------------------- #
class _Formulaires(HTMLParser):
    """Collecte les formulaires de la page et leurs champs."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.formulaires = []
        self._courant = None

    def handle_starttag(self, tag, attrs):
        attributs = dict(attrs)
        if tag == "form":
            self._courant = {
                "action": attributs.get("action", ""),
                "methode": (attributs.get("method") or "post").lower(),
                "champs": [],
            }
            self.formulaires.append(self._courant)
        elif tag == "input" and self._courant is not None:
            self._courant["champs"].append(
                {
                    "nom": attributs.get("name", ""),
                    "type": (attributs.get("type") or "text").lower(),
                    "valeur": attributs.get("value", ""),
                }
            )

    def handle_endtag(self, tag):
        if tag == "form":
            self._courant = None


def formulaire_de_connexion(page_html):
    """Retourne le formulaire portant un champ mot de passe, ou None."""
    parseur = _Formulaires()
    parseur.feed(page_html)
    parseur.close()
    for formulaire in parseur.formulaires:
        if any(champ["type"] == "password" for champ in formulaire["champs"]):
            return formulaire
    return None


_NOMS_LOGIN = ("user", "login", "name", "id", "account", "utilisateur", "identifiant")


def donnees_de_connexion(formulaire, login, mot_de_passe):
    """Construit le corps du POST : identifiants + champs caches conserves."""
    donnees = {}
    champ_login = None
    for champ in formulaire["champs"]:
        nom = champ["nom"]
        if not nom:
            continue
        if champ["type"] == "password":
            donnees[nom] = mot_de_passe
        elif champ["type"] in ("hidden", "submit"):
            donnees[nom] = champ["valeur"]
        elif champ_login is None and champ["type"] in ("text", "email", ""):
            champ_login = nom

    if champ_login is None:
        # Aucun champ texte : on retombe sur un nom de champ usuel.
        for champ in formulaire["champs"]:
            if champ["nom"] and any(m in champ["nom"].lower() for m in _NOMS_LOGIN):
                champ_login = champ["nom"]
                break
    if champ_login is None:
        raise ErreurWeb(
            "Le formulaire de connexion de l'interface web ne comporte pas de "
            "champ identifiant reconnaissable."
        )
    donnees[champ_login] = login
    return donnees


# ---------------------------------------------------------------------- #
# Recuperation de la page
# ---------------------------------------------------------------------- #
def _ressemble_a_une_connexion(page_html):
    return formulaire_de_connexion(page_html) is not None


def recuperer_page(url, login, mot_de_passe, session=None, verifier_tls=False):
    """Retourne le contenu de la page apres authentification.

    Le certificat n'est pas verifie : les equipements du banc utilisent des
    certificats auto-signes, et l'echange reste cantonne au reseau de test.
    """
    session = session or requests.Session()
    try:
        reponse = session.get(url, timeout=DELAI_HTTP, verify=verifier_tls)
        if reponse.status_code == 401:
            reponse = session.get(
                url, timeout=DELAI_HTTP, verify=verifier_tls,
                auth=(login, mot_de_passe),
            )
            if reponse.status_code == 401:
                raise ErreurWeb(
                    "Identifiants refusés par l'interface web (%s)." % url
                )
        reponse.raise_for_status()

        if _ressemble_a_une_connexion(reponse.text):
            reponse = _se_connecter(
                session, url, reponse, login, mot_de_passe, verifier_tls
            )
    except requests.RequestException as err:
        raise ErreurWeb("Interface web injoignable sur %s : %s" % (url, err))
    return reponse.text


def _se_connecter(session, url, reponse, login, mot_de_passe, verifier_tls):
    """Soumet le formulaire de connexion puis recharge la page demandee."""
    formulaire = formulaire_de_connexion(reponse.text)
    donnees = donnees_de_connexion(formulaire, login, mot_de_passe)
    cible = urljoin(reponse.url, formulaire["action"] or reponse.url)

    if formulaire["methode"] == "get":
        session.get(cible, params=donnees, timeout=DELAI_HTTP, verify=verifier_tls)
    else:
        session.post(cible, data=donnees, timeout=DELAI_HTTP, verify=verifier_tls)

    finale = session.get(url, timeout=DELAI_HTTP, verify=verifier_tls)
    finale.raise_for_status()
    if _ressemble_a_une_connexion(finale.text):
        raise ErreurWeb(
            "Connexion a l'interface web refusée : vérifier l'identifiant et "
            "le mot de passe."
        )
    return finale


def url_par_defaut(ip):
    """URL de l'interface web a partir de l'adresse de la carte switch."""
    return "http://%s/" % ip


def normaliser_url(url, ip_par_defaut):
    """Complete une saisie partielle ("192.168.0.186", "/status")."""
    url = (url or "").strip()
    if not url:
        return url_par_defaut(ip_par_defaut)
    if url.startswith("/"):
        return url_par_defaut(ip_par_defaut).rstrip("/") + url
    if not urlparse(url).scheme:
        return "http://" + url
    return url


def relever_macs_web(url, login, mot_de_passe, journal):
    """Relevé des adresses MAC affichees par l'interface web."""
    journal("Interface web (%s) : connexion..." % url)
    page = recuperer_page(url, login, mot_de_passe)
    interfaces = extraire_macs(page)
    if not interfaces:
        raise ErreurWeb(
            "Aucune adresse MAC trouvée sur %s : vérifier que l'URL pointe bien "
            "sur la page qui les affiche." % url
        )
    for interface in interfaces:
        journal("Interface web : %s = %s" % (interface["interface"], interface["mac"]))
    return interfaces
