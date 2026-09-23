"""Refresh the two DERIVED cost columns on the existing transmission-line CSV.

    python -m energy_cost.recompute [--data PATH] [--check]

The CSV stays the single dataset file. This script does not create another one,
does not reorder rows, and does not touch a single source value: it rewrites
each line as its original text plus the two calculated fields.

    Loss_Cost_Per_Hour_INR = Energy_Loss_MW x 1000 x Tariff_INR_per_kWh
    Loss_Cost_Per_Year_INR = Loss_Cost_Per_Hour_INR x 8760

Both are DERIVED, per transmission line, at the verified KERC HT-2(a) energy
charge in `energy_cost.tariff`. A row whose `Energy_Loss_MW` is blank gets two
blank cells - never a substituted number.

`--check` recomputes without writing and reports whether the file is current.
Run it after changing the tariff; `tests/test_energy_cost.py` runs it too, so a
stale CSV fails the suite instead of quietly drifting.
"""

from __future__ import annotations

import argparse
import sys

from phase1.data_loader import find_dataset

from .tariff import (KARNATAKA_HT_INDUSTRIAL_ENERGY_CHARGE, TariffRate,
                     annualised_cost_inr, hourly_cost_inr, resolve_tariff)

#: The calculated columns this script owns. Everything else in the CSV is
#: source data and is passed through untouched.
DERIVED_COLUMNS = ("Loss_Cost_Per_Hour_INR", "Loss_Cost_Per_Year_INR")

#: Enough decimals that the value round-trips, few enough to stay readable.
COST_DECIMALS = 2


def _format_cost(value) -> str:
    return "" if value is None else f"{value:.{COST_DECIMALS}f}"


def _parse_loss(cell: str):
    cell = cell.strip()
    if not cell:
        return None
    try:
        return float(cell)
    except ValueError:
        return None


def derived_cells(energy_loss_mw, tariff: TariffRate) -> tuple:
    """The two calculated cells for one line, blank when the source is blank."""
    if energy_loss_mw is None:
        return "", ""
    hourly = hourly_cost_inr(energy_loss_mw, tariff)
    return _format_cost(hourly), _format_cost(annualised_cost_inr(hourly))


def rewrite(path: str, tariff: TariffRate = None, write: bool = True) -> dict:
    """Recompute the derived columns on `path`.

    Returns a report; with `write=False` nothing is saved and the report says
    whether the file already matches.
    """
    tariff = resolve_tariff(tariff)

    with open(path, "r", encoding="utf-8", newline="") as handle:
        original = handle.read()

    # Keep the file's own line endings rather than normalising them.
    lines = original.splitlines(keepends=True)
    if not lines:
        raise SystemExit(f"{path} is empty.")

    def split_line(text: str) -> tuple:
        body = text.rstrip("\r\n")
        ending = text[len(body):]
        return body, ending

    header_body, header_end = split_line(lines[0])
    header = [c.strip() for c in header_body.split(",")]

    if "Energy_Loss_MW" not in header:
        raise SystemExit(
            f"{path} has no Energy_Loss_MW column; there is nothing to cost."
        )

    # Strip any previous run's derived columns, then append them fresh, so the
    # script is idempotent and a tariff change fully replaces the old values.
    keep = [i for i, name in enumerate(header) if name not in DERIVED_COLUMNS]
    loss_index = keep.index(header.index("Energy_Loss_MW"))

    out = [",".join([header[i] for i in keep] + list(DERIVED_COLUMNS))
           + (header_end or "\n")]

    rows = blanks = 0
    for raw in lines[1:]:
        body, ending = split_line(raw)
        if not body.strip():
            out.append(raw)
            continue

        cells = body.split(",")
        if len(cells) < len(header):
            cells = cells + [""] * (len(header) - len(cells))
        source_cells = [cells[i] for i in keep]

        loss = _parse_loss(source_cells[loss_index])
        if loss is None:
            blanks += 1
        rows += 1

        out.append(",".join(source_cells + list(derived_cells(loss, tariff)))
                   + (ending or "\n"))

    updated = "".join(out)
    current = updated == original

    if write and not current:
        with open(path, "w", encoding="utf-8", newline="") as handle:
            handle.write(updated)

    return {
        "path": path,
        "rows": rows,
        "blank_energy_loss": blanks,
        "already_current": current,
        "written": bool(write and not current),
        "tariff_inr_per_kwh": tariff.inr_per_kwh,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Refresh the derived loss-cost columns on the dataset CSV."
    )
    parser.add_argument("--data", default=None,
                        help="Path to the CSV (default: the one in data/).")
    parser.add_argument("--check", action="store_true",
                        help="Report without writing.")
    args = parser.parse_args(argv)

    path = args.data or find_dataset()
    tariff = KARNATAKA_HT_INDUSTRIAL_ENERGY_CHARGE
    report = rewrite(path, tariff, write=not args.check)

    print(f"dataset : {report['path']}")
    print(f"tariff  : Rs. {tariff.inr_per_kwh:.2f}/kWh "
          f"({tariff.category}, energy charge only)")
    print(f"rows    : {report['rows']}  "
          f"({report['blank_energy_loss']} without Energy_Loss_MW)")
    print(f"columns : {', '.join(DERIVED_COLUMNS)} (calculated, not source)")

    if args.check:
        print("status  : up to date" if report["already_current"]
              else "status  : STALE - run without --check to refresh")
        return 0 if report["already_current"] else 1

    print("status  : unchanged" if report["already_current"] else "status  : written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
