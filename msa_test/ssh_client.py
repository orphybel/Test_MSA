"""Connexion SSH aux modules MSA et execution des commandes smartctl.

Correspond aux etapes 12 et 13 de la procedure X301773 :
  - etape 12 : connexion a la console SSH du MSA
  - etape 13 : passage en Super Utilisateur (su) puis `smartctl -a /dev/sdX1`

Un shell interactif (PTY) est utilise car la commande `su` refuse de lire
son mot de passe ailleurs que sur un terminal.
"""

import re
import socket
import time
import uuid

import paramiko

DELAI_CONNEXION = 15  # secondes
DELAI_COMMANDE = 90  # secondes (smartctl peut reveiller le disque)
_PROMPT_MDP = re.compile(rb"(?:password|mot de passe|passwd)\s*:", re.IGNORECASE)


class ErreurMSA(Exception):
    """Erreur fonctionnelle remontee a l'operateur (message en clair)."""


class SessionMSA:
    """Session SSH root sur un module MSA."""

    def __init__(self, hote, login, mot_de_passe, mot_de_passe_root=None, port=22):
        self.hote = hote
        self.login = login
        self.mot_de_passe = mot_de_passe
        # Si l'operateur ne renseigne pas de mot de passe root, on reutilise
        # celui du compte SSH (cas le plus frequent sur les bancs de test).
        self.mot_de_passe_root = mot_de_passe_root or mot_de_passe
        self.port = port
        self._client = None
        self._canal = None

    # ------------------------------------------------------------------ #
    # Cycle de vie
    # ------------------------------------------------------------------ #
    def __enter__(self):
        self.ouvrir()
        return self

    def __exit__(self, *_):
        self.fermer()

    def ouvrir(self):
        """Etape 12 : ouverture de la connexion SSH."""
        self._client = paramiko.SSHClient()
        self._client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            self._client.connect(
                hostname=self.hote,
                port=self.port,
                username=self.login,
                password=self.mot_de_passe,
                timeout=DELAI_CONNEXION,
                banner_timeout=DELAI_CONNEXION,
                auth_timeout=DELAI_CONNEXION,
                look_for_keys=False,
                allow_agent=False,
            )
        except paramiko.AuthenticationException:
            raise ErreurMSA(
                "Authentification refusee : verifier le login et le mot de passe."
            )
        except (socket.timeout, socket.error, paramiko.SSHException) as err:
            raise ErreurMSA("Connexion impossible sur %s : %s" % (self.hote, err))

        self._canal = self._client.invoke_shell(term="dumb", width=250, height=60)
        self._canal.settimeout(1.0)
        self._vider(1.5)
        # Prompt neutre et pas de pagination : la sortie devient previsible.
        self._envoyer("export PS1='' ; export TERM=dumb ; stty -echo 2>/dev/null")
        self._vider(1.0)

    def fermer(self):
        for ressource in (self._canal, self._client):
            try:
                if ressource is not None:
                    ressource.close()
            except Exception:
                pass
        self._canal = None
        self._client = None

    # ------------------------------------------------------------------ #
    # Primitives bas niveau
    # ------------------------------------------------------------------ #
    def _envoyer(self, texte):
        self._canal.send(texte + "\n")

    def _vider(self, duree):
        """Consomme et retourne ce qui arrive pendant `duree` secondes."""
        fin = time.time() + duree
        tampon = b""
        while time.time() < fin:
            try:
                if self._canal.recv_ready():
                    tampon += self._canal.recv(65535)
                else:
                    time.sleep(0.05)
            except socket.timeout:
                continue
        return tampon.decode("utf-8", errors="replace")

    def _lire_jusqu_a(self, motif, delai):
        """Lit le canal jusqu'a rencontrer `motif` (bytes ou regex compilee)."""
        fin = time.time() + delai
        tampon = b""
        while time.time() < fin:
            try:
                if self._canal.recv_ready():
                    tampon += self._canal.recv(65535)
                else:
                    time.sleep(0.05)
                    continue
            except socket.timeout:
                continue
            if hasattr(motif, "search"):
                if motif.search(tampon):
                    return tampon.decode("utf-8", errors="replace")
            elif motif in tampon:
                return tampon.decode("utf-8", errors="replace")
            if self._canal.exit_status_ready() and not self._canal.recv_ready():
                break
        raise ErreurMSA(
            "Delai depasse sur %s (aucune reponse attendue du MSA)." % self.hote
        )

    def executer(self, commande, delai=DELAI_COMMANDE):
        """Execute une commande et retourne (sortie, code_retour).

        Des marqueurs uniques encadrent la sortie afin de l'isoler de l'echo
        du terminal et des eventuelles banniere/prompt du MSA.
        """
        jeton = uuid.uuid4().hex[:12]
        debut = "DEBUT_%s" % jeton
        fin_marqueur = "FIN_%s" % jeton
        self._envoyer(
            "echo %s ; %s ; echo %s:$?" % (debut, commande, fin_marqueur)
        )
        brut = self._lire_jusqu_a(("%s:" % fin_marqueur).encode(), delai)

        # L'echo du terminal repete la ligne de commande (qui contient les deux
        # marqueurs) : la vraie sortie commence apres la DERNIERE occurrence du
        # marqueur de debut.
        corps = brut.rsplit(debut, 1)[-1]
        corps, _, queue = corps.partition(fin_marqueur + ":")
        code = queue.strip().split()[0] if queue.strip().split() else ""
        try:
            code_retour = int(code)
        except ValueError:
            code_retour = None
        return corps.strip("\r\n"), code_retour

    # ------------------------------------------------------------------ #
    # Etape 13 : mode Super Utilisateur
    # ------------------------------------------------------------------ #
    def est_root(self):
        """Vrai uniquement si l'UID courant vaut exactement 0.

        La comparaison porte sur la derniere ligne non vide et sur l'egalite
        stricte : un UID comme 1000 ou 1010 ne doit surtout pas etre confondu
        avec l'UID 0, sous peine de sauter le `su` et de lancer smartctl en
        simple utilisateur.
        """
        sortie, _ = self.executer("id -u", delai=20)
        lignes = [ligne.strip() for ligne in sortie.splitlines() if ligne.strip()]
        if not lignes:
            raise ErreurMSA(
                "Impossible de lire l'UID courant sur %s (`id -u` sans reponse)."
                % self.hote
            )
        return lignes[-1] == "0"

    def passer_root(self):
        """Etape 13 : `su` puis saisie des identifiants Super Utilisateur."""
        if self.est_root():
            return "deja root"

        self._envoyer("su")
        try:
            self._lire_jusqu_a(_PROMPT_MDP, 15)
        except ErreurMSA:
            raise ErreurMSA(
                "La commande `su` n'a pas demande de mot de passe sur %s." % self.hote
            )
        self._canal.send(self.mot_de_passe_root + "\n")
        self._vider(1.5)
        self._envoyer("export PS1='' ; stty -echo 2>/dev/null")
        self._vider(0.5)

        if not self.est_root():
            raise ErreurMSA(
                "Passage en Super Utilisateur refuse sur %s : verifier le mot de "
                "passe root." % self.hote
            )
        return "su"

    # ------------------------------------------------------------------ #
    # Etape 13/14 : releve smartctl
    # ------------------------------------------------------------------ #
    def smartctl(self, peripherique):
        sortie, code = self.executer("LC_ALL=C smartctl -a %s" % peripherique)
        if "command not found" in sortie.lower():
            # Le PATH herite du compte SSH n'inclut pas toujours /usr/sbin.
            sortie, code = self.executer(
                "LC_ALL=C /usr/sbin/smartctl -a %s" % peripherique
            )
        if "permission denied" in sortie.lower():
            raise ErreurMSA(
                "smartctl refuse l'acces a %s sur %s : la session n'est pas en "
                "Super Utilisateur." % (peripherique, self.hote)
            )
        # smartctl utilise un code de retour en bitmask : les bits 0 et 1
        # signalent une erreur d'usage/ouverture, les autres bits sont des
        # etats du disque et n'empechent pas la lecture des attributs.
        if code is not None and code & 0b11:
            raise ErreurMSA(
                "smartctl a echoue sur %s (%s) : %s"
                % (peripherique, self.hote, sortie.strip().splitlines()[-1:] or "")
            )
        return sortie
