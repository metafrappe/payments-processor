# Copyright (c) 2024, Resilient Tech and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase


class TestPaymentsProcessorConfiguration(IntegrationTestCase):
    def test_automation_requires_explicit_enablement(self):
        doc = frappe.new_doc("Payments Processor Configuration")
        self.assertEqual(doc.disabled, 1)
        self.assertEqual(doc.auto_submit_entries, 0)
