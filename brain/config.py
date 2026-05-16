"""Tunable weights and scales for priority computation."""

PRIORITY_WEIGHTS = {
    "importance": 1.0,
    "urgency":    2.0,
    "time":       10.0,
    "energy":     0.5,
    "unlock":     0.0,
    "unfunded":   0.0,
}

URGENCY_SCALE = 7

ENERGY_PENALTIES = {"low": 0, "medium": 1, "high": 3, None: 0}

FITS_TIME_BOOST = 1.5

UNDO_STACK_LIMIT = 50
