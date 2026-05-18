"""Tunable weights and scales for priority computation, plus model constants."""
import os

# Gemini model used by brain/parser.py and brain/coach.py.
# Override via the GEMINI_MODEL env var (e.g. "gemini-2.5-flash").
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-1.5-flash")


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

# Tag → lobe routing for 3D positioning. Customisable by user later.
TAG_TO_LOBE = {
    "планы": "frontal", "цели": "frontal", "проект": "frontal", "projects": "frontal",
    "работа": "parietal", "задачи": "parietal", "work": "parietal", "tasks": "parietal",
    "мотоцикл": "temporal", "идеи": "temporal", "память": "temporal", "ideas": "temporal",
    "творчество": "occipital", "дизайн": "occipital", "art": "occipital",
    "спорт": "cerebellum", "здоровье": "cerebellum", "привычки": "cerebellum", "habits": "cerebellum",
    "_default": "parietal",
}

# Lobe centers in normalized brain-space (-1..1). Used by visualizer to scatter nodes.
LOBE_CENTERS = {
    "frontal":    {"left": (-0.45,  0.25,  0.70), "right": ( 0.45,  0.25,  0.70)},
    "parietal":   {"left": (-0.40,  0.65,  0.05), "right": ( 0.40,  0.65,  0.05)},
    "temporal":   {"left": (-0.75, -0.05,  0.15), "right": ( 0.75, -0.05,  0.15)},
    "occipital":  {"left": (-0.30,  0.20, -0.75), "right": ( 0.30,  0.20, -0.75)},
    "cerebellum": {"center": (0.0, -0.55, -0.55)},
}
LOBE_SPREAD = 0.22  # gaussian sigma around lobe center
