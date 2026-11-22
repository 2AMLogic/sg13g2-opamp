"""Standing circuit benches select the typical passive sections of DR-0012."""

import json
import unittest
from pathlib import Path

SIM = Path(__file__).resolve().parents[1]
MODELS = "libs.tech/ngspice/models"


class PassiveSections(unittest.TestCase):
    def test_process_bundles_select_typical_passives(self):
        requests = sorted(SIM.glob("*/klt/*.request.json"))
        self.assertTrue(requests)
        for path in requests:
            request = json.loads(path.read_text())
            for process in request["corners"]["process"]:
                with self.subTest(request=path.name, process=process["name"]):
                    self.assertEqual(
                        process["sections"],
                        [
                            process["name"],
                            {"lib": f"{MODELS}/cornerCAP.lib", "section": "cap_typ"},
                            {"lib": f"{MODELS}/cornerRES.lib", "section": "res_typ"},
                        ],
                    )

    def test_dut_templates_select_typical_passives(self):
        models = f"@@PDK_ROOT@@/@@PDK@@/{MODELS}"
        for path in sorted(SIM.glob("*/testbench/*.spice.tmpl")):
            lines = path.read_text().splitlines()
            if '.include "@@DUT_NETLIST@@"' in lines:
                with self.subTest(template=path.name):
                    passive_cards = [
                        line
                        for line in lines
                        if line.startswith(".lib ")
                        and ("cornerCAP.lib" in line or "cornerRES.lib" in line)
                    ]
                    self.assertEqual(
                        passive_cards,
                        [
                            f'.lib "{models}/cornerCAP.lib" cap_typ',
                            f'.lib "{models}/cornerRES.lib" res_typ',
                        ],
                    )
