# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Pure Python helpers for data products.

* ``TTLParser``           — TTL parsing / component extraction (rdflib)
* ``DataProductProcessor``— headless product listing/loading (storage-aware)
* ``analyzer``            — pure resource-format sniffing/parsing helpers
"""

from backend.data_products.ttl_parser import TTLParser
from backend.data_products.processor import DataProductProcessor
from backend.data_products import analyzer

__all__ = ["TTLParser", "DataProductProcessor", "analyzer"]
