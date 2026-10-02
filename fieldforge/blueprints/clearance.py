"""Pair distances and exact limit comparisons for axis-aligned envelopes."""

from decimal import Decimal, localcontext


def _text(value):
    if not value:
        return "0"
    value = value.normalize()
    return format(value, "f") if -6 <= value.adjusted() <= 12 else str(value)


def clearance_measurement(gaps):
    """Display the shortest box distance; preserve its exact square for comparison.

    800 digits cover sums of squared gaps across the supported finite float input
    range (5e-324 through 2e6). Only the displayed square root is rounded, to 17
    significant digits. No tolerance is introduced and no global context changes.
    """
    with localcontext() as context:
        context.prec = 800
        squared = sum(Decimal(value) ** 2 for value in gaps)
        with localcontext() as display:
            display.prec = 17
            distance = squared.sqrt()
        return {"clearance_mm": _text(distance), "clearance_squared_mm2": _text(squared),
                "clearance_is_rounded": distance * distance != squared}


def evaluate_pair(rule, pair):
    """Evaluate an already-validated rule against a freshly computed pair."""
    metric = rule["metric"]
    metadata = {}
    with localcontext() as context:
        context.prec = 800
        if metric == "pair.relation":
            actual = pair["relation"]
            passed = actual == rule["value"]
        else:
            expected = Decimal(str(rule["value"]))
            if metric == "pair.clearance":
                actual = pair["clearance_mm"]
                measured = Decimal(pair["clearance_squared_mm2"])
                expected = expected ** 2
                metadata = {"actual_squared_mm2": pair["clearance_squared_mm2"],
                            "actual_is_rounded": pair["clearance_is_rounded"]}
            else:
                actual = pair["gap_mm"]["xyz".index(metric[-1])]
                measured = Decimal(actual)
            passed = {"=": measured == expected, "<=": measured <= expected,
                      ">=": measured >= expected}[rule["operator"]]
    prefix = "Approximately " if metadata.get("actual_is_rounded") else ""
    detail = (f"{rule['target']}: {prefix}{actual} {rule['unit']}; "
              f"expected {rule['operator']} {rule['value']} {rule['unit']}.")
    if metric == "pair.clearance":
        detail += " Compared squared distances exactly; the displayed square root is not used for acceptance."
    elif metric != "pair.relation":
        detail += " Compared decimal gaps exactly; zero can mean overlap or contact on this axis."
    return {"actual": actual, "status": "passed" if passed else "failed", "detail": detail, **metadata}
