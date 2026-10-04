"""The VoltRide Systems demo dataset, as plain data.

Kept separate from seed_odoo.py so the story of the dataset is readable in one
place. Every record carries a stable business key (product code, partner ref,
order reference) which the seeder uses to stay idempotent.

Product structure (3 BOM levels below the kits):

    KIT-MID  Mid-drive kit 250W   -> SA-DRV-MID -> SA-CTL-STD -> PCB, MCU, MOSFETs, casing, thermal pad
    KIT-HP   High-power kit 750W  -> SA-DRV-HP  -> SA-CTL-HP  -> ...
    KIT-HUB  Hub motor kit 350W   -> SA-CTL-STD (directly, hub motors carry no drive unit)
    all kits -> SA-DSP display unit -> LCD, display PCB, housing, buttons, MCU

The MCU chip is shared by every controller and every display, and is
deliberately short in stock: it is the bottleneck the planner should find.
Prices are in the company currency (HKD on the trial database).
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Supplier:
    ref: str
    name: str
    city: str


@dataclass(frozen=True)
class Customer:
    ref: str
    name: str
    city: str


@dataclass(frozen=True)
class Component:
    code: str
    name: str
    cost: float
    supplier: str  # Supplier.ref
    lead_days: int
    on_hand: float
    min_qty: float  # reorder rule minimum; on_hand < min_qty means "low stock"
    max_qty: float


@dataclass(frozen=True)
class Operation:
    name: str
    workcenter: str  # WorkCenter.code
    minutes: float  # expected duration per unit


@dataclass(frozen=True)
class Manufactured:
    code: str
    name: str
    sale_price: float  # 0 for sub-assemblies that are never sold
    on_hand: float
    lines: dict[str, float]  # component/sub-assembly code -> quantity per unit
    operations: list[Operation] = field(default_factory=list)


@dataclass(frozen=True)
class WorkCenter:
    code: str
    name: str
    cost_per_hour: float


@dataclass(frozen=True)
class SaleOrder:
    ref: str
    customer: str  # Customer.ref
    days_ago: int
    state: str  # draft | sale | cancel
    lines: dict[str, float]  # kit code -> quantity


@dataclass(frozen=True)
class PurchaseOrder:
    ref: str
    supplier: str
    days_ago: int
    state: str  # draft | purchase
    lines: dict[str, float]


@dataclass(frozen=True)
class ManufacturingOrder:
    ref: str
    product: str
    qty: float
    days_ago: int  # planned start, relative to today
    state: str  # draft | confirmed | progress | done
    # For done orders: actual minutes per work order as a multiple of expected,
    # so the shop-floor view (Phase 5) has planned-vs-actual variance to show.
    actual_factor: float = 1.0
    hour_utc: int = 8  # start time of the first work order (UTC; 01:00 UTC = 09:00 in Hong Kong)
    # Historical orders that must not change today's stock picture: the seeder
    # tops up exactly what they consume before finishing them, and removes
    # what they produce afterwards (as if it had shipped or been used since).
    stock_neutral: bool = False


SUPPLIERS = [
    Supplier("SUP-SZM", "Shenzhen MotorWorks Ltd", "Shenzhen"),
    Supplier("SUP-TPC", "Taipei Circuit Co.", "Taipei"),
    Supplier("SUP-DGC", "Dongguan Cable & Harness", "Dongguan"),
    Supplier("SUP-NBP", "Ningbo Precision Metal", "Ningbo"),
    Supplier("SUP-VPD", "VisionPanel Displays", "Suzhou"),
]

CUSTOMERS = [
    Customer("CUS-ALP", "Alpine Cycles GmbH", "Innsbruck"),
    Customer("CUS-URB", "Urban Pedal Co.", "Amsterdam"),
    Customer("CUS-CST", "Coastline E-Bikes", "Sydney"),
    Customer("CUS-PKT", "Peak Trail Bikes", "Vancouver"),
]

WORK_CENTERS = [
    WorkCenter("PCB", "PCB Line", 420.0),
    WorkCenter("ASM", "Assembly", 360.0),
    WorkCenter("TST", "Testing", 300.0),
]

# fmt: off
COMPONENTS = [
    # Motors
    Component("MTR-250", "Mid-drive motor 250W",        1450.0, "SUP-SZM", 21,  14,  10, 40),
    Component("MTR-750", "High-power motor 750W",       2380.0, "SUP-SZM", 28,   3,   8, 24),  # short
    Component("MTR-HUB", "Rear hub motor 350W",          980.0, "SUP-SZM", 21,  18,  10, 40),
    # Controller parts
    Component("PCB-CTL", "Controller PCB (bare)",        145.0, "SUP-TPC", 14,  40,  20, 80),
    Component("CHP-MCU", "MCU chip STM32G4",              62.0, "SUP-TPC", 35,   9,  40, 150),  # short, shared
    Component("CHP-MOS", "MOSFET power stage pack",       88.0, "SUP-TPC", 14,  12,  30, 100),  # short
    Component("CAS-CTL", "Controller aluminium casing",   75.0, "SUP-NBP", 10,  45,  20, 80),
    Component("THM-PAD", "Thermal interface pad",          6.5, "SUP-TPC",  7, 120,  40, 200),
    # Display parts
    Component("LCD-35",  "3.5in colour LCD panel",       160.0, "SUP-VPD", 21,   6,  15, 60),  # short
    Component("PCB-DSP", "Display PCB",                   58.0, "SUP-TPC", 14,  30,  15, 60),
    Component("CAS-DSP", "Display housing",               32.0, "SUP-VPD", 10,  35,  15, 60),
    Component("BTN-PAD", "Handlebar button pad",          45.0, "SUP-VPD", 10,  40,  15, 60),
    # Sensors
    Component("SNS-TRQ", "Torque sensor",                390.0, "SUP-TPC", 28,   5,  12, 40),  # short
    Component("SNS-CAD", "Cadence sensor",                68.0, "SUP-TPC", 14,  25,  10, 40),
    Component("SNS-SPD", "Speed sensor & spoke magnet",   38.0, "SUP-TPC", 14,  50,  20, 80),
    # Cables and connectors
    Component("CBL-MAIN", "Main wiring harness",          95.0, "SUP-DGC", 14,  30,  15, 60),
    Component("CBL-EXT", "Motor extension cable",         42.0, "SUP-DGC", 10,  35,  15, 60),
    Component("CBL-BRK", "Brake cut-off sensor pair",     55.0, "SUP-DGC", 10,  60,  20, 80),
    Component("CON-HIG", "HIGO waterproof connector set", 36.0, "SUP-DGC", 21,  10,  25, 80),  # short
    # Mechanical
    Component("CRG-42",  "Chainring 42T",                 85.0, "SUP-NBP", 14,  22,  10, 40),
    Component("CRG-38",  "Chainring 38T",                 85.0, "SUP-NBP", 14,  15,  10, 40),
    Component("BRK-MNT", "Motor mount bracket",           70.0, "SUP-NBP", 14,  28,  15, 60),
    Component("BOLT-KIT", "Fastener kit",                 18.0, "SUP-NBP",  7, 100,  30, 150),
    Component("SPK-36",  "Spoke set 36h",                 65.0, "SUP-NBP", 10,  20,  10, 40),
    # Packaging
    Component("PKG-BOX", "Kit retail box",                22.0, "SUP-NBP",  7,  80,  30, 150),
]
# fmt: on

# Ordered bottom-up (sub-assemblies before the products that use them).
MANUFACTURED = [
    Manufactured(
        "SA-CTL-STD",
        "Controller 36V (standard)",
        0,
        6,
        {"PCB-CTL": 1, "CHP-MCU": 1, "CHP-MOS": 1, "CAS-CTL": 1, "THM-PAD": 1},
        [Operation("Solder & flash firmware", "PCB", 12), Operation("Controller burn-in", "TST", 20)],
    ),
    Manufactured(
        "SA-CTL-HP",
        "Controller 48V (high-power)",
        0,
        2,
        {"PCB-CTL": 1, "CHP-MCU": 1, "CHP-MOS": 2, "CAS-CTL": 1, "THM-PAD": 2},
        [Operation("Solder & flash firmware", "PCB", 15), Operation("Controller burn-in", "TST", 30)],
    ),
    Manufactured(
        "SA-DSP",
        "Display unit",
        0,
        8,
        {"LCD-35": 1, "PCB-DSP": 1, "CAS-DSP": 1, "BTN-PAD": 1, "CHP-MCU": 1},
        [Operation("Mount LCD & flash", "PCB", 10), Operation("Display check", "TST", 5)],
    ),
    Manufactured(
        "SA-DRV-MID",
        "Mid-drive unit 250W",
        0,
        3,
        {"MTR-250": 1, "SA-CTL-STD": 1, "SNS-TRQ": 1, "BRK-MNT": 1, "CBL-MAIN": 1},
        [Operation("Mount motor & controller", "ASM", 25), Operation("Dyno test", "TST", 15)],
    ),
    Manufactured(
        "SA-DRV-HP",
        "High-power drive unit 750W",
        0,
        1,
        {"MTR-750": 1, "SA-CTL-HP": 1, "SNS-TRQ": 1, "BRK-MNT": 1, "CBL-MAIN": 1},
        [Operation("Mount motor & controller", "ASM", 35), Operation("Dyno test", "TST", 20)],
    ),
    Manufactured(
        "KIT-MID",
        "VoltRide Mid-Drive Kit 250W",
        5800.0,
        4,
        {"SA-DRV-MID": 1, "SA-DSP": 1, "CRG-42": 1, "SNS-SPD": 1, "CBL-BRK": 1, "BOLT-KIT": 1, "PKG-BOX": 1},
        [Operation("Kit & pack", "ASM", 10), Operation("Final inspection", "TST", 8)],
    ),
    Manufactured(
        "KIT-HP",
        "VoltRide High-Power Kit 750W",
        8600.0,
        1,
        {
            "SA-DRV-HP": 1,
            "SA-DSP": 1,
            "CRG-38": 1,
            "SNS-SPD": 1,
            "CBL-BRK": 1,
            "CON-HIG": 2,
            "BOLT-KIT": 1,
            "PKG-BOX": 1,
        },
        [Operation("Kit & pack", "ASM", 12), Operation("Final inspection", "TST", 10)],
    ),
    Manufactured(
        "KIT-HUB",
        "VoltRide Hub Motor Kit 350W",
        3600.0,
        6,
        {
            "MTR-HUB": 1,
            "SA-CTL-STD": 1,
            "SA-DSP": 1,
            "SNS-CAD": 1,
            "SPK-36": 1,
            "CBL-EXT": 1,
            "CBL-BRK": 1,
            "CON-HIG": 1,
            "PKG-BOX": 1,
        },
        [Operation("Kit & pack", "ASM", 10), Operation("Final inspection", "TST", 8)],
    ),
]

SALE_ORDERS = [
    SaleOrder("SEED-SO-001", "CUS-ALP", 68, "sale", {"KIT-MID": 4}),
    SaleOrder("SEED-SO-002", "CUS-URB", 61, "sale", {"KIT-HUB": 10}),
    SaleOrder("SEED-SO-003", "CUS-CST", 50, "cancel", {"KIT-HP": 2}),
    SaleOrder("SEED-SO-004", "CUS-PKT", 44, "sale", {"KIT-MID": 3, "KIT-HP": 1}),
    SaleOrder("SEED-SO-005", "CUS-ALP", 33, "sale", {"KIT-HUB": 6}),
    SaleOrder("SEED-SO-006", "CUS-URB", 26, "sale", {"KIT-MID": 8}),
    SaleOrder("SEED-SO-007", "CUS-CST", 19, "sale", {"KIT-HP": 5}),
    SaleOrder("SEED-SO-008", "CUS-PKT", 12, "sale", {"KIT-HUB": 4, "KIT-MID": 2}),
    SaleOrder("SEED-SO-009", "CUS-ALP", 5, "draft", {"KIT-HP": 6}),
    SaleOrder("SEED-SO-010", "CUS-URB", 2, "draft", {"KIT-MID": 12, "KIT-HUB": 8}),
]

PURCHASE_ORDERS = [
    PurchaseOrder("SEED-PO-001", "SUP-TPC", 9, "purchase", {"CHP-MCU": 60, "CHP-MOS": 40}),
    PurchaseOrder("SEED-PO-002", "SUP-SZM", 3, "draft", {"MTR-750": 12}),
]

MANUFACTURING_ORDERS = [
    ManufacturingOrder("SEED-MO-001", "SA-DSP", 6, 20, "done", actual_factor=1.25),
    ManufacturingOrder("SEED-MO-002", "KIT-MID", 2, 14, "done", actual_factor=0.9),
    ManufacturingOrder("SEED-MO-003", "KIT-HUB", 3, 3, "progress"),
    ManufacturingOrder("SEED-MO-004", "SA-CTL-STD", 10, 1, "confirmed"),
    ManufacturingOrder("SEED-MO-005", "KIT-HP", 4, -2, "confirmed"),
    ManufacturingOrder("SEED-MO-006", "KIT-MID", 5, -5, "draft"),
    # Production history for the shop-floor view (Phase 5): five weeks of
    # finished orders with realistic overruns, plus one order running today.
    ManufacturingOrder("SEED-MO-007", "SA-CTL-STD", 8, 34, "done", 1.15, hour_utc=1, stock_neutral=True),
    ManufacturingOrder("SEED-MO-008", "SA-DSP", 10, 32, "done", 0.95, hour_utc=2, stock_neutral=True),
    ManufacturingOrder("SEED-MO-009", "KIT-HUB", 4, 29, "done", 1.30, hour_utc=1, stock_neutral=True),
    ManufacturingOrder("SEED-MO-010", "SA-CTL-HP", 4, 27, "done", 1.40, hour_utc=3, stock_neutral=True),
    ManufacturingOrder("SEED-MO-011", "SA-DRV-MID", 4, 24, "done", 1.10, hour_utc=1, stock_neutral=True),
    ManufacturingOrder("SEED-MO-012", "KIT-MID", 3, 21, "done", 1.05, hour_utc=5, stock_neutral=True),
    ManufacturingOrder("SEED-MO-013", "SA-DSP", 8, 17, "done", 1.20, hour_utc=1, stock_neutral=True),
    ManufacturingOrder("SEED-MO-014", "SA-DRV-HP", 2, 12, "done", 1.35, hour_utc=2, stock_neutral=True),
    ManufacturingOrder("SEED-MO-015", "KIT-HP", 2, 10, "done", 1.25, hour_utc=1, stock_neutral=True),
    ManufacturingOrder("SEED-MO-016", "SA-CTL-STD", 6, 7, "done", 0.90, hour_utc=1, stock_neutral=True),
    ManufacturingOrder("SEED-MO-017", "KIT-HUB", 2, 4, "done", 1.10, hour_utc=3, stock_neutral=True),
    ManufacturingOrder("SEED-MO-018", "SA-DSP", 4, 0, "progress", 1.20, hour_utc=1, stock_neutral=True),
    ManufacturingOrder("SEED-MO-019", "SA-CTL-HP", 2, 2, "done", 1.05, hour_utc=2, stock_neutral=True),
]
