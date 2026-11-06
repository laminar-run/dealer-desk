# DealerDesk 98 - Fake Dealership Management System (DMS)

A fully functional, deliberately old-school **Windows 98-style desktop** Dealership Management
System built as an RPA testing target - the dealership-domain sibling of `fake-emr` (MedChart Pro 98).
Tkinter UI, single SQLite database, idempotent seed data, and a DB-driven "chaos engine" that injects
realistic enterprise-app friction (fake freezes, error dialogs, session timeouts, BSOD, etc.).

## Run

```bash
pip install -r requirements.txt          # desktop and web dependencies
python main.py                           # launches the Win98 desktop app
python create_shortcut.py                # (Windows) puts "DealerDesk 98.lnk" on the Desktop
```

The database `dms.db` is created and seeded automatically on first launch (idempotent - safe to re-run).

## Logins

| Username | Password | Role |
|----------|----------|------|
| `admin`    | `admin`    | admin |
| `jmiller`  | `password` | salesperson |
| `rdavis`   | `password` | advisor |

## Modules (left navigation)

- **Home** - retro dashboard (clock, marquee, module status, quick stats)
- **Customers** - customer master; detail window has tabs: Profile / Vehicles / Repair Orders / Deals / Appointments
- **Inventory** - vehicles on the lot (In Stock / Sold / Customer-Owned)
- **Deals** - sales transactions (primary sales flow)
- **Repair Orders** - service write-ups using the "3 C's": Concern / Cause / Correction (+ Recommendations) - primary service flow
- **Appointments** - service & sales appointments
- **Reports** - canned dealership reports
- **Settings** - chaos engine configuration (off by default)

## Domain mapping (vs. fake-emr / MedChart)

| MedChart (EMR) | DealerDesk (DMS) |
|----------------|------------------|
| Patient | Customer |
| MRN | Customer # |
| Encounter (SOAP note) | Repair Order (3 C's) |
| Provider | Service Advisor / Salesperson |
| Medications / Diagnoses | Vehicles / Deals |
| Appointment | Appointment (Service/Sales) |

## Chaos engine

Off by default (`chaos_settings.master_enabled = 0`). Toggle scenarios in the **Settings** panel
or with the "Fire Now" buttons. Scenario keys match `chaos/engine.py` `SCENARIO_MAP`
(the `wrong_patient` key is reused for the wrong-customer warning).

## Stable selectors for RPA

Every interactive widget has a stable Tk `name=` (queryable via uiautomation/pywinauto by AutomationId/Name).
See `config.json -> use_cases` for full step-by-step flows. Highlights:

- Login: `username`, `password`, `btn_login`
- Nav: `btn_nav_home`, `btn_nav_customers`, `btn_nav_inventory`, `btn_nav_deals`, `btn_nav_repair_orders`, `btn_nav_appointments`, `btn_nav_reports`, `btn_nav_settings`
- Customers: `customer_search`, `btn_search_customers`, `customer_tree`, `btn_open_customer`, `btn_add_customer`
- Repair Order form: `btn_new_ro`, `ro_customer`/`btn_ro_lookup_customer`, `ro_vehicle`/`btn_ro_lookup_vehicle`, `ro_date`, `ro_type`, `ro_advisor`, `ro_status`, `ro_mileage`, `ro_concern`, `ro_cause`, `ro_correction`, `ro_recommendations`, `btn_save_ro`
- Deal form: `btn_new_deal`, `btn_deal_lookup_customer`, `btn_deal_lookup_vehicle`, `deal_date`, `deal_salesperson`, `deal_type`, `deal_sale_price`, `deal_status`, `btn_save_deal`
- Appointment form: `btn_new_appt`, `btn_appt_lookup_customer`, `appt_datetime`, `appt_dept`, `appt_advisor`, `appt_reason`, `appt_status`, `btn_save_appt`
- Inventory: `inventory_search`, `inventory_status_filter`, `btn_search_inventory`, `inventory_tree`

The Windows desktop also starts a session-local chaos API for ordinary RPA job scripts.
See [the local API contract](docs/local-chaos-api.md) for discovery, actions, security, and timeout limits.
