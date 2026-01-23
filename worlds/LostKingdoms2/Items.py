from typing import NamedTuple, Optional, List
from BaseClasses import Item, Region, ItemClassification


class LK2Item(Item):
    name: str
    iso_address: str
    classification: ItemClassification

    def __init__(self, name, iso_address, classification, player=int):
        super(LK2Item, self).__init__(name, iso_address, classification, player=player)

        self.name = name
        self.iso_address = iso_address
        self.classification = classification