"""Test HCL loading helpers"""

import concurrent.futures
import io
from unittest import TestCase

from terrawrap.utils.hcl import hcl2_load, hcl2_loads

EXPECTED_SOURCE = "../../modules/aws/thing/v1"
MODULE_TF = f'module "m" {{\n  source = "{EXPECTED_SOURCE}"\n  name   = "x"\n}}\n'
# Distinct documents matter: identical text does not trigger the python-hcl2 race
VARIED_TF = [
    f'locals {{\n  v{i} = "${{var.x}}-{i}"\n  tags = {{ a = "b{i}" }}\n}}\n'
    f'variable "x{i}" {{\n  type = string\n  default = "d{i}"\n}}\n' + MODULE_TF
    for i in range(20)
]
WORKERS = 50  # matches the thread pools in module.py and tf_variables.py


def _source(parsed: dict) -> str:
    return parsed["module"][0]["m"]["source"]


class TestHcl(TestCase):
    """Test HCL loading helpers"""

    def test_load_strips_quotes(self):
        self.assertEqual(EXPECTED_SOURCE, _source(hcl2_load(io.StringIO(MODULE_TF))))
        self.assertEqual(EXPECTED_SOURCE, _source(hcl2_loads(MODULE_TF)))

    def test_concurrent_loads_strip_quotes(self):
        """python-hcl2 8.1.3+ intermittently returns quoted strings when parsed from many threads"""
        with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as executor:
            sources = list(executor.map(lambda text: _source(hcl2_loads(text)), VARIED_TF * 100))

        self.assertEqual([EXPECTED_SOURCE] * len(sources), sources)

    def test_load_strips_quotes_after_concurrent_loads(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as executor:
            list(executor.map(hcl2_loads, VARIED_TF * 100))

        self.assertEqual(EXPECTED_SOURCE, _source(hcl2_loads(MODULE_TF)))
