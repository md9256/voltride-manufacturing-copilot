"""Export the live Odoo data to the JSON snapshot used by ODOO_MODE=demo.

Run from /backend:  python -m scripts.export_snapshot [--out PATH]

Uses the live OdooClient itself, so the snapshot contains exactly what the
app would read from Odoo. Re-run before the trial database expires, and after
changing the seed data or the client interface.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from app.config import get_settings
from app.odoo.live import LiveOdooClient
from app.odoo.rpc import OdooError, OdooRpc
from app.odoo.snapshot import DEFAULT_SNAPSHOT_PATH, Snapshot


def export(client: LiveOdooClient) -> Snapshot:
    return Snapshot(
        exported_at=datetime.now(UTC),
        server_version=client.server_version(),
        currency=client.company_currency(),
        sale_orders=client.list_sale_orders(),
        manufacturing_orders=client.list_manufacturing_orders(),
        stock_levels=client.list_stock_levels(),
        products=client.list_products(),
        boms=client.list_boms(),
        work_centers=client.list_work_centers(),
        work_orders=client.list_work_orders(),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_SNAPSHOT_PATH)
    args = parser.parse_args()

    s = get_settings()
    if not (s.odoo_url and s.odoo_db and s.odoo_api_key):
        print("ODOO_URL, ODOO_DB and ODOO_API_KEY must be set (see .env.example)")
        return 2
    client = LiveOdooClient(OdooRpc(s.odoo_url, s.odoo_db, s.odoo_api_key, timeout_s=60))
    try:
        snapshot = export(client)
    except OdooError as exc:
        print(f"FAILED: {exc}")
        return 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(snapshot.model_dump_json(indent=1) + "\n", encoding="utf-8")
    print(
        f"Wrote {args.out}: {len(snapshot.products)} products, {len(snapshot.boms)} BOMs, "
        f"{len(snapshot.sale_orders)} sale orders, {len(snapshot.manufacturing_orders)} MOs, "
        f"{len(snapshot.work_orders)} work orders"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
