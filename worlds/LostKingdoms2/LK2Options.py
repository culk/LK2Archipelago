from __future__ import annotations

from dataclasses import dataclass
from Options import Choice, Option, PerGameCommonOptions, Range, DeathLink

from typing import Dict

class WinConditionOptions(Choice):
    """Choose the win condition.
    """
    display_name = "Win Condition"
    option_defeat_emperor = 0
    option_collect_all_cards = 1
    option_default = 0


@dataclass
class LostKingdoms2Options(PerGameCommonOptions):
    win_condition: WinConditionOptions