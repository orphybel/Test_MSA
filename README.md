# TestMSA — automatisation de la procédure X301773 (étapes 12 à 15 et 24)

Application Windows autonome (`TestMSA.exe`) qui automatise les relevés SMART
de la procédure de test **RERNG-NVR-2-DISQ / MP14-NVR-DISQ** (réf. X301773) :

| Étape de la procédure | Automatisée |
|---|---|
| 12 — Connexion SSH à la console du MSA | oui |
| 13 — `su` (attente de l'invite de mot de passe) puis `smartctl -a /dev/sda1` et `/dev/sdb1` | oui |
| 14 — Relevé des RAW_VALUE ID#188 (Command_Timeout) et ID#199 (UDMA_CRC_Error_Count) | oui |
| 15 — Répétition sur chaque module MSA (1 à 6 adresses IP) | oui |
| 24 — Nouveau relevé après enregistrement **et comparaison** avec les valeurs avant | oui |

Les étapes manuelles (clé, formatage, 2 h d'enregistrement, FileZilla, VLC)
restent à la charge de l'opérateur.

## Utilisation

1. Lancer `TestMSA.exe`.
2. Renseigner :
   - **Adresse IP de la carte Contrôle/Switch** — c'est la seule adresse à
     saisir. Les modules MSA sont déduits par incrément de 1 : MSA0 = adresse
     de la carte + 1, MSA1 = +2, etc. (carte `.186` → MSA0 `.187` … MSA5
     `.192`). Les adresses effectivement interrogées sont affichées en clair
     avant lancement.
   - **Nombre de MSA testés** — de 1 à 6.
   - **Login SSH** et **mot de passe** (identifiants du logiciel de
     constitution des bancs de test).
   - **Mot de passe root (su)** — optionnel : laissé vide, le mot de passe SSH
     est réutilisé.
   - **N° de série du NVR** — repris dans le **nom de tous les fichiers
     produits**, dans l'en-tête du rapport, dans le PV et dans le CSV.
   - *Optionnel* : port SSH, nom de l'opérateur (repris sur le PV),
     identifiants de la carte Contrôle/Switch (relevé des adresses MAC) et
     compte REST (relevé de la capacité, pré-rempli).
3. **Bouton 1 — Relevé AVANT enregistrement (étapes 12 à 15)** : l'application
   se connecte à chaque MSA, attend l'invite de mot de passe du `su`, passe en
   super-utilisateur, exécute les deux `smartctl` et affiche les RAW_VALUE. Le
   relevé est enregistré et le **rapport visuel** s'ouvre dans le navigateur.
4. Dérouler manuellement les étapes 16 à 23 (formatage, RECORD, 2 h
   d'enregistrement, vérification FileZilla/VLC).
5. **Bouton 2 — Relevé APRÈS enregistrement (étape 24)** : nouveau relevé,
   comparaison automatique avec le relevé « avant », verdict CONFORME /
   NON CONFORME par attribut et par partition, et rapport visuel avant/après.

Le bouton **Ouvrir le rapport visuel** réaffiche à tout moment le dernier
rapport généré.

## Capacité de stockage

Le bouton **Capacité de stockage** envoie à chaque module CPU enregistreur la
requête de la procédure — celle passée manuellement sous INSOMNIA :

```
GET http://<adresse du MSA>:8080/storage/status
```

L'interface REST des modules demande une authentification : les champs
**Login REST** et **Mot de passe REST** sont pré-remplis avec le compte
`rest` / `rest1234` et les identifiants sont envoyés dès la première requête.

La valeur `capacity` de la réponse JSON est relevée et affichée en Ko, avec ses
équivalents en Mo et Go (exemple de la procédure : `3 755 205 Ko`), ainsi que
le détail des `hdd_status_entries` renvoyées. Le résultat est écrit dans
`capacite_stockage_<n° de série>_<horodatage>.txt`, ouvert en fin de relevé.

Le seuil d'acceptation est **capacité ≥ 3 700 000 Ko** : chaque module est
marqué `SUFFISANTE` ou `INSUFFISANTE`. Le champ **Capacité mini (Ko)** permet
de le modifier ; vidé, il n'entraîne aucune sanction et les capacités sont
seulement relevées. Un module injoignable est reporté en `NON RELEVE` sans
interrompre les autres.

## Relevé des adresses MAC

Le bouton **Relever les adresses MAC** interroge, indépendamment des relevés
SMART :

- la **carte Contrôle/Switch**, à l'adresse saisie ;
- chacun des modules MSA, en SSH avec les identifiants MSA.

Trois sources sont proposées pour la carte Contrôle/Switch :

| Source | Usage |
|---|---|
| **Interface web** (par défaut) | Les identifiants **web** du NVR suffisent — c'est le cas le plus courant, le mot de passe SSH de cette carte n'étant pas toujours connu. |
| **SSH** | Si vous disposez du compte console de la carte. |
| **Ne pas relever** | Seuls les modules MSA sont interrogés. |

En mode interface web, l'application ouvre la page **Administration :
Versions** du NVR — par défaut
`http://<adresse Contrôle/Switch>/cgi-bin/cgi_fh?URL=SUAdminVersions`. Saisir
la seule adresse de l'équipement suffit, le chemin est complété ; un chemin
explicite est toujours respecté.

L'authentification se fait en **HTTP Basic** ou via le **formulaire de
connexion** de la page — champs identifiant/mot de passe et jetons anti-rejeu
cachés sont détectés automatiquement.

L'extraction lit la colonne **Adresse MAC** des tableaux de la page et prend
la colonne **Paramètre** comme intitulé, précédé du titre de section
(`NVR - Module CPU Enregistreur 0`, `Caméras intérieures - CamInt1_S1`). Le
checksum affiché sur la même ligne n'est donc jamais confondu avec une
adresse, les cellules à `?` sont ignorées, et deux modules partageant la même
adresse restent deux lignes distinctes. Si la page ne comporte pas de colonne
dédiée, l'application retombe sur une recherche ligne par ligne.

Si l'authentification de votre interface web ne peut pas être automatisée, le
bouton **MAC depuis une page enregistrée...** extrait les adresses d'une page
sauvegardée depuis le navigateur (Ctrl+S) ou d'un simple copier-coller dans un
fichier texte.

Toutes les interfaces réseau de chaque équipement sont listées avec leur
adresse MAC dans un fichier texte
(`adresses_MAC_<n° de série>_<horodatage>.txt`), ouvert en fin de relevé.

Le fichier commence par un **récapitulatif d'une ligne par adresse**, les
équipements triés par adresse IP (carte Contrôle/Switch `.186`, puis MSA0
`.187`, MSA1 `.188`…), suivi du détail par équipement dans le même ordre. Un
équipement injoignable apparaît en `NON RELEVE`, sans interrompre le relevé
des autres.

La lecture des adresses MAC ne nécessite pas les droits root : aucun `su`
n'est effectué. Si le login de la carte control switch est laissé vide, seuls
les modules MSA sont relevés et le fichier le mentionne.

## Rapport visuel

Le rapport HTML montre, pour **chaque équipement** :

- un tableau des RAW_VALUE **ID#188** et **ID#199** par partition
  (avant / après / sanction) ;
- les **lignes `smartctl` complètes**, reprises telles quelles de la console du
  MSA (comme en Figure 11 de la procédure), avant et après enregistrement ;
- une pastille CONFORME / NON CONFORME par module et un bandeau de conclusion
  global ;
- un **bandeau d'alerte listant les RAW_VALUE non nulles**, et une pastille
  `≠ 0` sur chaque valeur concernée.

### Valeurs non nulles

La procédure ne sanctionne que l'**égalité** des valeurs avant/après
(étape 24) : une RAW_VALUE à 12 qui reste à 12 est donc CONFORME au sens du PV.
Comme ces compteurs traduisent des erreurs déjà enregistrées par le disque,
l'application les signale sans modifier ce verdict — bandeau d'alerte en tête
de rapport, pastille `≠ 0` sur la valeur, ligne surlignée dans le tableau de
l'interface, et section dédiée dans le PV texte.

Un module relevé avant l'enregistrement mais injoignable à l'étape 24 conserve
les alertes de son relevé « avant ».

Il est autonome (aucune ressource externe), s'ouvre dans n'importe quel
navigateur et s'imprime directement en annexe du PV de test.

Le relevé « avant » le plus récent est rechargé automatiquement au démarrage :
l'application peut être fermée pendant les 2 h d'enregistrement.

## Fichiers produits

Créés dans le sous-dossier `resultats_msa\` situé à côté de l'exécutable. Son
chemin complet est affiché en bas de la fenêtre, et le bouton **Ouvrir le
dossier des résultats** l'ouvre dans l'explorateur. Si l'exécutable est placé
dans un dossier protégé (Program Files, partage réseau en lecture seule),
l'application se rabat sur `Documents\TestMSA\` — le chemin affiché indique
toujours l'emplacement réellement utilisé. Le
n° de série du NVR est inséré dans chaque nom de fichier (par exemple
`rapport_avant_apres_NVR-MP14-2026-0087_2026-08-21_11-22-47.html`) ; les
caractères refusés par Windows sont remplacés et le nom reste valide si aucun
numéro n'est saisi :

- `campagne_avant_*.json` / `campagne_apres_*.json` — relevés bruts (le JSON
  « avant » sert de référence à l'étape 24) ;
- `releves_*.csv` — tableau des RAW_VALUE (séparateur `;`, ouvrable dans Excel) ;
- `PV_comparaison_*.txt` — synthèse avant/après avec la conclusion, à reporter
  sur le PV de test ;
- `adresses_MAC_*.txt` — relevé des adresses MAC (voir ci-dessus) ;
- `capacite_stockage_*.txt` — capacité de chaque module CPU enregistreur ;
- `rapport_avant_*.html` / `rapport_avant_apres_*.html` — rapport visuel
  (voir ci-dessus), ouvert automatiquement en fin de campagne.

Aucun mot de passe n'est écrit sur disque. Seuls l'adresse IP, le nombre de
MSA, le login, le port, l'opérateur et le n° de série du NVR sont mémorisés
dans `preferences_msa.json` — le numéro est ainsi conservé entre le relevé
« avant » et le relevé « après », deux heures plus tard.

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

- `msa_test/ssh_client.py` — session SSH, passage `su`, exécution `smartctl`,
  lecture des adresses MAC ;
- `msa_test/smart_parser.py` — extraction des RAW_VALUE ID#188 et ID#199 ;
- `msa_test/campagne.py` — parcours des 1 à 6 MSA, comparaison avant/après et
  détection des valeurs non nulles ;
- `msa_test/web_mac.py` — relevé des adresses MAC via l'interface web du NVR ;
- `msa_test/stockage.py` — requête `:8080/storage/status` et capacité relevée ;
- `msa_test/rapport.py` — sauvegarde JSON, export CSV, génération du PV ;
- `msa_test/rapport_html.py` — rapport visuel HTML des lignes ID#188 / ID#199 ;
- `msa_test/interface.py` — interface graphique Tkinter.
