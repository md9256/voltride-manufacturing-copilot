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
from datetime import UTC, datetime, timedelta

from app.config import get_settings
from app.odoo.rpc import OdooError, OdooRpc
from scripts import seed_data as data

ODOO_DT = "%Y-%m-%d %H:%M:%S"  # Odoo datetimes are naive UTC strings


def days_ago(days: int, hour: int = 9) -> str:
    dt = datetime.now(UTC).replace(hour=hour, minute=0, second=0, microsecond=0) - timedelta(days=days)
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
                "supplier",
                "res.partner",
                [["ref", "=", s.ref]],
                {"name": s.name, "ref": s.ref, "city": s.city, "is_company": True, "supplier_rank": 1},
            )
        for c in data.CUSTOMERS:
            self.partner_ids[c.ref], _ = self._ensure(
                "customer",
                "res.partner",
                [["ref", "=", c.ref]],
                {"name": c.name, "ref": c.ref, "city": c.city, "is_company": True, "customer_rank": 1},
            )

    def work_centers(self) -> None:
        for wc in data.WORK_CENTERS:
            self.workcenter_ids[wc.code], _ = self._ensure(
                "work center",
                "mrp.workcenter",
                [["code", "=", wc.code]],
                {"name": wc.name, "code": wc.code, "costs_hour": wc.cost_per_hour},
            )

    def products(self) -> None:
        # No per-product routes: in Odoo 20 "Buy" and "Manufacture" are
        # warehouse-level routes (not product-selectable). Odoo picks between
        # them from whether the product has a supplier or a BOM.
        base = {"type": "consu", "is_storable": True}

        for c in data.COMPONENTS:
            vals = base | {
                "name": c.name,
                "default_code": c.code,
                "standard_price": c.cost,
                "sale_ok": False,
                "purchase_ok": True,
                "seller_ids": [
                    [
                        0,
                        0,
                        {
                            "partner_id": self.partner_ids[c.supplier],
                            "price": c.cost,
                            "delay": c.lead_days,
                            "min_qty": 1,
                        },
                    ]
                ],
            }
            self._ensure_product(c.code, vals)

        for m in data.MANUFACTURED:
            is_kit = m.sale_price > 0
            vals = base | {
                "name": m.name,
                "default_code": m.code,
                "list_price": m.sale_price,
                "sale_ok": is_kit,
                "purchase_ok": False,
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
                    [
                        0,
                        0,
                        {
                            "name": op.name,
                            "workcenter_id": self.workcenter_ids[op.workcenter],
                            "time_mode": "manual",
                            "time_cycle_manual": op.minutes,
                            "sequence": (i + 1) * 10,
                        },
                    ]
                    for i, op in enumerate(m.operations)
                ],
            }
            self.bom_ids[m.code], _ = self._ensure("BOM", "mrp.bom", [["code", "=", f"SEED-{m.code}"]], vals)

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
            quant_ids.append(
                self.rpc.create(
                    "stock.quant",
                    {"product_id": self.product_ids[code], "location_id": stock_location, "inventory_quantity": qty},
                    context={"inventory_mode": True},
                )
            )
        if quant_ids:
            self.rpc.call("stock.quant", "action_apply_inventory", ids=quant_ids, context={"inventory_mode": True})
        self.stats["stock count applied"] += len(quant_ids)

    def reorder_rules(self) -> None:
        for c in data.COMPONENTS:
            self._ensure(
                "reorder rule",
                "stock.warehouse.orderpoint",
                [["product_id", "=", self.product_ids[c.code]]],
                # Manual trigger: Odoo shows the rule in the replenishment report
                # but never auto-creates purchase orders from it.
                {
                    "product_id": self.product_ids[c.code],
                    "product_min_qty": c.min_qty,
                    "product_max_qty": c.max_qty,
                    "trigger": "manual",
                },
            )

    def purchase_orders(self) -> None:
        cost = {c.code: c.cost for c in data.COMPONENTS}
        for po in data.PURCHASE_ORDERS:
            po_id, created = self._ensure(
                "purchase order",
                "purchase.order",
                [["partner_ref", "=", po.ref]],
                {
                    "partner_id": self.partner_ids[po.supplier],
                    "partner_ref": po.ref,
                    "date_order": days_ago(po.days_ago),
                    **({"date_planned": days_ago(-po.receipt_in_days, hour=1)} if po.receipt_in_days else {}),
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
                "sale order",
                "sale.order",
                [["client_order_ref", "=", so.ref]],
                {
                    "partner_id": self.partner_ids[so.customer],
                    "client_order_ref": so.ref,
                    "date_order": date_order,
                    **({"commitment_date": days_ago(-so.commitment_in_days, hour=2)} if so.commitment_in_days else {}),
                    "order_line": [
                        [
                            0,
                            0,
                            {"product_id": self.product_ids[code], "product_uom_qty": qty, "price_unit": price[code]},
                        ]
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
                "manufacturing order",
                "mrp.production",
                [["origin", "=", mo.ref]],
                {
                    "product_id": self.product_ids[mo.product],
                    "product_qty": mo.qty,
                    "bom_id": self.bom_ids[mo.product],
                    "origin": mo.ref,
                    "date_start": days_ago(mo.days_ago, hour=mo.hour_utc),
                    **({"date_deadline": days_ago(-mo.deadline_in_days, hour=10)} if mo.deadline_in_days else {}),
                },
            )
            target = self.MO_STATE_RANK[mo.state]
            if self._mo_state(mo_id) == "draft" and target >= self.MO_STATE_RANK["confirmed"]:
                if mo.stock_neutral:
                    # Add exactly what this order will reserve and consume, so
                    # today's free stock (and the shortages built on it) is unchanged.
                    for code, qty in self._direct_components(mo).items():
                        self._adjust_stock(self.product_ids[code], qty)
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
                    self._consume_components(mo_id)
                    result = self.rpc.call("mrp.production", "button_mark_done", ids=[mo_id])
                    if isinstance(result, dict) and result.get("res_model"):
                        print(f"  note: {mo.ref} mark-done opened wizard {result['res_model']}")
                    if self._mo_state(mo_id) == "done":
                        self.rpc.write("mrp.production", [mo_id], {"date_finished": finished.strftime(ODOO_DT)})
                        if mo.stock_neutral:
                            # Only once the output really exists; doing this after a
                            # mark-done that stopped half-way removed stock twice.
                            self._adjust_stock(self.product_ids[mo.product], -mo.qty)  # output "used since"
                self.stats["manufacturing order advanced"] += 1

            state = self._mo_state(mo_id)
            if state != mo.state:
                print(f"  warning: {mo.ref} is in state {state!r}, expected {mo.state!r}")

    def _consume_components(self, mo_id: int) -> None:
        """Record every component move as consumed at its BOM quantity.

        In the UI, setting "quantity producing" fills these in; over the API
        it does not, and Odoo then stops mark-done with a "consumption
        warning" whenever a component was not fully reserved (reservation
        order between competing orders is not under the seed's control).
        Only component moves: also marking the output move makes Odoo cancel
        the order (verified on Odoo 20).
        """
        moves = self.rpc.search_read(
            "stock.move",
            [["raw_material_production_id", "=", mo_id], ["state", "not in", ["done", "cancel"]]],
            ["product_uom_qty"],
        )
        for move in moves:
            self.rpc.write("stock.move", [move["id"]], {"quantity": move["product_uom_qty"], "picked": True})

    def _direct_components(self, mo: data.ManufacturingOrder) -> dict[str, float]:
        lines = next(m.lines for m in data.MANUFACTURED if m.code == mo.product)
        return {code: qty * mo.qty for code, qty in lines.items()}

    def _adjust_stock(self, product_id: int, delta: float) -> None:
        """Change on-hand stock by `delta` through an inventory adjustment."""
        location = self._stock_location()
        ctx = {"inventory_mode": True}
        quants = self.rpc.search_read(
            "stock.quant", [["product_id", "=", product_id], ["location_id", "=", location]], ["quantity"], limit=1
        )
        if quants:
            quant_id = quants[0]["id"]
            self.rpc.write(
                "stock.quant", [quant_id], {"inventory_quantity": quants[0]["quantity"] + delta}, context=ctx
            )
        else:
            quant_id = self.rpc.create(
                "stock.quant",
                {"product_id": product_id, "location_id": location, "inventory_quantity": delta},
                context=ctx,
            )
        self.rpc.call("stock.quant", "action_apply_inventory", ids=[quant_id], context=ctx)
        self.stats["stock adjustment"] += 1

    def _stock_location(self) -> int:
        if not hasattr(self, "_location_id"):
            wh = self.rpc.search_read("stock.warehouse", [], ["lot_stock_id"], limit=1)
            self._location_id = wh[0]["lot_stock_id"][0]
        return self._location_id

    def plan_manufacturing_orders(self) -> None:
        """Schedule open MOs with Odoo's own planner (the MO "Plan" button).

        It books each work order onto its work center's calendar, which gives
        the shop-floor timeline real planned slots. Already planned MOs are
        left alone, so re-running is a no-op.
        """
        open_mos = self.rpc.search_read(
            "mrp.production",
            [
                ["origin", "in", [m.ref for m in data.MANUFACTURING_ORDERS]],
                ["state", "in", ["confirmed", "progress"]],
                ["is_planned", "=", False],
            ],
            ["name"],
        )
        for mo in open_mos:
            self.rpc.call("mrp.production", "button_plan", ids=[mo["id"]])
            self.stats["manufacturing order planned"] += 1

    ACTIVITY_TYPES = {
        "todo": "mail_activity_data_todo",
        "call": "mail_activity_data_call",
        "email": "mail_activity_data_email",
    }
    ORDER_KEYS = {"sale.order": "client_order_ref", "purchase.order": "partner_ref", "mrp.production": "origin"}

    def activities(self) -> None:
        """To-dos with due dates on orders (Odoo activities, part of the base system)."""
        uid = self._uid()
        for act in data.ACTIVITIES:
            record = self._find_one(act.model, [[self.ORDER_KEYS[act.model], "=", act.ref]])
            if record is None:
                print(f"  warning: {act.model} {act.ref} not found; skipping activity")
                continue
            model_id = self._find_one("ir.model", [["model", "=", act.model]])
            self._ensure(
                "activity",
                "mail.activity",
                [["res_model", "=", act.model], ["res_id", "=", record], ["summary", "=", act.summary]],
                {
                    "res_model_id": model_id,
                    "res_id": record,
                    "activity_type_id": self._xmlid("mail", self.ACTIVITY_TYPES[act.kind]),
                    "summary": act.summary,
                    "note": f"<p>{act.note}</p>" if act.note else False,
                    "date_deadline": days_ago(-act.due_in_days)[:10],
                    "user_id": uid,
                },
            )

    def _xmlid(self, module: str, name: str) -> int:
        rows = self.rpc.search_read(
            "ir.model.data", [["module", "=", module], ["name", "=", name]], ["res_id"], limit=1
        )
        if not rows:
            raise OdooError(f"external id {module}.{name} not found")
        return rows[0]["res_id"]

    def _mo_state(self, mo_id: int) -> str:
        return self.rpc.call("mrp.production", "read", ids=[mo_id], fields=["state"])[0]["state"]

    def _finish_workorders(self, mo_id: int, mo: data.ManufacturingOrder, limit: int | None = None) -> datetime:
        """Finish work orders with historical dates and actual durations; returns the end time."""
        workorders = self.rpc.search_read(
            "mrp.workorder",
            [["production_id", "=", mo_id], ["state", "not in", ["done", "cancel"]]],
            ["id", "duration_expected"],
            order="id",
        )
        start = datetime.strptime(days_ago(mo.days_ago, hour=mo.hour_utc), ODOO_DT)
        if not workorders:
            # Resuming an order whose work orders were finished on an earlier run.
            done = self.rpc.search_read(
                "mrp.workorder", [["production_id", "=", mo_id], ["state", "=", "done"]], ["date_finished"]
            )
            ends = [datetime.strptime(w["date_finished"], ODOO_DT) for w in done if w["date_finished"]]
            return max(ends, default=start)
        for wo in workorders[:limit]:
            minutes = round(wo["duration_expected"] * mo.actual_factor, 1)
            end = start + timedelta(minutes=minutes)
            # Writing `duration` makes Odoo log a matching time entry, which is
            # what the planned-vs-actual comparison reads later.
            self.rpc.write(
                "mrp.workorder",
                [wo["id"]],
                {
                    "duration": minutes,
                    "date_start": start.strftime(ODOO_DT),
                    "date_finished": end.strftime(ODOO_DT),
                },
            )
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
            ("Scheduling", self.plan_manufacturing_orders),
            ("Activities", self.activities),
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
