"""Run business regressions without a bench: python -m payments_processor.tests.run_unit.

Only the framework boundary is stubbed. The same tests run against real Frappe
in the disposable-site v16 smoke suite; this is not an installation test.
"""

import sys
import types
import unittest
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock


class AttrDict(dict):
    __getattr__ = dict.get
    __setattr__ = dict.__setitem__


def module(name, **attributes):
    result = types.ModuleType(name)
    result.__dict__.update(attributes)
    sys.modules[name] = result
    return result


def run():
    try:
        import frappe
    except ImportError:
        frappe = module("frappe", _dict=AttrDict, _=lambda text: text)
        for name in (
            "get_cached_doc",
            "get_hooks",
            "get_all",
            "new_doc",
            "db",
            "flags",
            "qb",
            "log_error",
            "get_traceback",
        ):
            setattr(frappe, name, MagicMock())
        module("erpnext.accounts.utils", get_balance_on=MagicMock())
        module("frappe.core.doctype.role.role", get_info_based_on_role=MagicMock())
        module(
            "frappe.email.doctype.email_template.email_template",
            get_email_template=MagicMock(),
        )

        def getdate(value=None):
            if value is None:
                return date.today()
            return date.fromisoformat(value) if isinstance(value, str) else value

        module(
            "frappe.utils",
            getdate=getdate,
            add_days=lambda day, days: getdate(day) + timedelta(days=days),
            get_timedelta=MagicMock(),
            now_datetime=datetime.now,
        )
        module("pypika", Order=types.SimpleNamespace(asc="asc"))
    suite = unittest.defaultTestLoader.loadTestsFromName(
        "payments_processor.tests.test_automation"
    )
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(run())
