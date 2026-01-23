from __future__ import annotations

from dataclasses import dataclass
from Options import Choice, Option, PerGameCommonOptions, Range

from typing import Dict

class WinConditionOptions(Choice):
    """Choose how many wins are needed for each duelist. This also sets the number of locations per duelist.

    Supported values: 3-10
    Default value: 5
    """
    defeat_emperor: 50

@dataclass
class LostKingdoms2Options(PerGameCommonOptions):
    WinCondition: WinConditionOptions