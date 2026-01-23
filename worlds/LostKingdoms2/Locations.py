from typing import NamedTuple, Optional, List
from BaseClasses import Location, Region

class LK2Location(Location):
    region: str
    name: str
    iso_address: str
    missable: bool

    def __init__(self, region, name, iso_address, missable):
        super(LK2Location, self).__init__(region, name, iso_address, missable)

        self.region = region
        self.name = name
        self.iso_address = iso_address
        self.missable = missable