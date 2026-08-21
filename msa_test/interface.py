"""Interface graphique de l'automate de test MSA (procedure X301773).

Automatise les etapes 12 a 15 (relevé avant enregistrement) et l'etape 24
(relevé apres enregistrement + comparaison) pour 1 a 6 modules MSA.
"""

import json
import os
import queue
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import __version__, rapport
from .campagne import (
    NB_MSA_MAX,
    PARTITIONS,
    PHASE_APRES,
    PHASE_AVANT,
    comparer,
    executer_campagne,
    liste_ip,
)

FICHIER_PREFS = "preferences_msa.json"
IP_PAR_DEFAUT = "192.168.0.187"


def racine_application():
    """Dossier de l'executable (ou du script) : les rapports y sont ecrits."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.getcwd()


class Application(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Test MSA - Procedure X301773 (etapes 12 a 15 et 24)")
        self.geometry("1080x740")
        self.minsize(940, 640)

        self.racine = racine_application()
        self.file_journal = queue.Queue()
        self.arret = threading.Event()
        self.travail = None
        self.campagne_avant = None
        self.campagne_apres = None

        self._construire_saisie()
        self._construire_actions()
        self._construire_tableau()
        self._construire_journal()

        self._charger_preferences()
        self._charger_avant_existant()
        self.protocol("WM_DELETE_WINDOW", self._fermer)
        self.after(100, self._pomper_journal)

    # ------------------------------------------------------------------ #
    # Construction de l'interface
    # ------------------------------------------------------------------ #
    def _construire_saisie(self):
        cadre = ttk.LabelFrame(self, text="Parametres du banc de test")
        cadre.pack(fill="x", padx=10, pady=(10, 6))

        self.var_ip = tk.StringVar(value=IP_PAR_DEFAUT)
        self.var_nombre = tk.IntVar(value=1)
        self.var_login = tk.StringVar()
        self.var_mdp = tk.StringVar()
        self.var_mdp_root = tk.StringVar()
        self.var_port = tk.IntVar(value=22)
        self.var_operateur = tk.StringVar()
        self.var_numero = tk.StringVar()

        ttk.Label(cadre, text="1ere adresse IP (CPU0) *").grid(
            row=0, column=0, sticky="w", padx=8, pady=6
        )
        ttk.Entry(cadre, textvariable=self.var_ip, width=20).grid(
            row=0, column=1, sticky="w", pady=6
        )

        ttk.Label(cadre, text="Nombre de MSA testés (1 a %d) *" % NB_MSA_MAX).grid(
            row=0, column=2, sticky="w", padx=8
        )
        ttk.Spinbox(
            cadre,
            from_=1,
            to=NB_MSA_MAX,
            textvariable=self.var_nombre,
            width=6,
            command=self._rafraichir_apercu,
        ).grid(row=0, column=3, sticky="w")

        ttk.Label(cadre, text="Port SSH").grid(row=0, column=4, sticky="w", padx=8)
        ttk.Entry(cadre, textvariable=self.var_port, width=6).grid(
            row=0, column=5, sticky="w"
        )

        ttk.Label(cadre, text="Login SSH *").grid(
            row=1, column=0, sticky="w", padx=8, pady=6
        )
        ttk.Entry(cadre, textvariable=self.var_login, width=20).grid(
            row=1, column=1, sticky="w", pady=6
        )

        ttk.Label(cadre, text="Mot de passe *").grid(row=1, column=2, sticky="w", padx=8)
        ttk.Entry(cadre, textvariable=self.var_mdp, width=20, show="*").grid(
            row=1, column=3, sticky="w", columnspan=2
        )

        ttk.Label(cadre, text="Mot de passe root (su)").grid(
            row=2, column=0, sticky="w", padx=8, pady=6
        )
        ttk.Entry(cadre, textvariable=self.var_mdp_root, width=20, show="*").grid(
            row=2, column=1, sticky="w", pady=6
        )
        ttk.Label(
            cadre,
            text="laisser vide si identique au mot de passe SSH",
            foreground="#555555",
        ).grid(row=2, column=2, columnspan=4, sticky="w", padx=8)

        ttk.Label(cadre, text="Operateur (PV)").grid(row=3, column=0, sticky="w", padx=8)
        ttk.Entry(cadre, textvariable=self.var_operateur, width=20).grid(
            row=3, column=1, sticky="w", pady=(0, 8)
        )
        ttk.Label(cadre, text="Numero du MSA (PV)").grid(
            row=3, column=2, sticky="w", padx=8
        )
        ttk.Entry(cadre, textvariable=self.var_numero, width=20).grid(
            row=3, column=3, sticky="w", columnspan=2, pady=(0, 8)
        )

        self.etiquette_apercu = ttk.Label(cadre, text="", foreground="#00693e")
        self.etiquette_apercu.grid(
            row=4, column=0, columnspan=6, sticky="w", padx=8, pady=(0, 8)
        )
        self.var_ip.trace_add("write", lambda *_: self._rafraichir_apercu())
        self.var_nombre.trace_add("write", lambda *_: self._rafraichir_apercu())
        self._rafraichir_apercu()

    def _construire_actions(self):
        cadre = ttk.Frame(self)
        cadre.pack(fill="x", padx=10, pady=4)

        self.bouton_avant = ttk.Button(
            cadre,
            text="1. Relevé AVANT enregistrement (etapes 12 a 15)",
            command=lambda: self._lancer(PHASE_AVANT),
        )
        self.bouton_avant.pack(side="left", padx=(0, 6))

        self.bouton_apres = ttk.Button(
            cadre,
            text="2. Relevé APRES enregistrement (etape 24)",
            command=lambda: self._lancer(PHASE_APRES),
        )
        self.bouton_apres.pack(side="left", padx=6)

        self.bouton_arret = ttk.Button(
            cadre, text="Arreter", command=self._demander_arret, state="disabled"
        )
        self.bouton_arret.pack(side="left", padx=6)

        ttk.Button(
            cadre, text="Charger un relevé AVANT...", command=self._charger_avant_fichier
        ).pack(side="left", padx=6)

        self.etiquette_avant = ttk.Label(cadre, text="Aucun relevé AVANT charge")
        self.etiquette_avant.pack(side="left", padx=12)

    def _construire_tableau(self):
        cadre = ttk.LabelFrame(self, text="Relevés SMART (RAW_VALUE)")
        cadre.pack(fill="both", expand=True, padx=10, pady=6)

        colonnes = (
            "cpu",
            "ip",
            "partition",
            "av188",
            "ap188",
            "av199",
            "ap199",
            "verdict",
        )
        entetes = {
            "cpu": ("CPU", 60),
            "ip": ("Adresse IP", 120),
            "partition": ("Partition", 90),
            "av188": ("ID#188 avant", 110),
            "ap188": ("ID#188 apres", 110),
            "av199": ("ID#199 avant", 110),
            "ap199": ("ID#199 apres", 110),
            "verdict": ("Sanction", 340),
        }
        self.tableau = ttk.Treeview(cadre, columns=colonnes, show="headings", height=12)
        for colonne in colonnes:
            titre, largeur = entetes[colonne]
            self.tableau.heading(colonne, text=titre)
            self.tableau.column(colonne, width=largeur, anchor="w")
        self.tableau.tag_configure("ok", background="#e3f6e8")
        self.tableau.tag_configure("nok", background="#fbe0e0")
        self.tableau.tag_configure("attente", background="#fdf6dd")

        barre = ttk.Scrollbar(cadre, orient="vertical", command=self.tableau.yview)
        self.tableau.configure(yscrollcommand=barre.set)
        self.tableau.pack(side="left", fill="both", expand=True)
        barre.pack(side="right", fill="y")

    def _construire_journal(self):
        cadre = ttk.LabelFrame(self, text="Journal d'execution")
        cadre.pack(fill="both", expand=False, padx=10, pady=(0, 10))
        self.journal = tk.Text(cadre, height=10, wrap="word", state="disabled")
        barre = ttk.Scrollbar(cadre, orient="vertical", command=self.journal.yview)
        self.journal.configure(yscrollcommand=barre.set)
        self.journal.pack(side="left", fill="both", expand=True)
        barre.pack(side="right", fill="y")

        pied = ttk.Frame(self)
        pied.pack(fill="x", padx=10, pady=(0, 8))
        self.etiquette_etat = ttk.Label(pied, text="Pret. Version %s" % __version__)
        self.etiquette_etat.pack(side="left")

    # ------------------------------------------------------------------ #
    # Journal et etat
    # ------------------------------------------------------------------ #
    def _tracer(self, message):
        self.file_journal.put(message)

    def _pomper_journal(self):
        while True:
            try:
                message = self.file_journal.get_nowait()
            except queue.Empty:
                break
            self.journal.configure(state="normal")
            self.journal.insert("end", message + "\n")
            self.journal.see("end")
            self.journal.configure(state="disabled")
        self.after(100, self._pomper_journal)

    def _rafraichir_apercu(self):
        try:
            ips = liste_ip(self.var_ip.get(), int(self.var_nombre.get()))
        except (ValueError, tk.TclError):
            self.etiquette_apercu.configure(
                text="Adresses interrogées : - (parametres incomplets)",
                foreground="#a00000",
            )
            return
        detail = "   ".join(
            "CPU%d = %s" % (index, adresse) for index, adresse in enumerate(ips)
        )
        self.etiquette_apercu.configure(
            text="Adresses interrogées : " + detail, foreground="#00693e"
        )

    # ------------------------------------------------------------------ #
    # Preferences (jamais de mot de passe sur disque)
    # ------------------------------------------------------------------ #
    def _chemin_preferences(self):
        return os.path.join(self.racine, FICHIER_PREFS)

    def _charger_preferences(self):
        try:
            with open(self._chemin_preferences(), "r", encoding="utf-8") as fichier:
                prefs = json.load(fichier)
        except (OSError, ValueError):
            return
        self.var_ip.set(prefs.get("premiere_ip", IP_PAR_DEFAUT))
        self.var_nombre.set(prefs.get("nombre_msa", 1))
        self.var_login.set(prefs.get("login", ""))
        self.var_port.set(prefs.get("port", 22))
        self.var_operateur.set(prefs.get("operateur", ""))

    def _enregistrer_preferences(self):
        prefs = {
            "premiere_ip": self.var_ip.get(),
            "nombre_msa": int(self.var_nombre.get()),
            "login": self.var_login.get(),
            "port": int(self.var_port.get()),
            "operateur": self.var_operateur.get(),
        }
        try:
            with open(self._chemin_preferences(), "w", encoding="utf-8") as fichier:
                json.dump(prefs, fichier, indent=2)
        except OSError:
            pass

    # ------------------------------------------------------------------ #
    # Chargement du relevé "avant"
    # ------------------------------------------------------------------ #
    def _charger_avant_existant(self):
        campagne, chemin = rapport.derniere_campagne_avant(self.racine)
        if campagne is not None:
            self.campagne_avant = campagne
            self._annoncer_avant(chemin)

    def _charger_avant_fichier(self):
        chemin = filedialog.askopenfilename(
            title="Choisir un relevé AVANT enregistrement",
            initialdir=rapport.dossier_resultats(self.racine),
            filetypes=[("Relevé JSON", "*.json"), ("Tous les fichiers", "*.*")],
        )
        if not chemin:
            return
        try:
            campagne = rapport.charger(chemin)
        except (OSError, ValueError) as err:
            messagebox.showerror("Lecture impossible", str(err))
            return
        if campagne.get("phase") != PHASE_AVANT:
            messagebox.showwarning(
                "Phase inattendue",
                "Ce fichier correspond a la phase '%s' et non au relevé AVANT."
                % campagne.get("phase"),
            )
        self.campagne_avant = campagne
        self._annoncer_avant(chemin)
        self._afficher_campagne(campagne, PHASE_AVANT)

    def _annoncer_avant(self, chemin):
        self.etiquette_avant.configure(
            text="Relevé AVANT : %s (%s)"
            % (os.path.basename(chemin), self.campagne_avant.get("date", ""))
        )
        self._tracer("Relevé AVANT charge depuis %s" % chemin)

    # ------------------------------------------------------------------ #
    # Lancement d'une campagne
    # ------------------------------------------------------------------ #
    def _lire_configuration(self, phase):
        ip = self.var_ip.get().strip()
        login = self.var_login.get().strip()
        mdp = self.var_mdp.get()
        if not ip or not login or not mdp:
            raise ValueError(
                "Renseigner la 1ere adresse IP, le login et le mot de passe."
            )
        try:
            nombre = int(self.var_nombre.get())
            port = int(self.var_port.get())
        except (ValueError, tk.TclError):
            raise ValueError("Le nombre de MSA et le port doivent etre numeriques.")
        liste_ip(ip, nombre)  # valide l'adresse et la plage 1..6
        return {
            "phase": phase,
            "premiere_ip": ip,
            "nombre_msa": nombre,
            "login": login,
            "mot_de_passe": mdp,
            "mot_de_passe_root": self.var_mdp_root.get() or None,
            "port": port,
            "operateur": self.var_operateur.get().strip(),
            "numero_msa": self.var_numero.get().strip(),
        }

    def _lancer(self, phase):
        if self.travail is not None and self.travail.is_alive():
            return
        try:
            config = self._lire_configuration(phase)
        except ValueError as err:
            messagebox.showerror("Parametres incomplets", str(err))
            return
        if phase == PHASE_APRES and self.campagne_avant is None:
            messagebox.showerror(
                "Relevé AVANT manquant",
                "L'etape 24 compare les valeurs avec le relevé effectue avant "
                "l'enregistrement. Lancez d'abord le relevé AVANT, ou chargez "
                "le fichier JSON correspondant.",
            )
            return

        self._enregistrer_preferences()
        self._vider_tableau()
        self.arret.clear()
        self._basculer_boutons(actif=False)
        self.etiquette_etat.configure(text="Campagne en cours...")
        self._tracer("")
        self._tracer("=== %s ===" % rapport.libelle_phase(phase))

        self.travail = threading.Thread(
            target=self._executer, args=(config,), daemon=True
        )
        self.travail.start()

    def _executer(self, config):
        try:
            campagne = executer_campagne(
                config,
                journal=self._tracer,
                sur_resultat=lambda module: self.after(
                    0, self._ajouter_module, module, config["phase"]
                ),
                arret=self.arret,
            )
            chemin = rapport.sauvegarder(campagne, self.racine)
            self._tracer("Relevé enregistre : %s" % chemin)
            chemin_csv = rapport.exporter_csv(campagne, self.racine)
            self._tracer("Export CSV : %s" % chemin_csv)
            self.after(0, self._terminer, campagne, chemin)
        except Exception as err:  # remonte proprement dans l'interface
            self._tracer("ERREUR : %s" % err)
            self.after(0, self._echouer, err)

    def _terminer(self, campagne, chemin):
        self._basculer_boutons(actif=True)
        if campagne["phase"] == PHASE_AVANT:
            self.campagne_avant = campagne
            self._annoncer_avant(chemin)
            self.etiquette_etat.configure(
                text="Relevé AVANT termine. Lancer l'enregistrement 2h (etapes 16 a 23)."
            )
            self._afficher_campagne(campagne, PHASE_AVANT)
            return

        self.campagne_apres = campagne
        self._afficher_comparaison(campagne)

    def _echouer(self, err):
        self._basculer_boutons(actif=True)
        self.etiquette_etat.configure(text="Campagne interrompue sur erreur.")
        messagebox.showerror("Erreur", str(err))

    def _demander_arret(self):
        self.arret.set()
        self._tracer("Demande d'arret prise en compte (fin du module en cours).")

    def _basculer_boutons(self, actif):
        etat = "normal" if actif else "disabled"
        self.bouton_avant.configure(state=etat)
        self.bouton_apres.configure(state=etat)
        self.bouton_arret.configure(state="disabled" if actif else "normal")

    # ------------------------------------------------------------------ #
    # Affichage des resultats
    # ------------------------------------------------------------------ #
    def _vider_tableau(self):
        for ligne in self.tableau.get_children():
            self.tableau.delete(ligne)

    def _ajouter_module(self, module, phase):
        """Affiche un module des qu'il est relevé (retour immediat a l'operateur)."""
        for partition in PARTITIONS:
            releve = module["partitions"].get(partition)
            if releve is None:
                valeurs = (
                    "CPU%d" % module["cpu"],
                    module["ip"],
                    partition,
                    "",
                    "",
                    "",
                    "",
                    module.get("erreur") or "non relevé",
                )
                self.tableau.insert("", "end", values=valeurs, tags=("nok",))
                continue
            if phase == PHASE_AVANT:
                valeurs = (
                    "CPU%d" % module["cpu"],
                    module["ip"],
                    partition,
                    releve["command_timeout"],
                    "",
                    releve["udma_crc_error_count"],
                    "",
                    "Relevé - a noter sur le PV",
                )
                self.tableau.insert("", "end", values=valeurs, tags=("attente",))
            else:
                valeurs = (
                    "CPU%d" % module["cpu"],
                    module["ip"],
                    partition,
                    "",
                    releve["command_timeout"],
                    "",
                    releve["udma_crc_error_count"],
                    "comparaison en fin de campagne",
                )
                self.tableau.insert("", "end", values=valeurs, tags=("attente",))

    def _afficher_campagne(self, campagne, phase):
        self._vider_tableau()
        for module in campagne["modules"]:
            self._ajouter_module(module, phase)

    def _afficher_comparaison(self, campagne_apres):
        lignes, conforme = comparer(self.campagne_avant, campagne_apres)
        self._vider_tableau()
        for ligne in lignes:
            tag = "ok" if ligne["verdict"].startswith("CONFORME") else "nok"
            self.tableau.insert(
                "",
                "end",
                values=(
                    "CPU%d" % ligne["cpu"],
                    ligne["ip"],
                    ligne["partition"],
                    ligne["avant_188"] if ligne["avant_188"] is not None else "",
                    ligne["apres_188"] if ligne["apres_188"] is not None else "",
                    ligne["avant_199"] if ligne["avant_199"] is not None else "",
                    ligne["apres_199"] if ligne["apres_199"] is not None else "",
                    ligne["verdict"],
                ),
                tags=(tag,),
            )
        chemin, _ = rapport.exporter_pv(campagne_apres, self.campagne_avant, self.racine)
        self._tracer("PV de comparaison : %s" % chemin)
        if conforme:
            self.etiquette_etat.configure(
                text="Etape 24 : CONFORME - toutes les valeurs sont inchangées."
            )
            messagebox.showinfo(
                "Etape 24 - CONFORME",
                "Les RAW_VALUE ID#188 et ID#199 sont identiques a celles relevées "
                "avant enregistrement.\n\nPV genere :\n%s" % chemin,
            )
        else:
            self.etiquette_etat.configure(
                text="Etape 24 : NON CONFORME - voir les lignes en rouge."
            )
            messagebox.showwarning(
                "Etape 24 - NON CONFORME",
                "Au moins une valeur a evolué ou un module n'a pas pu etre relevé.\n\n"
                "PV genere :\n%s" % chemin,
            )

    def _fermer(self):
        if self.travail is not None and self.travail.is_alive():
            if not messagebox.askyesno(
                "Campagne en cours", "Une campagne est en cours. Quitter quand meme ?"
            ):
                return
            self.arret.set()
        self._enregistrer_preferences()
        self.destroy()


def lancer():
    Application().mainloop()
