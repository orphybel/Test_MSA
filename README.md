# TestMSA — automatisation de la procédure X301773 (étapes 12 à 15 et 24)

Application Windows autonome (`TestMSA.exe`) qui automatise les relevés SMART
de la procédure de test **RERNG-NVR-2-DISQ / MP14-NVR-DISQ** (réf. X301773) :

| Étape de la procédure | Automatisée |
|---|---|
| 12 — Connexion SSH à la console du MSA | oui |
| 13 — `su` puis `smartctl -a /dev/sda1` et `/dev/sdb1` | oui |
| 14 — Relevé des RAW_VALUE ID#188 (Command_Timeout) et ID#199 (UDMA_CRC_Error_Count) | oui |
| 15 — Répétition sur chaque module CPU (1 à 6 adresses IP) | oui |
| 24 — Nouveau relevé après enregistrement **et comparaison** avec les valeurs avant | oui |

Les étapes manuelles (clé, formatage, 2 h d'enregistrement, FileZilla, VLC)
restent à la charge de l'opérateur.

## Utilisation

1. Lancer `TestMSA.exe`.
2. Renseigner :
   - **1ʳᵉ adresse IP (CPU0)** — par défaut `192.168.0.187`, modifiable ;
     les modules suivants sont déduits par incrément de 1 (cf. Figure 12 de la
     procédure : CPU0 `.187` → CPU5 `.192`). Les adresses effectivement
     interrogées sont affichées en clair avant lancement.
   - **Nombre de MSA testés** — de 1 à 6.
   - **Login SSH** et **mot de passe** (identifiants du logiciel de
     constitution des bancs de test).
   - **Mot de passe root (su)** — optionnel : laissé vide, le mot de passe SSH
     est réutilisé.
   - *Optionnel* : port SSH, opérateur et numéro de MSA (repris sur le PV).
3. **Bouton 1 — Relevé AVANT enregistrement (étapes 12 à 15)** : l'application
   se connecte à chaque MSA, passe en super-utilisateur, exécute les deux
   `smartctl` et affiche les RAW_VALUE. Le relevé est enregistré
   automatiquement.
4. Dérouler manuellement les étapes 16 à 23 (formatage, RECORD, 2 h
   d'enregistrement, vérification FileZilla/VLC).
5. **Bouton 2 — Relevé APRÈS enregistrement (étape 24)** : nouveau relevé,
   comparaison automatique avec le relevé « avant », verdict CONFORME /
   NON CONFORME par partition.

Le relevé « avant » le plus récent est rechargé automatiquement au démarrage :
l'application peut être fermée pendant les 2 h d'enregistrement.

## Fichiers produits

Créés dans le sous-dossier `resultats_msa\` situé à côté de l'exécutable :

- `campagne_avant_*.json` / `campagne_apres_*.json` — relevés bruts (le JSON
  « avant » sert de référence à l'étape 24) ;
- `releves_*.csv` — tableau des RAW_VALUE (séparateur `;`, ouvrable dans Excel) ;
- `PV_comparaison_*.txt` — synthèse avant/après avec la conclusion, à reporter
  sur le PV de test.

Aucun mot de passe n'est écrit sur disque. Seuls l'adresse IP, le nombre de
MSA, le login, le port et l'opérateur sont mémorisés dans
`preferences_msa.json`.

## Construction de l'exécutable

**En local, sous Windows :**

```bat
build.bat
```

L'exécutable est produit dans `dist\TestMSA.exe` (fichier unique, sans
installation de Python sur le poste de test).

**Via GitHub Actions :** le workflow `.github/workflows/build-windows.yml`
exécute les tests puis construit `TestMSA.exe` sur `windows-latest` à chaque
push. Le binaire est téléchargeable dans l'artefact **TestMSA-exe** de
l'exécution.

## Développement

```bash
pip install -r requirements.txt pytest
python -m pytest -q      # tests du parseur SMART et de la comparaison
python main.py           # lancement de l'interface
```

Organisation du code :

- `msa_test/ssh_client.py` — session SSH, passage `su`, exécution `smartctl` ;
- `msa_test/smart_parser.py` — extraction des RAW_VALUE ID#188 et ID#199 ;
- `msa_test/campagne.py` — parcours des 1 à 6 MSA et comparaison avant/après ;
- `msa_test/rapport.py` — sauvegarde JSON, export CSV, génération du PV ;
- `msa_test/interface.py` — interface graphique Tkinter.
