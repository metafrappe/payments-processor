<div align="center">

# Payments Processor for ERPNext

A powerful payments automation extension for ERPNext that streamlines payment operations and provides financial insights.

<br>
</div>

## v16 branch

This fork ports upstream `develop` (`7722e55af9d4d52348d68c14c194ab37966a2e07`)
to Frappe/ERPNext v16. Target validation uses Frappe 16.33.1 and ERPNext 16.34.2.

New configurations are **disabled by default**. Set a processing time and automation
days, review the report and thresholds, then explicitly enable the configuration.
Auto-submit remains off by default. Installing this app does not configure a payment
provider. Submitting a Payment Entry can invoke integrations installed separately.

### Behavior corrected in this branch

- v16 query syntax for aggregates, payment references, and supplier contacts.
- Grouped draft creation, group thresholds, and per-invoice failure rollback.
- Supplier/invoice hold dates and expired early-payment discounts.
- Term-based references, invoice payable accounts, and balanced discount deductions.
- Partial settlement does not claim a full-invoice early-payment discount.
- Every invoice in a group must pass auto-submit checks before the group is submitted.
- Credit notes appear with reason `2004` and require manual reconciliation. Automated
  refund generation is not supported. Foreign-currency invoices remain excluded.
- Grouped invoices with different payable accounts fail explicitly; disable grouping
  to create separate entries. Configuration enablement is unchanged for existing rows.

### Validation

Run the isolated business regressions without a bench:

```sh
python -m payments_processor.tests.run_unit
```

On a **disposable v16 site** with ERPNext and this app installed, enable `allow_tests`
and run the real accounting/controller check:

```sh
bench --site test-site execute payments_processor.tests.v16_smoke.run
bench --site test-site run-tests --app payments_processor
```

The smoke suite creates temporary company, supplier, invoice, and draft payment
records inside a savepoint, verifies a second run cannot duplicate drafts, checks
ERPNext's own payment factory and discount balancing, blocks external HTTP, and
rolls back its fixtures. It expects no enabled Payments Processor configuration.
It does not submit a Payment Entry or contact a payment provider.

## ✨ Features

*Automate and optimize payment workflows*

- **Smart Due Date Calculation** Auto-computes payment deadlines considering terms, early-payment discounts, and grace periods.

- **Bulk Payment Engine** Generate bulk payment entries for multiple invoices in a single click.

- **Automation** Schedule payments, automate reminders, and customize payment workflows.

## 🛠️ Installation

### Prerequisites

Frappe and ERPNext v16, Python 3.14+, Node.js 24+

### Frappe Cloud

Sign up for a [Frappe Cloud](https://frappecloud.com/dashboard/signup?referrer=99df7a8f) free trial, create a new site with Frappe Version-16, and install ERPNext and Payments Processor from the Apps.

### Docker

Use [this guide](https://github.com/frappe/frappe_docker/blob/main/docs/custom-apps.md) to deploy Payments Processor by building your custom image.

<details>
<summary>Sample Apps JSON</summary>

```shell
export APPS_JSON='[
  {
    "url": "https://github.com/frappe/erpnext",
    "branch": "version-16"
  },
  {
    "url": "https://github.com/metafrappe/payments-processor",
    "branch": "version-16"
  }
]'

export APPS_JSON_BASE64=$(echo ${APPS_JSON} | base64 -w 0)
```

</details>

### Manual

Once you've [set up a Frappe site](https://frappeframework.com/docs/v14/user/en/installation/), install app by executing the following commands:

<details>
<summary>Commands</summary>

Download the App using the Bench CLI

```sh
bench get-app https://github.com/metafrappe/payments-processor.git --branch version-16
```

Install the App on your site

```sh
bench --site [site name] install-app payments_processor
```

</details>

## 📚 Documentation

- [Setup Guide](https://github.com/metafrappe/payments-processor/blob/version-16/docs/1_setup_guide.md)
- [Reports](<https://github.com/metafrappe/payments-processor/blob/version-16/docs/2_reports.md>)
- [Customization Guide](https://github.com/metafrappe/payments-processor/blob/version-16/docs/3_customization_guide.md)

## 🤝 Contributing

- [Issue Guidelines](https://github.com/frappe/erpnext/wiki/Issue-Guidelines)
- [Pull Request Requirements](https://github.com/frappe/erpnext/wiki/Contribution-Guidelines)

## 📜 License

[GNU General Public License (v3)](https://github.com/metafrappe/payments-processor/blob/version-16/license.txt)
