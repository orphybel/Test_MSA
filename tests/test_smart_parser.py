import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from msa_test.smart_parser import SmartIntrouvable, parser_attributs, releve_partition

SORTIE = """
smartctl 7.2 2020-12-30 r5155 [x86_64-linux] (local build)
=== START OF READ SMART DATA SECTION ===
ID# ATTRIBUTE_NAME          FLAG     VALUE WORST THRESH TYPE      UPDATED  WHEN_FAILED RAW_VALUE
  1 Raw_Read_Error_Rate     0x002f   100   100   000    Pre-fail  Always       -       0
188 Command_Timeout         0x0032   100   100   000    Old_age   Always       -       0 0 0
190 Airflow_Temperature_Cel 0x0022   070   055   045    Old_age   Always       -       30 (Min/Max 20/45)
199 UDMA_CRC_Error_Count    0x003e   200   200   000    Old_age   Always       -       12
"""


def test_extraction_des_deux_attributs():
    attributs = parser_attributs(SORTIE)
    assert attributs[188] == "0 0 0"
    assert attributs[199] == "12"


def test_releve_complet():
    releve = releve_partition(SORTIE)
    assert releve["command_timeout"] == "0 0 0"
    assert releve["udma_crc_error_count"] == "12"
    assert releve["manquants"] == []


def test_attribut_absent_signale():
    sortie = "\n".join(
        ligne for ligne in SORTIE.splitlines() if not ligne.startswith("199")
    )
    releve = releve_partition(sortie)
    assert releve["udma_crc_error_count"] is None
    assert any("199" in m for m in releve["manquants"])


@pytest.mark.parametrize(
    "sortie",
    ["", "   ", "bash: smartctl: command not found", "smartctl: Permission denied"],
)
def test_sorties_invalides(sortie):
    with pytest.raises(SmartIntrouvable):
        releve_partition(sortie)
