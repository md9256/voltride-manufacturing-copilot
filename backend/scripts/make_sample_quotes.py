"""Generate sample supplier quote PDFs for the quote-intake demo and tests.

Run from /backend:  python -m scripts.make_sample_quotes

Each sample exercises a different path through the review checks:
1. clean            - everything matches; can become a draft PO directly
2. bad-arithmetic   - a line total and the grand total don't add up (blocks)
3. fuzzy-unknown    - supplier name differs from the vendor record, one
                      product is unknown, one price is 11% above the agreed price
4. duplicate        - quote number already used on an existing purchase order
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from fpdf import FPDF

OUT_DIR = Path(__file__).resolve().parents[1] / "samples" / "quotes"


@dataclass
class Line:
    code: str
    description: str
    qty: float
    price: float
    printed_total: float | None = None  # override to print a wrong line total

    @property
    def total(self) -> float:
        return self.printed_total if self.printed_total is not None else round(self.qty * self.price, 2)


@dataclass
class Quote:
    filename: str
    supplier: str
    address: str
    number: str
    date: str
    lines: list[Line]
    printed_total: float | None = None  # override to print a wrong grand total


SAMPLES = [
    Quote(
        "1-clean-taipei-circuit.pdf",
        "Taipei Circuit Co.",
        "No. 88, Sec. 2, Zhongshan N. Rd., Taipei, Taiwan",
        "TPC-Q-2026-0412",
        "2026-10-02",
        [
            Line("CHP-MCU", "MCU chip STM32G4", 60, 61.50),
            Line("CHP-MOS", "MOSFET power stage pack", 40, 86.00),
            Line("SNS-TRQ", "Torque sensor", 10, 385.00),
        ],
    ),
    Quote(
        "2-bad-arithmetic-visionpanel.pdf",
        "VisionPanel Displays",
        "18 Xinghu St., Suzhou Industrial Park, China",
        "VPD-7781",
        "2026-09-29",
        [
            Line("LCD-35", "3.5in colour LCD panel", 20, 158.00, printed_total=3610.00),  # should be 3,160.00
            Line("CAS-DSP", "Display housing", 30, 32.00),
        ],
    ),
    Quote(
        "3-fuzzy-unknown-shenzhen.pdf",
        "Shenzhen Motor Works Co., Ltd.",
        "Bao'an District, Shenzhen, Guangdong, China",
        "SZM-2026-118",
        "2026-10-01",
        [
            Line("MTR-750", "750W high-power drive motor", 12, 2650.00),  # agreed price 2,380
            Line("RBC-9", "Regenerative brake controller RBC-9", 5, 420.00),  # not a VoltRide product
        ],
    ),
    Quote(
        "4-duplicate-taipei-circuit.pdf",
        "Taipei Circuit Co.",
        "No. 88, Sec. 2, Zhongshan N. Rd., Taipei, Taiwan",
        "SEED-PO-001",  # already on purchase order P00001 from the seed data
        "2026-09-25",
        [
            Line("CHP-MCU", "MCU chip STM32G4", 60, 62.00),
            Line("CHP-MOS", "MOSFET power stage pack", 40, 88.00),
        ],
    ),
]


def render(q: Quote) -> bytes:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 9, q.supplier, new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", size=9)
    pdf.cell(0, 5, q.address, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(6)
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 8, "QUOTATION", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", size=10)
    for label, value in [
        ("Quote no.", q.number),
        ("Date", q.date),
        ("Customer", "VoltRide Systems Ltd., Hong Kong"),
        ("Currency", "HKD"),
        ("Valid for", "30 days"),
    ]:
        pdf.cell(30, 6, label)
        pdf.cell(0, 6, value, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    widths = [28, 72, 18, 32, 40]
    pdf.set_font("Helvetica", "B", 9)
    for w, h in zip(widths, ["Item code", "Description", "Qty", "Unit price", "Amount"], strict=True):
        pdf.cell(w, 7, h, border="B", align="R" if h in ("Qty", "Unit price", "Amount") else "L")
    pdf.ln()
    pdf.set_font("Helvetica", size=9)
    for line in q.lines:
        pdf.cell(widths[0], 7, line.code)
        pdf.cell(widths[1], 7, line.description)
        pdf.cell(widths[2], 7, f"{line.qty:g}", align="R")
        pdf.cell(widths[3], 7, f"{line.price:,.2f}", align="R")
        pdf.cell(widths[4], 7, f"{line.total:,.2f}", align="R", new_x="LMARGIN", new_y="NEXT")

    subtotal = round(sum(line.total for line in q.lines), 2)
    total = q.printed_total if q.printed_total is not None else subtotal
    pdf.ln(2)
    pdf.set_font("Helvetica", size=10)
    for label, value, bold in [("Subtotal", subtotal, False), ("Tax", 0.0, False), ("TOTAL (HKD)", total, True)]:
        pdf.set_font("Helvetica", "B" if bold else "", 10)
        pdf.cell(sum(widths[:4]), 7, label, align="R")
        pdf.cell(widths[4], 7, f"{value:,.2f}", align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(8)
    pdf.set_font("Helvetica", "I", 8)
    pdf.multi_cell(0, 4, "Prices ex-works. Payment 30 days net. Lead times as per frame agreement.")
    return bytes(pdf.output())


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for q in SAMPLES:
        (OUT_DIR / q.filename).write_bytes(render(q))
        print(f"wrote {OUT_DIR / q.filename}")


if __name__ == "__main__":
    main()
