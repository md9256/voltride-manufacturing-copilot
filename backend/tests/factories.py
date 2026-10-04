"""Tiny builders for planning fixtures: products, BOMs and work centers by code."""

from app.schemas.erp import Bom, BomLine, BomOperation, Product, SupplierPrice, WorkCenter
from app.services.bom import ManufacturingData


def supplier(name: str, price: float, lead_days: int = 10, min_qty: float = 1, sid: int = 1) -> SupplierPrice:
    return SupplierPrice(supplier_id=sid, supplier=name, price=price, min_qty=min_qty, lead_days=lead_days)


def product(
    id: int,
    code: str,
    *,
    free: float = 0,
    on_hand: float | None = None,
    incoming: float = 0,
    cost: float = 1.0,
    suppliers: list[SupplierPrice] | None = None,
) -> Product:
    return Product(
        id=id,
        code=code,
        name=f"{code} name",
        cost=cost,
        on_hand=free if on_hand is None else on_hand,
        free_qty=free,
        incoming_qty=incoming,
        suppliers=suppliers or [],
    )


def bom(
    id: int,
    product_id: int,
    lines: dict[int, float],
    *,
    qty: float = 1,
    ops: list[tuple[int, float]] | None = None,
    type: str = "normal",
    sequence: int = 0,
) -> Bom:
    return Bom(
        id=id,
        product_id=product_id,
        quantity=qty,
        type=type,
        sequence=sequence,
        lines=[BomLine(product_id=pid, quantity=q) for pid, q in lines.items()],
        operations=[BomOperation(name=f"op{i}", workcenter_id=wc, minutes=m) for i, (wc, m) in enumerate(ops or [])],
    )


def work_center(
    id: int, code: str, *, hours_per_day: float = 8, efficiency: float = 1.0, rate: float = 60
) -> WorkCenter:
    return WorkCenter(
        id=id, code=code, name=f"{code} center", hours_per_day=hours_per_day, efficiency=efficiency, cost_per_hour=rate
    )


def data(products, boms, work_centers=()) -> ManufacturingData:
    return ManufacturingData.build(list(products), list(boms), list(work_centers))


# A miniature VoltRide: the CHIP is shared by the controller and the display.
#
#   KIT(1) -> CTL(2) x1 -> CHIP(10) x1, PCB(11) x1
#          -> DSP(3) x1 -> CHIP(10) x1, LCD(12) x1
#          -> BOX(13) x1
KIT, CTL, DSP, CHIP, PCB, LCD, BOX = 1, 2, 3, 10, 11, 12, 13
ASM, TST = 100, 101


def mini_voltride(**overrides) -> ManufacturingData:
    """overrides: code -> Product, to tweak stock for one test."""
    products = {
        KIT: product(KIT, "KIT"),
        CTL: product(CTL, "CTL"),
        DSP: product(DSP, "DSP"),
        CHIP: product(CHIP, "CHIP", free=3, cost=60, suppliers=[supplier("ChipCo", 60, lead_days=35, sid=201)]),
        PCB: product(PCB, "PCB", free=100, cost=140, suppliers=[supplier("BoardCo", 140, lead_days=14, sid=202)]),
        LCD: product(LCD, "LCD", free=100, cost=160, suppliers=[supplier("PanelCo", 160, lead_days=21, sid=203)]),
        BOX: product(BOX, "BOX", free=100, cost=20, suppliers=[supplier("BoxCo", 20, lead_days=7, sid=204)]),
    }
    by_code = {p.code: pid for pid, p in products.items()}
    for code, replacement in overrides.items():
        products[by_code[code]] = replacement
    boms = [
        bom(1, KIT, {CTL: 1, DSP: 1, BOX: 1}, ops=[(ASM, 30)]),
        bom(2, CTL, {CHIP: 1, PCB: 1}, ops=[(ASM, 12), (TST, 20)]),
        bom(3, DSP, {CHIP: 1, LCD: 1}, ops=[(TST, 6)]),
    ]
    return data(products.values(), boms, [work_center(ASM, "ASM", rate=60), work_center(TST, "TST", rate=30)])
