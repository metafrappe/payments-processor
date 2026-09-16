"""Payment decisions with isolated persistence and no external transactions."""

from datetime import date, timedelta
from unittest import TestCase
from unittest.mock import MagicMock, patch

import frappe

from payments_processor.payments_processor.utils import automation
from payments_processor.payments_processor.utils.automation import PaymentsProcessor


class TestPaymentDecisions(TestCase):
    def setUp(self):
        self.today = date(2026, 9, 16)
        self.setting = frappe._dict(
            company="Test Company",
            bank_account="Test Bank",
            disabled=0,
            auto_generate_entries=1,
            auto_submit_entries=0,
            due_date_offset=0,
            group_payments_by_supplier=1,
            limit_payment_to_outstanding=0,
            claim_early_payment_discount=1,
            exclude_foreign_currency_invoices=1,
            automate_on_wednesday=1,
        )
        company = frappe._dict(
            default_currency="USD",
            default_discount_account="Discount",
            cost_center="Main",
        )
        with patch.object(frappe, "get_cached_doc", return_value=company):
            with patch.object(automation, "getdate", return_value=self.today):
                self.processor = PaymentsProcessor(self.setting)
        self.processor.suppliers = {
            "Supplier": frappe._dict(name="Supplier", remaining_balance=100)
        }
        self.processor.draft_payment_invoices = set()
        self.processor.paid_from = "Bank"
        self.processor.get_party_bank_account = MagicMock(return_value=None)
        self.processor.get_contact_person = MagicMock(return_value=None)
        self.addCleanup(patch.stopall)
        patch.object(frappe, "get_hooks", return_value=[]).start()

    def invoice(self, name="PI-1", amount=100, **kwargs):
        return frappe._dict(
            {
                "name": name,
                "supplier": "Supplier",
                "currency": "USD",
                "grand_total": amount,
                "outstanding_amount": amount,
                "total_outstanding_due": amount,
                "total_discount": 0,
                "amount_to_pay": amount,
                "credit_to": "Payable",
                "cost_center": "Main",
                "due_date": self.today,
                **kwargs,
            }
        )

    def process(self, *invoices):
        self.processor.invoices = {row.name: row for row in invoices}
        self.processor.process_auto_generate()
        return self.processor.processed_invoices

    def test_grouped_invoices_create_one_draft(self):
        invoices = [self.invoice(), self.invoice("PI-2")]
        self.process(*invoices)
        pe = MagicMock(name="draft")
        pe.name = "PE-1"
        self.processor.create_payment_entry = MagicMock(return_value=pe)
        with (
            patch.object(frappe, "db", new_callable=MagicMock),
            patch.object(frappe, "flags", frappe._dict()),
        ):
            self.processor.create_payments()
            self.assertIsNone(frappe.flags.initiated_by_payment_processor)
        self.processor.create_payment_entry.assert_called_once_with(
            "Supplier", invoices
        )
        pe.save.assert_called_once()
        pe.submit.assert_not_called()
        self.assertEqual([row.payment_entry for row in invoices], ["PE-1", "PE-1"])

    def test_grouped_submit_requires_all_invoices_to_be_approved(self):
        self.process(self.invoice(auto_submit=1), self.invoice("PI-2", auto_submit=0))
        pe = MagicMock()
        self.processor.create_payment_entry = MagicMock(return_value=pe)
        with (
            patch.object(frappe, "db", new_callable=MagicMock),
            patch.object(frappe, "flags", frappe._dict()),
        ):
            self.processor.create_payments()
        pe.submit.assert_not_called()

    def test_failed_save_rolls_back_only_that_invoice_and_restores_flag(self):
        self.setting.group_payments_by_supplier = 0
        first, second = self.invoice(), self.invoice("PI-2")
        self.process(first, second)
        failed, saved = MagicMock(), MagicMock()
        failed.save.side_effect = ValueError("Mock provider rejected the draft")
        saved.name = "PE-2"
        self.processor.create_payment_entry = MagicMock(side_effect=[failed, saved])
        with (
            patch.object(frappe, "db", new_callable=MagicMock) as db,
            patch.object(frappe, "log_error"),
            patch.object(frappe, "get_traceback", return_value="mock failure"),
            patch.object(
                frappe, "flags", frappe._dict(initiated_by_payment_processor="before")
            ),
        ):
            self.processor.create_payments()
            db.rollback.assert_called_once_with(save_point="payments_processor_entry")
            self.assertEqual(frappe.flags.initiated_by_payment_processor, "before")
        self.assertEqual(self.processor.processed_invoices.valid["Supplier"], [second])
        self.assertEqual(
            self.processor.processed_invoices.invalid["Supplier"][0].reason_code, "3001"
        )
        self.assertEqual(second.payment_entry, "PE-2")

    def test_group_threshold_reports_all_invoices_without_creating_payments(self):
        self.setting.auto_generate_threshold = 150
        result = self.process(self.invoice(), self.invoice("PI-2"))
        self.assertFalse(result.valid)
        self.assertEqual(
            [row.reason_code for row in result.invalid["Supplier"]], ["1006", "1006"]
        )

    def test_rejected_invoice_does_not_consume_supplier_balance(self):
        self.setting.limit_payment_to_outstanding = 1
        result = self.process(self.invoice(on_hold=1), self.invoice("PI-2"))
        self.assertEqual([row.name for row in result.valid["Supplier"]], ["PI-2"])
        self.assertEqual(result.valid["Supplier"][0].amount_to_pay, 100)

    def test_supplier_hold_remains_active_through_release_date(self):
        supplier = frappe._dict(on_hold=1, hold_type="Payments")
        for release_date, blocked in [
            (None, True),
            (self.today + timedelta(days=1), True),
            (self.today, True),
            (self.today - timedelta(days=1), False),
        ]:
            with self.subTest(release_date=release_date):
                supplier.release_date = release_date
                self.assertEqual(
                    bool(self.processor.is_supplier_blocked(supplier)), blocked
                )

    def test_invoice_hold_expires_on_release_date(self):
        for release_date, blocked in [
            (None, True),
            (self.today + timedelta(days=1), True),
            (self.today, False),
            (self.today - timedelta(days=1), False),
        ]:
            with self.subTest(release_date=release_date):
                invoice = self.invoice(on_hold=1, release_date=release_date)
                self.assertEqual(
                    bool(self.processor.is_invoice_blocked(invoice)), blocked
                )

    def test_expired_discount_is_not_claimed(self):
        term = frappe._dict(
            outstanding_amount=100,
            discount_type="Percentage",
            discount=10,
            discount_date=self.today - timedelta(days=1),
        )
        self.processor.apply_discount(term)
        self.assertEqual(term.discount_amount, 0)

    def test_partial_settlement_does_not_claim_full_discount(self):
        self.setting.limit_payment_to_outstanding = 1
        self.processor.suppliers["Supplier"].remaining_balance = 30
        result = self.process(self.invoice(total_discount=10))
        invoice = result.valid["Supplier"][0]
        self.assertEqual((invoice.amount_to_pay, invoice.total_discount), (30, 0))

    def test_foreign_currency_and_credit_note_require_manual_handling(self):
        result = self.process(
            self.invoice(currency="EUR"), self.invoice("PI-2", amount=-100, is_return=1)
        )
        self.assertFalse(result.valid)
        self.assertEqual(
            [row["reason_code"] for row in result.invalid["Supplier"]], ["2002", "2004"]
        )

    def test_existing_draft_is_not_duplicated(self):
        self.processor.draft_payment_invoices = {"PI-1"}
        result = self.process(self.invoice())
        self.assertFalse(result.valid)
        self.assertEqual(result.invalid["Supplier"][0]["reason_code"], "2003")

    def test_disabled_generation_returns_empty_report_and_skips_run(self):
        self.setting.auto_generate_entries = 0
        self.processor.get_invoices = MagicMock()
        self.assertEqual(
            self.processor.process_invoices(), {"valid": {}, "invalid": {}}
        )
        self.processor.run()
        self.processor.get_invoices.assert_not_called()

    def test_disabled_configuration_does_not_run(self):
        self.setting.disabled = 1
        self.processor.process_invoices = MagicMock()
        self.processor.run()
        self.processor.process_invoices.assert_not_called()

    def test_discount_deduction_balances_payable_and_uses_invoice_account(self):
        invoice = self.invoice(amount_to_pay=90, total_discount=10)
        pe = MagicMock()
        with patch.object(frappe, "new_doc", return_value=pe):
            self.processor.create_payment_entry("Supplier", [invoice])
        payload = pe.update.call_args.args[0]
        self.assertEqual((payload["paid_to"], payload["paid_amount"]), ("Payable", 90))
        self.assertEqual(payload["references"][0]["allocated_amount"], 100)
        self.assertEqual(pe.append.call_args.args[1]["amount"], -10)

    def test_payment_term_references_keep_allocation_within_due_terms(self):
        invoice = self.invoice(
            amount_to_pay=50,
            allocate_payment_based_on_payment_terms=1,
            payment_terms=[
                frappe._dict(payment_term="First", outstanding_amount=40),
                frappe._dict(payment_term="Second", outstanding_amount=60),
            ],
        )
        pe = MagicMock()
        with patch.object(frappe, "new_doc", return_value=pe):
            self.processor.create_payment_entry("Supplier", [invoice])
        refs = pe.update.call_args.args[0]["references"]
        self.assertEqual(
            [(row["payment_term"], row["allocated_amount"]) for row in refs],
            [("First", 40), ("Second", 10)],
        )

    def test_term_outstanding_is_not_reduced_by_invoice_payment_twice(self):
        row = self.invoice(
            rounded_total=100,
            outstanding_amount=60,
            allocate_payment_based_on_payment_terms=1,
            term_payment_term="Net 30",
            term_payment_amount=100,
            term_outstanding_amount=60,
            term_due_date=self.today,
            term_discount_date=None,
            term_discount_type=None,
            term_discount=0,
        )
        query = MagicMock()
        for name in ["join", "on", "left_join", "select", "where", "orderby"]:
            getattr(query, name).return_value = query
        query.run.return_value = [row]
        # Frappe v16 exposes qb through LocalProxy, which Mock can infer as
        # awaitable. Database queries here are synchronous.
        with patch.object(frappe, "qb", new_callable=MagicMock) as qb:
            qb.from_.return_value = query
            self.processor.get_invoices()
        self.assertEqual(self.processor.invoices["PI-1"].total_outstanding_due, 60)
