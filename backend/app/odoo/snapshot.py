"""The demo-mode snapshot: the OdooClient's own records, saved as JSON.

The snapshot schema *is* the client interface: export_snapshot.py stores the
exact records the live client returns, and the demo client loads them through
the same Pydantic models. If the interface changes, an outdated snapshot fails
validation at startup instead of misbehaving mid-demo.
"""

from datetime import datetime
from pathlib import Path

from pydantic import BaseModel

from app.schemas.erp import Bom, ManufacturingOrder, Product, SaleOrder, StockLevel, WorkCenter, WorkOrder

SNAPSHOT_FORMAT = 2  # 2: work orders, MO component readiness
DEFAULT_SNAPSHOT_PATH = Path(__file__).parent / "snapshot" / "voltride.json"


class Snapshot(BaseModel):
    format: int = SNAPSHOT_FORMAT
    exported_at: datetime
    server_version: str
    currency: str
    sale_orders: list[SaleOrder]
    manufacturing_orders: list[ManufacturingOrder]
    stock_levels: list[StockLevel]
    products: list[Product]
    boms: list[Bom]
    work_centers: list[WorkCenter]
    work_orders: list[WorkOrder]


def load_snapshot(path: Path) -> Snapshot:
    snapshot = Snapshot.model_validate_json(path.read_bytes())
    if snapshot.format != SNAPSHOT_FORMAT:
        raise ValueError(f"snapshot {path} has format {snapshot.format}, expected {SNAPSHOT_FORMAT}; re-export it")
    return snapshot
