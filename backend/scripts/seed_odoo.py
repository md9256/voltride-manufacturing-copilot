"""Populate a fresh Odoo database with the VoltRide Systems demo dataset.

Run from /backend:  python -m scripts.seed_odoo

Idempotent: every record is looked up by a stable business key (product code,
partner ref, order reference) before it is created. Records that already exist
are left untouched, so a second run reports "0 created" and never duplicates
data. We use business keys rather than external IDs (ir.model.data) because
Odoo refuses to create ir.model.data through the external API.

Only Community features are used (Sales, Inventory, Manufacturing, Purchase).
"""

from __future__ import annotations

import sys
from collections import Counter
from datetime import datetime, timedelta, timezone

from app.config import get_settings
from app.odoo.rpc import OdooError, OdooRpc
from scripts import seed_data as data

ODOO_DT = "%Y-%m-%d %H:%M:%S"  # Odoo datetimes are naive UTC strings


def days_ago(days: int, hour: int = 9) -> str:
    dt = datetime.now(timezone.utc).replace(hour=hour, minute=0, second=0, microsecond=0) - timedelta(days=days)
    return dt.strftime(ODOO_DT)


class Seeder:
    def __init__(self, rpc: OdooRpc) -> None:
        self.rpc = rpc
        self.stats: Counter[str] = Counter()
        self.partner_ids: dict[str, int] = {}
        self.workcenter_ids: dict[str, int] = {}
        self.product_ids: dict[str, int] = {}  # code -> product.product id
        self.template_ids: dict[str, int] = {}  # code -> product.template id
        self.bom_ids: dict[str, int] = {}
        self.newly_created_products: set[str] = set()

    # -- helpers ---------------------------------------------------------

    def _find_one(self, model: str, domain: list) -> int | None:
        ids = self.rpc.search_ids(model, domain, limit=1)
        return ids[0] if ids else None

    def _ensure(self, label: str, model: str, domain: list, vals: dict, **create_kwargs) -> tuple[int, bool]:
        """Return (id, created). Creates the record only if `domain` matches nothing."""
        existing = self._find_one(model, domain)
        if existing:
            self.stats[f"{label} existing"] += 1
            return existing, False
        new_id = self.rpc.create(model, vals, **create_kwargs)
        self.stats[f"{label} created"] += 1
        return new_id, True

    # -- steps -----------------------------------------------------------

    def enable_work_orders(self) -> None:
        # Work orders / operations are off by default; BOM operations are
        # silently ignored without this setting.
        if self.rpc.call("res.users", "has_group", ids=[self._uid()], group_ext_id="mrp.group_mrp_routings"):
            print("  work orders: already enabled")
            return
        settings_id = self.rpc.create("res.config.settings", {"group_mrp_routings": True})
        self.rpc.call("res.config.settings", "execute", ids=[settings_id])
        print("  work orders: enabled")

    def _uid(self) -> int:
        login = get_settings().odoo_user
        ids = self.rpc.search_ids("res.users", [["login", "=", login]], limit=1)
        if not ids:
            raise OdooError(f"no Odoo user with login {login!r} (check ODOO_USER)")
        return ids[0]

    def partners(self) -> None:
        for s in data.SUPPLIERS:
            self.partner_ids[s.ref], _ = self._ensure(
                "supplier", "res.partner", [["ref", "=", s.ref]],
                {"name": s.name, "ref": s.ref, "city": s.city, "is_company": True, "supplier_rank": 1},
            )
        for c in data.CUSTOMERS:
            self.partner_ids[c.ref], _ = self._ensure(
                "customer", "res.partner", [["ref", "=", c.ref]],
                {"name": c.name, "ref": c.ref, "city": c.city, "is_company": True, "customer_rank": 1},
            )

    def work_centers(self) -> None:
        for wc in data.WORK_CENTERS:
            self.workcenter_ids[wc.code], _ = self._ensure(
                "work center", "mrp.workcenter", [["code", "=", wc.code]],
                {"name": wc.name, "code": wc.code, "costs_hour": wc.cost_per_hour},
            )

    def products(self) -> None:
        # No per-product routes: in Odoo 20 "Buy" and "Manufacture" are
        # warehouse-level routes (not product-selectable). Odoo picks between
        # them from whether the product has a supplier or a BOM.
        base = {"type": "consu", "is_storable": True}

        for c in data.COMPONENTS:
            vals = base | {
                "name": c.name, "default_code": c.code, "standard_price": c.cost,
                "sale_ok": False, "purchase_ok": True,
                "seller_ids": [[0, 0, {
                    "partner_id": self.partner_ids[c.supplier], "price": c.cost,
                    "delay": c.lead_days, "min_qty": 1,
                }]],
            }
            self._ensure_product(c.code, vals)

        for m in data.MANUFACTURED:
            is_kit = m.sale_price > 0
            vals = base | {
                "name": m.name, "default_code": m.code, "list_price": m.sale_price,
                "sale_ok": is_kit, "purchase_ok": False,
            }
            self._ensure_product(m.code, vals)

    def _ensure_product(self, code: str, vals: dict) -> None:
        tmpl_id, created = self._ensure("product", "product.template", [["default_code", "=", code]], vals)
        self.template_ids[code] = tmpl_id
        variant = self.rpc.call("product.template", "read", ids=[tmpl_id], fields=["product_variant_id"])
        self.product_ids[code] = variant[0]["product_variant_id"][0]
        if created:
            self.newly_created_products.add(code)

    def boms(self) -> None:
        for m in data.MANUFACTURED:
            vals = {
                "product_tmpl_id": self.template_ids[m.code],
                "product_qty": 1,
                "type": "normal",
                "code": f"SEED-{m.code}",
                "bom_line_ids": [
                    [0, 0, {"product_id": self.product_ids[code], "product_qty": qty}] for code, qty in m.lines.items()
                ],
                "operation_ids": [
                    [0, 0, {
                        "name": op.name, "workcenter_id": self.workcenter_ids[op.workcenter],
                        "time_mode": "manual", "time_cycle_manual": op.minutes, "sequence": (i + 1) * 10,
                    }]
                    for i, op in enumerate(m.operations)
                ],
            }
            self.bom_ids[m.code], _ = self._ensure(
                "BOM", "mrp.bom", [["code", "=", f"SEED-{m.code}"]], vals
            )

    def stock(self) -> None:
        """Set opening stock, but only for products created in this run.

        Re-running must not reset quantities that manufacturing orders have
        since consumed or produced.
        """
        stock_location = self.rpc.search_read("stock.warehouse", [], ["lot_stock_id"], limit=1)[0]["lot_stock_id"][0]
        quantities = {c.code: c.on_hand for c in data.COMPONENTS} | {m.code: m.on_hand for m in data.MANUFACTURED}
        quant_ids = []
        for code, qty in quantities.items():
            if code not in self.newly_created_products or qty <= 0:
                continue
            # Quants can only be created in "inventory mode", the same path as
            # a physical inventory count in the UI.
            quant_ids.append(self.rpc.create(
                "stock.quant",
                {"product_id": self.product_ids[code], "location_id": stock_location, "inventory_quantity": qty},
                context={"inventory_mode": True},
            ))
        if quant_ids:
            self.rpc.call("stock.quant", "action_apply_inventory", ids=quant_ids, context={"inventory_mode": True})
        self.stats["stock count applied"] += len(quant_ids)

    def reorder_rules(self) -> None:
        for c in data.COMPONENTS:
            self._ensure(
                "reorder rule", "stock.warehouse.orderpoint", [["product_id", "=", self.product_ids[c.code]]],
                # Manual trigger: Odoo shows the rule in the replenishment report
                # but never auto-creates purchase orders from it.
                {"product_id": self.product_ids[c.code], "product_min_qty": c.min_qty,
                 "product_max_qty": c.max_qty, "trigger": "manual"},
            )

    def purchase_orders(self) -> None:
        cost = {c.code: c.cost for c in data.COMPONENTS}
        for po in data.PURCHASE_ORDERS:
            po_id, created = self._ensure(
                "purchase order", "purchase.order", [["partner_ref", "=", po.ref]],
                {
                    "partner_id": self.partner_ids[po.supplier], "partner_ref": po.ref,
                    "date_order": days_ago(po.days_ago),
                    "order_line": [
                        [0, 0, {"product_id": self.product_ids[code], "product_qty": qty, "price_unit": cost[code]}]
                        for code, qty in po.lines.items()
                    ],
                },
            )
            if created and po.state == "purchase":
                self.rpc.call("purchase.order", "button_confirm", ids=[po_id])

    def sale_orders(self) -> None:
        price = {m.code: m.sale_price for m in data.MANUFACTURED}
        for so in data.SALE_ORDERS:
            date_order = days_ago(so.days_ago)
            so_id, created = self._ensure(
                "sale order", "sale.order", [["client_order_ref", "=", so.ref]],
                {
                    "partner_id": self.partner_ids[so.customer], "client_order_ref": so.ref,
                    "date_order": date_order,
                    "order_line": [
                        [0, 0, {"product_id": self.product_ids[code], "product_uom_qty": qty, "price_unit": price[code]}]
                        for code, qty in so.lines.items()
                    ],
                },
            )
            if not created:
                continue
            if so.state == "sale":
                self.rpc.call("sale.order", "action_confirm", ids=[so_id])
                # Confirming stamps date_order with "now"; restore the historical
                # date so the orders-over-time chart has a real spread.
                self.rpc.write("sale.order", [so_id], {"date_order": date_order})
            elif so.state == "cancel":
                self.rpc.call("sale.order", "action_cancel", ids=[so_id])

    MO_STATE_RANK = {"draft": 0, "confirmed": 1, "progress": 2, "to_close": 3, "done": 4}

    def manufacturing_orders(self) -> None:
        """Create each MO and advance it to its target state.

        Unlike other records, MOs are advanced even if they already exist: the
        step compares current and target state, so it is idempotent and also
        resumes cleanly if a previous run stopped half-way.
        """
        for mo in data.MANUFACTURING_ORDERS:
            mo_id, _ = self._ensure(
                "manufacturing order", "mrp.production", [["origin", "=", mo.ref]],
                {
                    "product_id": self.product_ids[mo.product], "product_qty": mo.qty,
                    "bom_id": self.bom_ids[mo.product], "origin": mo.ref,
                    "date_start": days_ago(mo.days_ago, hour=8),
                },
            )
            target = self.MO_STATE_RANK[mo.state]
            if self._mo_state(mo_id) == "draft" and target >= self.MO_STATE_RANK["confirmed"]:
                self.rpc.call("mrp.production", "action_confirm", ids=[mo_id])
            if self.MO_STATE_RANK[self._mo_state(mo_id)] < target:
                if mo.state == "progress":
                    # Finish the first work order only. We avoid button_start:
                    # on Odoo Online the Enterprise mrp_workorder module requires
                    # an HR employee to start one, which Community does not.
                    self._finish_workorders(mo_id, mo, limit=1)
                elif mo.state == "done":
                    finished = self._finish_workorders(mo_id, mo)
                    self.rpc.write("mrp.production", [mo_id], {"qty_producing": mo.qty})
                    result = self.rpc.call("mrp.production", "button_mark_done", ids=[mo_id])
                    if isinstance(result, dict) and result.get("res_model"):
                        print(f"  note: {mo.ref} mark-done opened wizard {result['res_model']}")
                    self.rpc.write("mrp.production", [mo_id], {"date_finished": finished.strftime(ODOO_DT)})
                self.stats["manufacturing order advanced"] += 1

            state = self._mo_state(mo_id)
            if state != mo.state:
                print(f"  warning: {mo.ref} is in state {state!r}, expected {mo.state!r}")

    def _mo_state(self, mo_id: int) -> str:
        return self.rpc.call("mrp.production", "read", ids=[mo_id], fields=["state"])[0]["state"]

    def _finish_workorders(self, mo_id: int, mo: data.ManufacturingOrder, limit: int | None = None) -> datetime:
        """Finish work orders with historical dates and actual durations; returns the end time."""
        workorders = self.rpc.search_read(
            "mrp.workorder", [["production_id", "=", mo_id], ["state", "not in", ["done", "cancel"]]],
            ["id", "duration_expected"], order="id",
        )
        start = datetime.strptime(days_ago(mo.days_ago, hour=8), ODOO_DT)
        for wo in workorders[:limit]:
            minutes = round(wo["duration_expected"] * mo.actual_factor, 1)
            end = start + timedelta(minutes=minutes)
            # Writing `duration` makes Odoo log a matching time entry, which is
            # what the planned-vs-actual comparison reads later.
            self.rpc.write("mrp.workorder", [wo["id"]], {
                "duration": minutes, "date_start": start.strftime(ODOO_DT), "date_finished": end.strftime(ODOO_DT),
            })
            self.rpc.call("mrp.workorder", "button_finish", ids=[wo["id"]])
            # button_finish stamps date_finished with "now"; restore history.
            self.rpc.write("mrp.workorder", [wo["id"]], {"date_finished": end.strftime(ODOO_DT)})
            start = end + timedelta(minutes=30)
        return start

    def run(self) -> None:
        steps = [
            ("Settings", self.enable_work_orders),
            ("Partners", self.partners),
            ("Work centers", self.work_centers),
            ("Products", self.products),
            ("Bills of materials", self.boms),
            ("Opening stock", self.stock),
            ("Reorder rules", self.reorder_rules),
            ("Purchase orders", self.purchase_orders),
            ("Sale orders", self.sale_orders),
            ("Manufacturing orders", self.manufacturing_orders),
        ]
        for title, step in steps:
            print(f"{title}...")
            step()


def main() -> int:
    s = get_settings()
    if not (s.odoo_url and s.odoo_db and s.odoo_api_key):
        print("ODOO_URL, ODOO_DB and ODOO_API_KEY must be set (see .env.example)")
        return 2
    print(f"Seeding {s.odoo_url} (db={s.odoo_db})")
    seeder = Seeder(OdooRpc(s.odoo_url, s.odoo_db, s.odoo_api_key, timeout_s=60))
    try:
        seeder.run()
    except OdooError as exc:
        print(f"\nFAILED: {exc}")
        return 1
    finally:
        print("\nSummary:")
        for key in sorted(seeder.stats):
            print(f"  {key}: {seeder.stats[key]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
