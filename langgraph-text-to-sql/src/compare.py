"""Compare a query's result with the expected one, ignoring column names, row order, and float noise."""

from datetime import date, datetime
from decimal import Decimal


def normalise_value(value):
    if isinstance(value, (Decimal, float)):
        return round(float(value), 2)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def normalise(rows) -> list[list]:
    """Rows as sorted lists of normalised values (row order is not part of the answer)."""
    return sorted(([normalise_value(v) for v in row] for row in rows), key=repr)


def matches(rows, expected) -> bool:
    """Same multiset of rows. A result with extra columns still matches if one column subset equals the expected rows."""
    got = normalise(rows)
    if got == expected:
        return True
    # Tolerate extra columns (e.g. the model also returns the count next to the city): try each column subset
    if got and expected and len(got) == len(expected) and len(got[0]) > len(expected[0]):
        width = len(expected[0])
        from itertools import combinations
        for cols in combinations(range(len(got[0])), width):
            if sorted(([row[i] for i in cols] for row in got), key=repr) == expected:
                return True
    return False
