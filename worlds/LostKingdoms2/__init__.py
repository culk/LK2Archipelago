import sqlite3
import os
from typing import Optional

from BaseClasses import ItemClassification, Region, MultiWorld
from worlds.AutoWorld import WebWorld, World
from .Items import LK2Item
from .Locations import LK2Location
from .LK2Options import LostKingdoms2Options, WinConditionOptions

class LostKingdoms2Web(WebWorld):
    theme = "jungle"


class LostKingdoms2World(World):
    """
    Lost Kingdoms II, known as 'Rune II: Koruten no Kagi no Himitsu' in Japan, is a 2003 action role-playing game developed by FromSoftware and published by Activision. It is the sequel to Lost Kingdoms. Lost Kingdoms II is a card-based action role-playing game where battles are fought in real-time.
    """

    game = "Lost Kingdoms II"

    options_dataclass = LostKingdoms2Options  # options the player can set
    options: LostKingdoms2Options  # typing hints for option results
    #settings: typing.ClassVar[MyGameSettings]  # will be automatically assigned from type hint
    topology_present = True  # show path to required location checks in spoiler

    # ID of first item and location, could be hard-coded but code may be easier
    # to read with this as a property.
    base_id = 0
    # instead of dynamic numbering, IDs could be part of data

    # The following two dicts are required for the generation to know which
    # items exist. They could be generated from json or something else. They can
    # include events, but don't have to since events will be placed manually.

    conn = sqlite3.connect(os.path.join(os.path.dirname(__file__),"LK2DB.db"))
    cursor = conn.cursor()

    cursor.execute("Select name from cards")
    lost_kingdoms_2_items = [row[0] for row in cursor.fetchall()]

    item_name_to_id = {name: id for
                       id, name in enumerate(lost_kingdoms_2_items, base_id)}

    cursor.execute("Select name from location")
    lost_kingdoms_2_items = [row[0] for row in cursor.fetchall()]

    location_name_to_id = {name: id for
                           id, name in enumerate(lost_kingdoms_2_items, base_id)}

    # Items can be grouped using their names to allow easy checking if any item
    # from that group has been collected. Group names can also be used for !hint
    item_name_groups = {
        "weapons": {"red_fairy", "world", "shop", "key_item"},
    }

    def __init__(self, multiworld: MultiWorld, player: int):
        super(LostKingdoms2World, self).__init__(multiworld, player)
        self.win_condition: Optional[int] = 0

    def create_item(self, item: str) -> LK2Item:
        cursor = self.conn.cursor()
        item_data = cursor.execute("Select name, hexCode from cards where name = ?", (item,)).fetchone()
        classification = ItemClassification.filler
        return LK2Item(item_data[0], item_data[1], classification, self.player)

    def generate_early(self) -> None:

        starting_inventory = {"Hobgoblin", "Hobgoblin", "Hobgoblin", "Lizardman", "Lizardman", "Lizardman",
                              "Mandragora", "Mandragora", "Mandragora", "Fairy", "Dragon Knight"}
        for item in starting_inventory:
            self.multiworld.push_precollected(self.create_item(item))

    def create_regions(self):
        menu_region = Region("Menu", self.player, self.multiworld)
        self.multiworld.regions.append(menu_region)

        self.cursor.execute("Select distinct level from location").fetchall()
        region_names = [row[0] for row in self.cursor.fetchall()]
        for region_name in region_names:
            region = Region(region_name, self.player, self.multiworld)
            self.multiworld.regions.append(region)
            menu_region.connect(region)

        locations_tuples = self.cursor.execute("Select level,name,isoAddress,missable from location").fetchall()

        for location_tuple in locations_tuples:
            location = LK2Location(location_tuple[0], location_tuple[1], location_tuple[2],location_tuple[3])
            self.multiworld.get_region(location.name, self.player).locations.append(location)

    def set_rules(self) -> None:
        pass

    def generate_output(self, output_directory: str):
        # Output seed name and slot number to seed RNG in randomizer client
        # noinspection PyDictCreation
        output_data = {
            "Seed": self.multiworld.seed,
            "Slot": self.player,
            "Name": self.player_name,
            "Options": LostKingdoms2Options,
            "Locations": {},
            "Room Enemies": {},
            "Hints": {},
            "Client" : "APWorldVersion"
        }

