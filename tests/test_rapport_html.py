import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from msa_test.rapport_html import construire_html


def _module(cpu, sda_199, sdb_199, erreur=None):
    def partition(nom, valeur_199):
        return {
            "command_timeout": "7",
            "udma_crc_error_count": valeur_199,
            "ligne_188": "188 Command_Timeout      0x0032 100 100 000 Old_age Always - 7",
            "ligne_199": "199 UDMA_CRC_Error_Count 0x003e 200 200 000 Old_age Always - %s"
            % valeur_199,
            "manquants": [],
        }

    return {
        "cpu": cpu,
        "ip": "192.168.0.%d" % (187 + cpu),
        "erreur": erreur,
        "partitions": {}
        if erreur
        else {
            "/dev/sda1": partition("/dev/sda1", sda_199),
            "/dev/sdb1": partition("/dev/sdb1", sdb_199),
        },
    }


def _campagne(modules, phase="avant"):
    return {
        "phase": phase,
        "date": "2026-08-21T09:00:00",
        "operateur": "J. DURAND",
        "numero_msa": "MSA-1",
        "premiere_ip": "192.168.0.187",
        "nombre_msa": len(modules),
        "modules": modules,
    }


def test_rapport_avant_affiche_les_lignes_smart():
    html = construire_html(_campagne([_module(0, "42", "42")]))
    assert "RELEVÉ AVANT ENREGISTREMENT" in html
    assert "199 UDMA_CRC_Error_Count" in html
    assert "188 Command_Timeout" in html
    assert "CPU0" in html and "192.168.0.187" in html
    # aucune entite HTML ne doit apparaitre en clair
    assert "&amp;mdash;" not in html


def test_rapport_comparaison_conforme():
    avant = _campagne([_module(0, "42", "42")])
    apres = _campagne([_module(0, "42", "42")], phase="apres")
    html = construire_html(avant, apres)
    assert "CONCLUSION : CONFORME" in html
    assert "identique" in html
    assert "ÉCART" not in html


def test_rapport_comparaison_signale_l_ecart_sur_la_bonne_ligne():
    avant = _campagne([_module(0, "42", "42")])
    apres = _campagne([_module(0, "42", "58")], phase="apres")
    html = construire_html(avant, apres)
    assert "CONCLUSION : NON CONFORME" in html
    # un seul ecart : la ligne ID#199 de sdb1
    assert html.count("ÉCART") == 1
    assert "42 &rarr; 58" in html


def test_rapport_module_injoignable():
    avant = _campagne([_module(0, "42", "42")])
    apres = _campagne([_module(0, "42", "42", erreur="SSH KO")], phase="apres")
    html = construire_html(avant, apres)
    assert "NON TESTÉ" in html
    assert "SSH KO" in html


def test_les_valeurs_sont_echappees():
    module = _module(0, "42", "42")
    module["partitions"]["/dev/sda1"]["ligne_199"] = "199 <script>alert(1)</script>"
    html = construire_html(_campagne([module]))
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
