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

# Page "Administration : Versions" du NVR ACTIA, qui affiche les adresses MAC
# de chaque module dans un tableau.
CHEMIN_VERSIONS = "/cgi-bin/cgi_fh?URL=SUAdminVersions"

# Intitules des colonnes recherches dans l'en-tete des tableaux.
_COLONNE_MAC = "adresse mac"
_COLONNE_LIBELLE = ("parametre", "paramètre", "module")

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


class _Tableaux(HTMLParser):
    """Extrait les tableaux de la page ainsi que les titres qui les precedent."""

    _TITRES = ("h1", "h2", "h3", "h4", "caption", "legend")

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tableaux = []
        self._pile = []
        self._ligne = None
        self._cellule = None
        self._titre_courant = ""
        self._dans_titre = False
        self._ignore = 0

    # -- ouverture ---------------------------------------------------- #
    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._ignore += 1
        elif tag == "table":
            self._pile.append({"lignes": [], "titre": self._titre_courant})
        elif tag == "tr" and self._pile:
            self._ligne = []
        elif tag in ("td", "th") and self._pile:
            if self._ligne is None:  # cellule hors <tr> : on ouvre une ligne
                self._ligne = []
            self._cellule = []
        elif tag in self._TITRES:
            self._dans_titre = True
            self._titre_courant = ""

    # -- fermeture ---------------------------------------------------- #
    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._ignore = max(0, self._ignore - 1)
        elif tag in ("td", "th"):
            self._fermer_cellule()
        elif tag == "tr":
            self._fermer_ligne()
        elif tag == "table":
            self._fermer_tableau()
        elif tag in self._TITRES:
            self._dans_titre = False

    def handle_data(self, donnees):
        if self._ignore:
            return
        if self._cellule is not None:
            self._cellule.append(donnees)
        elif self._dans_titre:
            self._titre_courant += donnees

    def _fermer_cellule(self):
        if self._cellule is None:
            return
        texte = re.sub(r"\s+", " ", "".join(self._cellule)).strip()
        if self._ligne is not None:
            self._ligne.append(texte)
        self._cellule = None

    def _fermer_ligne(self):
        self._fermer_cellule()
        if self._ligne:
            self._pile[-1]["lignes"].append(self._ligne)
        self._ligne = None

    def _fermer_tableau(self):
        self._fermer_ligne()
        if not self._pile:
            return
        tableau = self._pile.pop()
        lignes = tableau["lignes"]
        # Un tableau reduit a une seule cellule sert d'intitule de section
        # (mise en page du NVR : "NVR", "Caméras intérieures"...).
        if len(lignes) == 1 and len(lignes[0]) == 1 and lignes[0][0]:
            self._titre_courant = lignes[0][0]
            return
        if lignes:
            self.tableaux.append(tableau)

    def close(self):
        super().close()
        while self._pile:
            self._fermer_tableau()


def _index_colonnes(entete):
    """Repere la colonne des adresses MAC et celle du libelle."""
    index_mac = None
    index_libelle = None
    for index, cellule in enumerate(entete):
        normalise = cellule.strip().lower()
        if index_mac is None and _COLONNE_MAC in normalise:
            index_mac = index
        elif index_libelle is None and normalise in _COLONNE_LIBELLE:
            index_libelle = index
    if index_mac is None:
        return None, None
    if index_libelle is None:
        index_libelle = 0 if index_mac != 0 else None
    return index_mac, index_libelle


def extraire_macs_tableaux(page_html):
    """Lit les adresses MAC dans les tableaux qui possedent une colonne dediee.

    C'est la mise en page de la page "Administration : Versions" du NVR :
    une ligne par module, avec les colonnes Parametre, Version logicielle,
    Checksum et Adresse MAC. Lire la colonne evite de confondre l'adresse
    avec le checksum et donne un intitule propre.
    """
    parseur = _Tableaux()
    parseur.feed(page_html)
    parseur.close()

    trouvees = []
    for tableau in parseur.tableaux:
        lignes = tableau["lignes"]
        # Un titre peut aussi occuper la premiere ligne du tableau (cellule
        # unique) : on le retient et on poursuit sur les lignes suivantes.
        titre = tableau["titre"]
        if len(lignes[0]) == 1 and len(lignes) > 1:
            titre = lignes[0][0] or titre
            lignes = lignes[1:]
        if not lignes:
            continue

        index_mac, index_libelle = _index_colonnes(lignes[0])
        if index_mac is None:
            continue
        for ligne in lignes[1:]:
            if index_mac >= len(ligne):
                continue
            mac = normaliser_mac(ligne[index_mac])
            if not mac or not _mac_exploitable(mac):
                continue  # cellule vide, "?" ou adresse inexploitable
            libelle = (
                ligne[index_libelle]
                if index_libelle is not None and index_libelle < len(ligne)
                else ""
            )
            trouvees.append(
                {
                    "interface": _intitule(titre, libelle),
                    "mac": mac,
                }
            )
    return trouvees


def _intitule(titre, libelle):
    titre = (titre or "").strip()
    libelle = (libelle or "").strip()
    if titre and libelle:
        return "%s - %s" % (titre, libelle)
    return libelle or titre or "adresse relevée"


def extraire_macs(page_html):
    """Retourne les adresses MAC de la page, avec leur ligne d'origine.

    Les tableaux comportant une colonne "Adresse MAC" sont lus en priorite :
    l'intitule provient alors de la colonne "Parametre" et deux modules
    portant la meme adresse restent distincts. A defaut, chaque ligne de
    texte contenant une adresse est examinee et les doublons sont ecartes.
    """
    depuis_tableaux = extraire_macs_tableaux(page_html)
    if depuis_tableaux:
        return depuis_tableaux

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
    """URL de la page des versions a partir de l'adresse Controle/Switch."""
    return "http://%s%s" % (ip, CHEMIN_VERSIONS)


def normaliser_url(url, ip_par_defaut):
    """Complete une saisie partielle.

    Saisir la seule adresse de l'equipement suffit : le chemin de la page des
    versions est ajoute. Un chemin explicite est toujours respecte.
    """
    url = (url or "").strip()
    if not url:
        return url_par_defaut(ip_par_defaut)
    if url.startswith("/"):
        return "http://%s%s" % (ip_par_defaut, url)
    if not urlparse(url).scheme:
        url = "http://" + url
    decoupee = urlparse(url)
    if decoupee.path in ("", "/") and not decoupee.query:
        return url.rstrip("/") + CHEMIN_VERSIONS
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
