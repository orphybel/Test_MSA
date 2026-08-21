"""Rapport visuel HTML des relevés SMART (lignes ID#188 et ID#199).

Le rapport reprend, pour chaque module MSA, les lignes smartctl telles
qu'elles apparaissent dans la console (Figure 11 de la procedure X301773),
avant et apres enregistrement, avec le verdict de l'etape 24.

Le fichier produit est autonome (CSS integre) : il s'ouvre dans n'importe
quel navigateur et s'imprime directement en annexe du PV de test.
"""

import datetime
import html
import os

from .campagne import PARTITIONS, comparer
from .rapport import _horodatage, dossier_resultats

# (libelle affiche, cle du relevé, cle de la ligne smartctl brute)
ATTRIBUTS_RAPPORT = (
    ("ID#188 &mdash; Command_Timeout", "command_timeout", "ligne_188"),
    ("ID#199 &mdash; UDMA_CRC_Error_Count", "udma_crc_error_count", "ligne_199"),
)

_STYLE = """
:root {
  --encre: #1c2530; --doux: #5b6673; --trait: #d5dbe2; --fond: #f4f6f9;
  --ok: #1a7f4b; --ok-fond: #e6f5ec; --nok: #b3261e; --nok-fond: #fbe9e7;
  --neutre: #8a5a00; --neutre-fond: #fdf4e0;
}
* { box-sizing: border-box; }
body {
  margin: 0; padding: 28px; background: var(--fond); color: var(--encre);
  font-family: "Segoe UI", Roboto, Helvetica, Arial, sans-serif; font-size: 14px;
}
.page { max-width: 1080px; margin: 0 auto; }
header {
  background: #fff; border: 1px solid var(--trait); border-radius: 10px;
  padding: 20px 24px; margin-bottom: 18px;
}
h1 { font-size: 20px; margin: 0 0 4px; }
.sous-titre { color: var(--doux); margin: 0 0 16px; }
.infos { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 10px 24px; }
.infos div { border-left: 3px solid var(--trait); padding-left: 10px; }
.infos .cle { color: var(--doux); font-size: 12px; text-transform: uppercase; letter-spacing: .04em; }
.infos .valeur { font-weight: 600; }
.bandeau {
  border-radius: 10px; padding: 16px 24px; margin-bottom: 18px;
  font-size: 17px; font-weight: 700; border: 1px solid;
}
.bandeau.ok { background: var(--ok-fond); border-color: var(--ok); color: var(--ok); }
.bandeau.nok { background: var(--nok-fond); border-color: var(--nok); color: var(--nok); }
.bandeau.neutre { background: var(--neutre-fond); border-color: var(--neutre); color: var(--neutre); }
.bandeau span { display: block; font-size: 13px; font-weight: 400; margin-top: 4px; }
.module {
  background: #fff; border: 1px solid var(--trait); border-radius: 10px;
  margin-bottom: 16px; overflow: hidden; break-inside: avoid; page-break-inside: avoid;
}
.module > h2 {
  margin: 0; padding: 12px 20px; font-size: 15px; background: #eef1f5;
  border-bottom: 1px solid var(--trait); display: flex; justify-content: space-between;
  align-items: center; gap: 12px;
}
.module h2 .ip { color: var(--doux); font-weight: 500; }
.etiquette {
  font-size: 12px; font-weight: 700; padding: 3px 10px; border-radius: 999px;
  border: 1px solid;
}
.etiquette.ok { background: var(--ok-fond); border-color: var(--ok); color: var(--ok); }
.etiquette.nok { background: var(--nok-fond); border-color: var(--nok); color: var(--nok); }
.etiquette.neutre { background: var(--neutre-fond); border-color: var(--neutre); color: var(--neutre); }
table { width: 100%; border-collapse: collapse; }
th, td { padding: 9px 14px; text-align: left; border-bottom: 1px solid var(--trait); }
th { font-size: 12px; text-transform: uppercase; letter-spacing: .04em; color: var(--doux); font-weight: 600; }
td.valeur { font-family: Consolas, "Courier New", monospace; font-size: 15px; font-weight: 700; }
td.attribut, th.attribut { white-space: nowrap; }
td.sanction { font-weight: 600; }
td.sanction.identique { color: var(--ok); }
tr.ok td.sanction { color: var(--ok); font-weight: 600; }
tr.nok td.sanction { color: var(--nok); font-weight: 600; }
tr.nok { background: var(--nok-fond); }
.console { padding: 14px 20px 18px; }
.console h3 { font-size: 12px; text-transform: uppercase; letter-spacing: .04em; color: var(--doux); margin: 12px 0 6px; }
pre {
  margin: 0 0 8px; padding: 10px 14px; background: #10151c; color: #e6edf3;
  border-radius: 6px; font-family: Consolas, "Courier New", monospace;
  font-size: 12.5px; line-height: 1.65; overflow-x: auto; white-space: pre;
}
pre .cmd { color: #7fd1a0; }
pre .absent { color: #ff9a8c; }
.erreur { margin: 0; padding: 14px 20px; color: var(--nok); font-weight: 600; }
footer { color: var(--doux); font-size: 12px; text-align: center; padding: 10px 0 4px; }
@media print {
  body { background: #fff; padding: 0; font-size: 11.5px; }
  .module, header { border-color: #999; }
  pre { background: #fff; color: #000; border: 1px solid #999; }
}
"""


def _e(valeur):
    """Echappement HTML, avec un tiret pour les valeurs absentes."""
    if valeur is None or valeur == "":
        return "&mdash;"
    return html.escape(str(valeur))


def _bloc_console(releve, libelle_phase, partition):
    """Affiche les deux lignes smartctl comme dans la console du MSA."""
    titre = "%s &mdash; %s" % (html.escape(libelle_phase), html.escape(partition))
    if releve is None:
        return (
            "<h3>%s</h3><pre><span class='absent'>relevé non disponible</span></pre>"
            % titre
        )
    lignes = [
        "<span class='cmd'># smartctl -a %s</span>" % html.escape(partition)
    ]
    for libelle, _, cle_ligne in ATTRIBUTS_RAPPORT:
        ligne = releve.get(cle_ligne)
        if ligne:
            lignes.append(html.escape(ligne))
        else:
            lignes.append(
                "<span class='absent'>%s : ligne absente de la sortie smartctl</span>"
                % libelle.split(" ")[0]
            )
    return "<h3>%s</h3><pre>%s</pre>" % (titre, "\n".join(lignes))


def _sanction_attribut(module_apres, releve_avant, releve_apres, cle):
    """Verdict d'un attribut sur une partition : (texte, conforme)."""
    if module_apres is None or module_apres.get("erreur") or releve_apres is None:
        motif = (module_apres or {}).get("erreur") or "relevé absent"
        return "NON TESTÉ (%s)" % motif, False
    if releve_avant is None:
        return "PAS DE RELEVÉ AVANT", False
    valeur_avant = releve_avant.get(cle)
    valeur_apres = releve_apres.get(cle)
    if valeur_avant is None or valeur_apres is None:
        return "VALEUR NON RELEVÉE", False
    if valeur_avant.strip() == valeur_apres.strip():
        return "identique", True
    return "ÉCART : %s &rarr; %s" % (
        html.escape(valeur_avant),
        html.escape(valeur_apres),
    ), False


def _module_par_cpu(campagne):
    if not campagne:
        return {}
    return {m["cpu"]: m for m in campagne.get("modules", [])}


def construire_html(campagne_avant, campagne_apres=None):
    """Retourne le rapport HTML complet (chaine)."""
    reference = campagne_apres or campagne_avant
    comparaison = campagne_apres is not None and campagne_avant is not None
    if comparaison:
        lignes_comparaison, conforme = comparer(campagne_avant, campagne_apres)
        verdicts = {
            (l["cpu"], l["partition"]): l["verdict"] for l in lignes_comparaison
        }
    else:
        lignes_comparaison, conforme, verdicts = [], None, {}

    avant_par_cpu = _module_par_cpu(campagne_avant)
    apres_par_cpu = _module_par_cpu(campagne_apres)
    cpus = sorted(set(avant_par_cpu) | set(apres_par_cpu))

    parties = [
        "<!doctype html><html lang='fr'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width, initial-scale=1'>",
        "<title>Rapport SMART MSA - %s</title>" % _e(reference.get("date", "")),
        "<style>%s</style></head><body><div class='page'>" % _STYLE,
        "<header><h1>Rapport de test MSA &mdash; relevés SMART ID#188 et ID#199</h1>",
        "<p class='sous-titre'>Procédure X301773 &mdash; RERNG-NVR-2-DISQ / "
        "MP14-NVR-DISQ &mdash; étapes 12 à 15 et 24</p>",
        "<div class='infos'>",
    ]
    infos = [
        ("Date du rapport", datetime.datetime.now().strftime("%d/%m/%Y %H:%M")),
        ("Opérateur", reference.get("operateur")),
        ("Numéro du MSA", reference.get("numero_msa")),
        ("Nombre de MSA testés", reference.get("nombre_msa")),
        ("1ère adresse IP", reference.get("premiere_ip")),
        ("Relevé avant enregistrement", (campagne_avant or {}).get("date")),
        ("Relevé après enregistrement", (campagne_apres or {}).get("date")),
    ]
    for cle, valeur in infos:
        if valeur in (None, ""):
            continue  # ex : pas encore de relevé apres enregistrement
        parties.append(
            "<div><div class='cle'>%s</div><div class='valeur'>%s</div></div>"
            % (html.escape(cle), _e(valeur))
        )
    parties.append("</div></header>")

    if comparaison:
        if conforme:
            parties.append(
                "<div class='bandeau ok'>CONCLUSION : CONFORME"
                "<span>Les RAW_VALUE ID#188 et ID#199 sont identiques avant et "
                "après enregistrement, sur toutes les partitions testées.</span></div>"
            )
        else:
            parties.append(
                "<div class='bandeau nok'>CONCLUSION : NON CONFORME"
                "<span>Au moins une valeur a évolué, ou un module n'a pas pu être "
                "relevé. Voir les lignes en rouge ci-dessous.</span></div>"
            )
    else:
        parties.append(
            "<div class='bandeau neutre'>RELEVÉ AVANT ENREGISTREMENT (étapes 12 à 15)"
            "<span>Valeurs de référence à reporter sur le PV de test. La comparaison "
            "sera établie après les 2 heures d'enregistrement (étape 24).</span></div>"
        )

    for cpu in cpus:
        module_avant = avant_par_cpu.get(cpu)
        module_apres = apres_par_cpu.get(cpu)
        courant = module_apres or module_avant
        erreur = (module_apres or {}).get("erreur") or (module_avant or {}).get("erreur")

        if comparaison:
            verdicts_module = [
                verdicts.get((cpu, partition), "") for partition in PARTITIONS
            ]
            module_ok = verdicts_module and all(
                v.startswith("CONFORME") for v in verdicts_module
            )
            classe = "ok" if module_ok else "nok"
            etiquette = "CONFORME" if module_ok else "NON CONFORME"
        else:
            classe = "nok" if erreur else "neutre"
            etiquette = "NON RELEVÉ" if erreur else "RELEVÉ"

        parties.append("<section class='module'>")
        parties.append(
            "<h2><span>CPU%d <span class='ip'>&mdash; %s</span></span>"
            "<span class='etiquette %s'>%s</span></h2>"
            % (cpu, _e(courant.get("ip")), classe, etiquette)
        )

        if erreur:
            parties.append("<p class='erreur'>%s</p>" % _e(erreur))

        entetes = ["Attribut SMART", "Partition"]
        entetes += (
            ["RAW_VALUE avant", "RAW_VALUE après", "Sanction"]
            if comparaison
            else ["RAW_VALUE relevée"]
        )
        parties.append("<table><thead><tr>")
        parties.extend(
            "<th%s>%s</th>" % (" class='attribut'" if i == 0 else "", e)
            for i, e in enumerate(entetes)
        )
        parties.append("</tr></thead><tbody>")

        for attribut, cle, _ in ATTRIBUTS_RAPPORT:
            for partition in PARTITIONS:
                releve_avant = (module_avant or {}).get("partitions", {}).get(partition)
                releve_apres = (module_apres or {}).get("partitions", {}).get(partition)
                if comparaison:
                    sanction, ligne_ok = _sanction_attribut(
                        module_apres, releve_avant, releve_apres, cle
                    )
                    parties.append(
                        "<tr class='%s'><td class='attribut'>%s</td><td>%s</td>"
                        "<td class='valeur'>%s</td><td class='valeur'>%s</td>"
                        "<td class='sanction%s'>%s</td></tr>"
                        % (
                            "ok" if ligne_ok else "nok",
                            attribut,
                            _e(partition),
                            _e((releve_avant or {}).get(cle)),
                            _e((releve_apres or {}).get(cle)),
                            " identique" if ligne_ok else "",
                            sanction,
                        )
                    )
                else:
                    parties.append(
                        "<tr><td class='attribut'>%s</td><td>%s</td>"
                        "<td class='valeur'>%s</td></tr>"
                        % (attribut, _e(partition), _e((releve_avant or {}).get(cle)))
                    )
        parties.append("</tbody></table>")

        parties.append("<div class='console'>")
        for libelle, module in (
            ("Avant enregistrement", module_avant),
            ("Après enregistrement", module_apres),
        ):
            if module is None:
                continue
            for partition in PARTITIONS:
                parties.append(
                    _bloc_console(
                        module.get("partitions", {}).get(partition), libelle, partition
                    )
                )
        parties.append("</div></section>")

    parties.append(
        "<footer>Rapport généré automatiquement &mdash; à joindre au PV de test "
        "(procédure X301773).</footer>"
    )
    parties.append("</div></body></html>")
    return "".join(parties)


def exporter_html(campagne_avant, campagne_apres=None, racine=None):
    """Ecrit le rapport visuel et retourne son chemin."""
    reference = campagne_apres or campagne_avant
    suffixe = "avant_apres" if campagne_apres is not None else "avant"
    nom = "rapport_%s_%s.html" % (suffixe, _horodatage(reference))
    chemin = os.path.join(dossier_resultats(racine), nom)
    with open(chemin, "w", encoding="utf-8") as fichier:
        fichier.write(construire_html(campagne_avant, campagne_apres))
    return chemin
