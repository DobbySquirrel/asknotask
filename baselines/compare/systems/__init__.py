"""CLEAR and AmbiSQL detectors used in the paper."""
from .ambisql import detect_ambisql
from .clear import detect_clear

DETECTORS = {
    "clear": detect_clear,
    "ambisql": detect_ambisql,
}
