"""What a figure measures. Figures combine only inside one dimension."""

from enum import StrEnum


class Dimension(StrEnum):
    """What a figure measures. Figures combine only inside one dimension."""

    MASS = "mass"
    ENERGY = "energy"
    VOLUME = "volume"
    COUNT = "count"
    FRACTION = "fraction"
    RATIO = "ratio"
