"""Disposable-site integration check; never enables the scheduler or pays a provider."""

import io
import unittest
from unittest.mock import patch

import frappe
from frappe.utils import getdate

from payments_processor.payments_processor.utils.automation import PaymentsProcessor
from payments_processor.tests import test_automation


def run(app="payments_processor"):
    if app != "payments_processor" or not frappe.conf.allow_tests:
        raise RuntimeError("Run only on a disposable site with allow_tests enabled")

    suite = unittest.defaultTestLoader.loadTestsFromModule(test_automation)
    output = io.StringIO()
    result = unittest.TextTestRunner(stream=output, verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise AssertionError(output.getvalue())

    # Refuse all outbound HTTP even if another installed app has a document hook.
    with patch(
        "requests.sessions.Session.request",
        side_effect=AssertionError("External HTTP forbidden"),
    ) as network:
        check_disabled_installation()
        frappe.db.savepoint("payments_processor_smoke")
        company_name = None
        try:
            company, supplier, bank_account, invoices = make_fixtures()
            company_name = company.name
            settings = frappe._dict(
                company=company.name,
                bank_account=bank_account.name,
                disabled=0,
                auto_generate_entries=1,
                auto_submit_entries=0,
                due_date_offset=0,
                group_payments_by_supplier=1,
                limit_payment_to_outstanding=1,
                claim_early_payment_discount=0,
                exclude_foreign_currency_invoices=1,
                **{f"automate_on_{getdate().strftime('%A').lower()}": 1},
            )
            processor = PaymentsProcessor(settings)
            processed = processor.process_invoices()
            assert len(processed.valid[supplier.name]) == 2, processed
            with patch.object(frappe, "log_error", side_effect=raise_logged_error):
                processor.create_payments()
            entries = {
                invoice.payment_entry for invoice in processed.valid[supplier.name]
            }
            assert len(entries) == 1 and None not in entries, processed
            payment = frappe.get_doc("Payment Entry", entries.pop())
            assert payment.docstatus == 0
            assert payment.is_auto_generated == 1
            assert payment.paid_amount == 200
            assert payment.difference_amount == 0
            assert payment.paid_to == invoices[0].credit_to
            assert {row.reference_name for row in payment.references} == {
                invoice.name for invoice in invoices
            }
            assert all(row.payment_term for row in payment.references)

            # Actual v16 child join and aggregate: no duplicate draft on the next pass.
            repeated = PaymentsProcessor(settings).process_invoices()
            assert not repeated.valid, repeated
            assert {row["reason_code"] for row in repeated.invalid[supplier.name]} == {
                "2003"
            }

            # Use ERPNext's own factory as a contract check for our account mapping.
            from erpnext.accounts.doctype.payment_entry.payment_entry import (
                get_payment_entry,
            )

            native = get_payment_entry(
                "Purchase Invoice",
                invoices[0].name,
                bank_account=company.default_cash_account,
            )
            assert native.paid_to == payment.paid_to
            assert native.payment_type == payment.payment_type

            # Discount must still balance after real v16 controller validation.
            payment.delete()
            processor = PaymentsProcessor(settings)
            selected = processor.process_invoices().valid[supplier.name]
            selected[0].total_discount = 10
            selected[0].amount_to_pay -= 10
            discount_payment = processor.create_payment_entry(supplier.name, selected)
            discount_payment.insert()
            assert discount_payment.docstatus == 0
            assert discount_payment.difference_amount == 0
            assert discount_payment.paid_amount == 190
            assert discount_payment.deductions[0].amount == -10
            network.assert_not_called()
        finally:
            frappe.db.rollback(save_point="payments_processor_smoke")
            if company_name:
                frappe.clear_document_cache("Company", company_name)
            frappe.clear_cache()
            frappe.cache.delete_value("fiscal_years")
    return {
        "app": app,
        "unit_tests": result.testsRun,
        "integration": "passed",
        "draft_total": 200,
        "discount_draft_total": 190,
        "external_http_calls": 0,
        "fixtures": "rolled back",
    }


def raise_logged_error(title=None, message=None, **kwargs):
    raise AssertionError(f"{title}\n{message}")


def check_disabled_installation():
    meta = frappe.get_meta("Payments Processor Configuration")
    assert str(meta.get_field("disabled").default) == "1"
    assert str(meta.get_field("auto_submit_entries").default) == "0"
    assert frappe.get_meta("Supplier").has_field("disable_auto_generate_payment_entry")
    assert frappe.get_meta("Payment Entry").has_field("is_auto_generated")
    assert frappe.db.exists("Role", "Auto Payments Manager")
    assert frappe.db.exists("Email Template", "Auto Payment Email")
    assert not frappe.get_all(
        "Payments Processor Configuration", filters={"disabled": 0}
    )
    # No configuration means no payment factory/provider activity.
    from payments_processor.payments_processor.utils.automation import (
        autocreate_payment_entry,
    )

    with patch.object(PaymentsProcessor, "run") as process:
        autocreate_payment_entry()
        process.assert_not_called()


def make_fixtures():
    suffix = frappe.generate_hash(length=8)
    today = getdate()
    company = frappe.get_doc(
        {
            "doctype": "Company",
            "company_name": f"Payment Test {suffix}",
            "abbr": f"P{suffix}",
            "country": "United States",
            "default_currency": "USD",
            "chart_of_accounts": "Standard",
        }
    ).insert()
    company.reload()
    company.default_discount_account = company.default_expense_account
    company.save()
    frappe.get_doc(
        {
            "doctype": "Fiscal Year",
            "year": f"Payment FY {suffix}",
            "year_start_date": today.replace(month=1, day=1),
            "year_end_date": today.replace(month=12, day=31),
            "companies": [{"company": company.name}],
        }
    ).insert()
    supplier = frappe.get_doc(
        {
            "doctype": "Supplier",
            "supplier_name": f"Payment Supplier {suffix}",
            "supplier_group": "All Supplier Groups",
            "supplier_type": "Company",
        }
    ).insert()
    item = frappe.get_doc(
        {
            "doctype": "Item",
            "item_code": f"Payment Service {suffix}",
            "item_name": f"Payment Service {suffix}",
            "item_group": "All Item Groups",
            "stock_uom": "Nos",
            "is_stock_item": 0,
        }
    ).insert()
    bank = frappe.get_doc(
        {"doctype": "Bank", "bank_name": f"Payment Bank {suffix}"}
    ).insert()
    bank_account = frappe.get_doc(
        {
            "doctype": "Bank Account",
            "account_name": f"Payment Account {suffix}",
            "bank": bank.name,
            "company": company.name,
            "account": company.default_cash_account,
            "is_company_account": 1,
        }
    ).insert()
    term = frappe.get_doc(
        {
            "doctype": "Payment Term",
            "payment_term_name": f"Payment Term {suffix}",
            "invoice_portion": 100,
            "due_date_based_on": "Day(s) after invoice date",
            "credit_days": 0,
        }
    ).insert()
    template = frappe.get_doc(
        {
            "doctype": "Payment Terms Template",
            "template_name": f"Payment Template {suffix}",
            "allocate_payment_based_on_payment_terms": 1,
            "terms": [
                {
                    "payment_term": term.name,
                    "invoice_portion": 100,
                    "due_date_based_on": "Day(s) after invoice date",
                    "credit_days": 0,
                }
            ],
        }
    ).insert()
    invoices = []
    for index in range(2):
        invoice = frappe.get_doc(
            {
                "doctype": "Purchase Invoice",
                "supplier": supplier.name,
                "company": company.name,
                "posting_date": today,
                "due_date": today,
                "bill_no": f"PP-{suffix}-{index}",
                "bill_date": today,
                "currency": "USD",
                "conversion_rate": 1,
                "credit_to": company.default_payable_account,
                "cost_center": company.cost_center,
                "payment_terms_template": template.name,
                "items": [
                    {
                        "item_code": item.name,
                        "qty": 1,
                        "rate": 100,
                        "expense_account": company.default_expense_account,
                        "cost_center": company.cost_center,
                    }
                ],
            }
        ).insert()
        invoice.submit()
        invoices.append(invoice)
    return company, supplier, bank_account, invoices
