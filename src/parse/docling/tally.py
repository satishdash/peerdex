"""What the walk kept and dropped, for one log line."""

from dataclasses import dataclass


@dataclass
class Tally:
    """What the walk kept and dropped, for one log line."""

    pic_seen: int = 0
    pic_kept: int = 0
    pic_drop_area: int = 0
    pic_drop_band: int = 0
    pic_drop_noimg: int = 0
    table_drop: int = 0
