import os
import random
import threading
import time
import typing
from dataclasses import fields
from typing import Optional

from worlds.generic.Rules import add_rule, set_rule, forbid_item, add_item_rule

from BaseClasses import MultiWorld, LocationProgressType, CollectionState
import logging
from worlds.AutoWorld import WebWorld, World
from .client.constants import AP_WORLD_VERSION_NAME, CLIENT_VERSION
from .client.lostkingdoms2_settings import LostKingdoms2Settings
from ..LauncherComponents import launch_subprocess, components, Component, SuffixIdentifier, icon_paths, Type

from .Items import *
from .Locations import *
from .LK2Options import *
from .iso_helper.lk2_rom import LK2PlayerContainer

import logging

logger = logging.getLogger(__name__)

location_name_to_id = {}
item_name_to_id = {}

def run_client(*args):
    from .LK2Client import main  # lazy import
    launch_subprocess(main, name="LK2Client", args=args)

# Adds the launcher for our component and our client logo.
components.append(
    Component("Lost Kingdoms II Client", func=run_client, component_type=Type.CLIENT,
        file_identifier=SuffixIdentifier(".aplk2"), icon="Archipelago_Icon"))
icon_paths["Archipelago_Icon"] = f"ap:{__name__}/data/Archipelago_Icon.png"

class LostKingdoms2Web(WebWorld):
    theme = "jungle"


class LostKingdoms2World(World):
    """
    Lost Kingdoms II, known as 'Rune II: Koruten no Kagi no Himitsu' in Japan, is a 2003 action role-playing game developed by FromSoftware and published by Activision. It is the sequel to Lost Kingdoms. Lost Kingdoms II is a card-based action role-playing game where battles are fought in real-time.
    """

    game = "Lost Kingdoms II"

    options_dataclass = LK2Options.LostKingdoms2Options  # options the player can set
    options: LostKingdoms2Options  # typing hints for option results
    settings: typing.ClassVar[LostKingdoms2Settings]  # will be automatically assigned from type hint
    topology_present = True  # show path to required location checks in spoiler

    # The following two dicts are required for the generation to know which
    # items exist. They could be generated from json or something else. They can
    # include events, but don't have to since events will be placed manually.

    item_name_to_id = {}
    for key in lost_kingdoms_2_items:
        if item_name_to_id.get(key, None) is None:
            item_name_to_id[key] = lost_kingdoms_2_items[key]["id"]
    globals()['item_name_to_id'] = location_name_to_id

    location_name_to_id = {}
    location_id = 1
    for location in lost_kingdoms_2_locations:
        if location_name_to_id.get(location, None) is None:
            location_name_to_id[location] = location_id
            location_id += 1
    globals()['location_name_to_id'] = location_name_to_id

    # Items can be grouped using their names to allow easy checking if any item
    # from that group has been collected. Group names can also be used for !hint
    item_name_groups = {
        "groups": {"red_fairy", "world", "shop", "key_item"},
    }

    def __init__(self, multiworld: MultiWorld, player: int):
        super(LostKingdoms2World, self).__init__(multiworld, player)
        self.configure_logging()

    def configure_logging(self):
        logger.propagate = False

        # 🔹 IMPORTANT: allow DEBUG through the logger itself
        logger.setLevel(logging.DEBUG)

        root_logger = logging.getLogger()
        file_handler = None
        console_handler = None

        for handler in root_logger.handlers:
            if isinstance(handler, logging.FileHandler):
                file_handler = handler
            elif isinstance(handler, logging.StreamHandler):
                console_handler = handler

        if file_handler:
            file_handler.setLevel(logging.DEBUG)  # file gets everything
            logger.addHandler(file_handler)

        if console_handler:
            console_handler.setLevel(logging.INFO)  # console shows INFO+
            logger.addHandler(console_handler)

    def create_item(self, item: str) -> LK2Item:
        if self.is_progression_item(item):
            classification = ItemClassification.progression
        elif item == "Red Fairy":
            classification = ItemClassification.progression_deprioritized_skip_balancing
        elif self.options.combosanity.value and item in lost_kingdoms_2_cards and lost_kingdoms_2_cards[item]["hasCombo"]:
            classification = ItemClassification.progression_deprioritized_skip_balancing
        elif item in lost_kingdoms_2_key_items:
            classification = ItemClassification.useful
        else:
            classification = ItemClassification.filler
        return LK2Item(item, classification, self.item_name_to_id[item], self.player)

    def create_items(self) -> None:
        # Add items to the Multiworld.
        # If there are two of the same item, the item has to be twice in the pool.
        # Which items are added to the pool may depend on player options, e.g. custom win condition like triforce hunt.
        # Having an item in the start inventory won't remove it from the pool.
        # If you want to do that, use start_inventory_from_pool

        self.multiworld.get_location("Defeat the God of Harmony",self.player,).place_locked_item(LK2Item("Victory", ItemClassification.progression, None, self.player))
        self.multiworld.completion_condition[self.player] = lambda state: state.has("Victory", self.player)

        #ensure there is always at least 1 flyer, jumper, and smasher in the pool
        lost_kingdoms_2_cards_diluted = lost_kingdoms_2_cards.copy()
        lost_kingdoms_2_cards_diluted.pop(progression_flyer)
        lost_kingdoms_2_cards_diluted.pop(progression_jumper)
        lost_kingdoms_2_cards_diluted.pop(progression_stationary)
        lost_kingdoms_2_cards_diluted.pop("Stone Golem")
        lost_kingdoms_2_cards_diluted.pop("God of Destruction")
        num_of_cards = (len(lost_kingdoms_2_chests) - 5) + (self.options.combosanity.value * len(lost_kingdoms_2_combos)) + (self.options.shopsanity.value * len(lost_kingdoms_2_shop_purchases))
        random_cards = random.sample(list(lost_kingdoms_2_cards_diluted.keys()), num_of_cards)
        random_cards.append(progression_flyer)
        random_cards.append(progression_jumper)
        random_cards.append(progression_stationary)
        random_cards.append("Stone Golem")
        random_cards.append("God of Destruction")

        for key in lost_kingdoms_2_items:
            #Only include the randomly selected cards from random_cards.
            #This is because there are more cards than locations available.
            if (lost_kingdoms_2_items[key]["Type"] != "Card") | (key in random_cards):
                #Only include Red Fairies if fairysanity is enabled
                if (lost_kingdoms_2_items[key]["Type"] == "Red Fairy") and (self.options.fairysanity.value != 1):
                    continue
                for amount in range(lost_kingdoms_2_items[key]["Amount"]):
                    lk2_item = self.create_item(key)
                    self.multiworld.itempool.append(lk2_item)

        # itempool and number of locations should match up.
        # If this is not the case we want to fill the itempool with junk.
        junk = 0  # calculate this based on player options
        self.multiworld.itempool += [self.create_item("nothing") for _ in range(junk)]

    def is_progression_item(self, item: str) -> bool:
        return (item in [progression_flyer,"Stone Golem", progression_jumper, progression_stationary,
                         "God of Destruction", "Magic Boosters"]) or (item in lost_kingdoms_2_key_items)

    def generate_early(self) -> None:
        pass

    def create_regions(self):
        menu_region = Region("Menu", self.player, self.multiworld)
        self.multiworld.worlds[self.player].starting_region = "Menu"
        self.multiworld.regions.append(menu_region)

        for region_name in lost_kingdoms_2_regions:
            region = Region(region_name, self.player, self.multiworld)
            self.multiworld.regions.append(region)

        for key in lost_kingdoms_2_locations:
            if lost_kingdoms_2_locations[key]["type"] == "Red Fairy" and self.options.fairysanity.value==0:
                continue
            if lost_kingdoms_2_locations[key]["type"] == "Combo" and self.options.combosanity.value==0:
                continue
            if lost_kingdoms_2_locations[key]["type"] == "Bonus Draw":
                continue
            if lost_kingdoms_2_locations[key]["type"] == "Shop Purchase" and self.options.shopsanity.value==0:
                continue
            region = self.multiworld.get_region(lost_kingdoms_2_locations[key]["level"], self.player)
            location_data = LK2LocationData(self.location_name_to_id[key])
            location = LK2Location(self.player,key, region, location_data)
            if lost_kingdoms_2_locations[key].get("missable", 0) == 1:
                location.progress_type = LocationProgressType.EXCLUDED
            region.locations.append(location)

        victory_location = LK2Location(self.player, "Defeat the God of Harmony",self.multiworld.get_region("Royal Tower, Upper", self.player), None)
        self.multiworld.get_region("Royal Tower, Upper", self.player).locations.append(victory_location)

    def set_rules(self) -> None:
        for region_name in lost_kingdoms_2_regions:
            region = self.multiworld.get_region(region_name,self.player)
            match region_name:
                case "Nobleman's Residence":
                    previous_region = self.multiworld.get_region("Menu", self.player)
                    previous_region.connect(region, "Menu/Hub -> Nobleman's Residence")
                case "Bhashea High Road":
                    previous_region = self.multiworld.get_region("Nobleman's Residence",self.player)
                    previous_region.connect(region, previous_region.name + " -> " + region.name)
                case "Kadishu":
                    previous_region = self.multiworld.get_region("Bhashea High Road", self.player)
                    previous_region.connect(region, previous_region.name + " -> " + region.name)
                case "Kadishu Shop":
                    previous_region = self.multiworld.get_region("Kadishu", self.player)
                    previous_region.connect(region, previous_region.name + " -> " + region.name)
                case "Fairy House":
                    previous_region = self.multiworld.get_region("Gromtull Desert", self.player)
                    previous_region.connect(region, previous_region.name + " -> " + region.name, lambda state: state.has("Black Liquid", self.player))
                case "Bhashea Castle":
                    previous_region = self.multiworld.get_region("Bhashea High Road", self.player)
                    previous_region.connect(region, previous_region.name + " -> " + region.name, lambda state: state.has(progression_flyer, self.player) and state.has(progression_stationary, self.player))
                case "Gromtull Desert":
                    previous_region = self.multiworld.get_region("Kadishu", self.player)
                    previous_region.connect(region, previous_region.name + " -> " + region.name)
                case "Kendarie Fortress":
                    previous_region = self.multiworld.get_region("Bhashea High Road", self.player)
                    previous_region.connect(region, previous_region.name + " -> " + region.name)
                case "Runestone Caverns - Upper Chambers":
                    previous_region = self.multiworld.get_region("Kendarie Fortress", self.player)
                    previous_region.connect(region, previous_region.name + " -> " + region.name, lambda state: state.has("Red Key", self.player) and state.has("Blue Key", self.player))
                case "Runestone Caverns - Lower Chambers":
                    previous_region = self.multiworld.get_region("Runestone Caverns - Upper Chambers", self.player)
                    previous_region.connect(region, previous_region.name + " -> " + region.name, lambda state: state.has("Stone Golem", self.player))
                case "Ruldo Forest":
                    previous_region = self.multiworld.get_region("Runestone Caverns - Lower Chambers", self.player)
                    previous_region.connect(region, previous_region.name + " -> " + region.name)
                case "Sacred Battle Arena 1":
                    previous_region = self.multiworld.get_region("Ruldo Forest", self.player)
                    previous_region.connect(region, previous_region.name + " -> " + region.name)
                case "Sacred Battle Arena 2":
                    previous_region = self.multiworld.get_region("Sacred Battle Arena 1", self.player)
                    previous_region.connect(region, previous_region.name + " -> " + region.name)
                case "Fossil Boneyard":
                    previous_region = self.multiworld.get_region("Ruldo Forest", self.player)
                    previous_region.connect(region, previous_region.name + " -> " + region.name)
                case "Sarvan":
                    previous_region = self.multiworld.get_region("Fossil Boneyard", self.player)
                    previous_region.connect(region, previous_region.name + " -> " + region.name,lambda state: state.has(progression_jumper, self.player) and state.has("Magic Boosters", self.player))
                case "Holzogh Town":
                    previous_region = self.multiworld.get_region("Sarvan", self.player)
                    previous_region.connect(region, previous_region.name + " -> " + region.name,lambda state: state.has(progression_stationary, self.player))
                case "Plains of Rowahl":
                    previous_region = self.multiworld.get_region("Holzogh Town", self.player)
                    previous_region.connect(region, previous_region.name + " -> " + region.name)
                case "Alanjeh Castle":
                    previous_region = self.multiworld.get_region("Plains of Rowahl", self.player)
                    previous_region.connect(region, previous_region.name + " -> " + region.name,lambda state: state.has("Castle Gate Key", self.player))
                case "Royal Tower, Lower":
                    previous_region = self.multiworld.get_region("Alanjeh Castle", self.player)
                    previous_region.connect(region, previous_region.name + " -> " + region.name)
                case "Royal Tower, Middle":
                    previous_region = self.multiworld.get_region("Royal Tower, Lower", self.player)
                    previous_region.connect(region, previous_region.name + " -> " + region.name,lambda state: state.has("God of Destruction", self.player))
                case "Royal Tower, Upper":
                    previous_region = self.multiworld.get_region("Royal Tower, Middle", self.player)
                    previous_region.connect(region, previous_region.name + " -> " + region.name)
                case "Krasheen Mountains":
                    previous_region = self.multiworld.get_region("Royal Tower, Lower", self.player)
                    previous_region.connect(region, previous_region.name + " -> " + region.name)
                case "Grenfoel Cathedral":
                    previous_region = self.multiworld.get_region("Krasheen Mountains", self.player)
                    previous_region.connect(region, previous_region.name + " -> " + region.name)
                case "Temple of Sharacia":
                    previous_region = self.multiworld.get_region("Grenfoel Cathedral", self.player)
                    previous_region.connect(region, previous_region.name + " -> " + region.name)
                case "Grenfoel Cathedral Shop":
                    previous_region = self.multiworld.get_region("Grenfoel Cathedral", self.player)
                    previous_region.connect(region, previous_region.name + " -> " + region.name)
                case "Isamat Urbur":
                    previous_region = self.multiworld.get_region("Nobleman's Residence", self.player)
                    previous_region.connect(region, previous_region.name + " -> " + region.name, lambda state: state.has("Mysterious Key", self.player))
                case "Obenoix Gorge":
                    previous_region = self.multiworld.get_region("Holzogh Town", self.player)
                    previous_region.connect(region, previous_region.name + " -> " + region.name)
                case "Proving Grounds":
                    previous_region = self.multiworld.get_region("Royal Tower, Upper", self.player)
                    previous_region.connect(region, previous_region.name + " -> " + region.name)


        for location in self.multiworld.get_locations(self.player):
            match location.name :
                case "BHR - jump/flight chest" | "RC-UC - dragon chest 1" | "RC-UC - dragon chest 2" | "RF - flight/jump chest"\
                    | "FB - flight chest 1" | "FB - flight chest 2" | "RC-UC - Red Fairy near dragon" | "Oht Runestone":
                    add_rule(location,lambda state: state.has(progression_jumper, self.player) or state.has(progression_flyer, self.player))
                case "BHR - flight chest" | "GD - flight chest" | "KF - flight chest" | "RC-LC - high water chest flight"\
                    | "FB - flight chest 1" | "FB - flight chest 2" | "PoR - flight chest" | "PoR - flight chest 2" | "AC - flight chest"\
                    | "RTL - flight chest 1" | "RTL - flight chest 2" | "KM - black dragon's card" | "ToS - flight chest"\
                    | "OG - flight chest 1" | "OG - flight chest 2" | "OG - flight chest 3" | "BHR - Red Fairy across bridge"\
                    | "KF - Red Fairy fly across" | "RTL - Red Fairy flight" | "KM - Red Fairy cave 1" | "KM - Red Fairy broken bridge 1"\
                    | "KM - Red Fairy broken bridge 2":
                    add_rule(location, lambda state: state.has(progression_flyer,self.player))
                case "BC - east jump chest" | "RF - jump chest" | "FB - Red Fairy near jump pad" | "FB - Red Fairy jumping" | "FB - chest behind cultist" | "FB - chest 3"\
                    | "FB - Red Fairy near 2nd jump pad" | "FB - chest 4" | "FB - chest 5" | "FB - chest 6" | "FB - chest 7" | "Sarvan - jump chest"\
                    | "RTL - jump chest 1" | "RTL - jump chest 2" | "KM - chest 1" | "KM - chest 2" | "KM - chest 3"\
                    | "KM - chest 4" | "KM - chest 5" | "KM - chest 6" | "GD - Red Fairy jump" | "AC - Red Fairy jump"\
                    | "Fossil Head" | "Fossil Torso" | "Fossil Tail" | "Fossil Rt Wing" | "Fossil Lt Wing" | "Fossil Rt Arm"\
                    | "Fossil Lt Arm" | "Fossil Lt Leg" | "Ebin Runestone":
                    add_rule(location, lambda state: state.has(progression_jumper, self.player) and state.has("Magic Boosters", self.player))
                case "BC - east jump chest" | "RC-UC - chest behind ice 1" | "RC-UC - chest behind ice 2" | "RTM - breakable wall chest 1"\
                    | "RTM - breakable wall chest 2" | "OG - chest behind ice" | "BC - Red Fairy wall break rubble" \
                    | "RTM - Red Fairy breakable wall 1" | "RTM - Red Fairy breakable wall 2":
                    add_rule(location, lambda state: state.has("Stone Golem", self.player) and state.has("Magic Boosters", self.player))
                case "SBA2 - defeat Leod" | "SBA2 - defeat Thalnos" | "SBA2 - defeat Katia" | "SBA2 - Red Fairy Queen Katia":
                    add_rule(location, lambda state: state.can_reach_region("Royal Tower, Upper", self.player))
                case "Kadishu - garbage collection 2":
                    add_rule(location, lambda state: state.can_reach_region("Ruldo Forest", self.player))
                case "Kadishu - garbage collection 3":
                    add_rule(location, lambda state: state.can_reach_region("Royal Tower, Lower", self.player))
                case "Sarvan - caged chest":
                    add_rule(location, lambda state: state.has(progression_flyer, self.player))
                    location.progress_type = LocationProgressType.EXCLUDED
                case "Sarvan - caged chest 2":
                    add_rule(location, lambda state: state.has(progression_stationary, self.player))
                    location.progress_type = LocationProgressType.EXCLUDED
                case "Sarvan - puzzle chest":
                    add_rule(location, lambda state: state.has(progression_stationary, self.player))
                case "HT - fountain card":
                    add_rule(location, lambda state: state.has("Key to Fountain", self.player))
                case "PoR - chest 6" | "PoR - chest 7" | "PoR - GoD card":
                    add_rule(location, lambda state: state.has("Jewel of Alanjeh", self.player))
                case "ToS - help valkyrie" | "ToS - help ashura" | "RC-UC - talk to Sol":
                    location.progress_type = LocationProgressType.EXCLUDED
                case "NR - Red Fairy sculpture" | "NR - Red Fairy central" | "NR - Red Fairy office" | "Keil Runestone":
                    add_rule(location, lambda state: state.has("Mysterious Key", self.player))
                case "BHR - Red Fairy across bridge in rubble" | "BHR - Red Fairy chaos knight":
                    add_rule(location, lambda state: state.has(progression_stationary, self.player))
                    add_rule(location, lambda state: state.has(progression_flyer, self.player))
                case "KF - Red Fairy past blue gate" | "KF - Red Fairy near Mechapult":
                    add_rule(location, lambda state: state.has(progression_flyer, self.player) or state.has("Blue Key", self.player))
                case "PoR - Red Fairy past gate" | "PoR - chest 4" | "PoR - chest 5" | "Elise Runestone":
                    add_rule(location, lambda state: state.has("Castle Gate Key", self.player))
                case "Red Key" | "KF - chest 2":
                    add_rule(location, lambda state: state.has("Blue Key", self.player))
                case "KF - chest behind green door":
                    add_rule(location, lambda state: state.has("Green Key", self.player))
                    add_rule(location, lambda state: state.has(progression_flyer, self.player) or state.has("Blue Key",self.player))
                case "KF - chest 4" | "KF - chest 5":
                    add_rule(location,lambda state: state.has("Blue Key", self.player) and state.has("Red Key", self.player))
                case "Green Key":
                    add_rule(location, lambda state: state.has("Red Key", self.player))
                case "Black Liquid":
                    add_rule(location, lambda state: state.has("Bottle", self.player))
                case "GD - Red Fairy Jarvi 1" | "GD - Red Fairy Jarvi 2" | "GD - jarvi cave chest 1" | "GD - jarvi cave chest 2":
                    add_rule(location, lambda state: state.has("Black Liquid", self.player))
                case "Stone of Sealing":
                    add_rule(location, lambda state: state.has("Eno Runestone", self.player) and state.has("Oht Runestone", self.player) \
                             and state.has("Elise Runestone", self.player) and state.has("Olf Runestone", self.player) \
                             and state.has("Ebin Runestone", self.player) and state.has("Keil Runestone", self.player) \
                             and state.has("Nebeth Runestone", self.player))
                case "FH - collect 1 fairy":
                    add_rule(location, lambda state: state.has("Red Fairy", self.player, 1))
                case "FH - collect 10 fairies":
                    add_rule(location, lambda state: state.has("Red Fairy", self.player, 10))
                case "FH - collect 20 fairies":
                    add_rule(location, lambda state: state.has("Red Fairy", self.player, 20))
                case "FH - collect 30 fairies":
                    add_rule(location, lambda state: state.has("Red Fairy", self.player, 30))
                case "FH - collect 50 fairies":
                    add_rule(location, lambda state: state.has("Red Fairy", self.player, 50))
                case "FH - collect 70 fairies":
                    add_rule(location, lambda state: state.has("Red Fairy", self.player, 70))
                case "FH - collect 80 fairies":
                    add_rule(location, lambda state: state.has("Red Fairy", self.player, 80))
                case "FH - collect 90 fairies":
                    add_rule(location, lambda state: state.has("Red Fairy", self.player, 90))
                case "FH - collect 100 fairies":
                    add_rule(location, lambda state: state.has("Red Fairy", self.player, 100))
                case "FB - zombie dragon chest":
                    add_rule(location, lambda state: state.has("Fossil Head", self.player) and state.has("Fossil Torso", self.player) \
                             and state.has("Fossil Tail", self.player) and state.has("Fossil Rt Wing", self.player) \
                             and state.has("Fossil Lt Wing", self.player) and state.has("Fossil Rt Arm", self.player) \
                             and state.has("Fossil Lt Arm", self.player) and state.has("Fossil Rt Leg", self.player) \
                             and state.has("Fossil Lt Leg", self.player))
                case "Combo - Triple Hagan":
                    add_rule(location, lambda state: state.has("Rock Hagan", self.player))
                    add_rule(location, lambda state: state.has("Bum Hagan", self.player))
                    add_rule(location, lambda state: state.has("Storm Hagan", self.player))
                case "Combo - Ultimate Pasta":
                    add_rule(location, lambda state: state.has("Red Dragon", self.player))
                    add_rule(location, lambda state: state.has("Brine Dragon", self.player))
                    add_rule(location, lambda state: state.has("Green Dragon", self.player))
                    add_rule(location, lambda state: state.has("Amber Dragon", self.player))
                case "Combo - Lizard War":
                    add_rule(location, lambda state: state.has("Red Lizard", self.player))
                    add_rule(location, lambda state: state.has("Venom Lizard", self.player))
                    add_rule(location, lambda state: state.has("Lizardman", self.player))
                    add_rule(location, lambda state: state.has("Basilisk", self.player))
                case "Combo - Rotary Death":
                    add_rule(location, lambda state: state.has("Carbuncle", self.player))
                    add_rule(location, lambda state: state.has("Decoy Pillar", self.player))
                case "Combo - Rocky Forecast":
                    add_rule(location, lambda state: state.has("Stone Head", self.player, 3))
                case "Combo - Sir Spear-A-Lot":
                    add_rule(location, lambda state: state.has("Ghost Armor", self.player))
                    add_rule(location, lambda state: state.has("Chaos Knight", self.player))
                case "Combo - Temper Tantrum":
                    add_rule(location, lambda state: state.has("Fire Golem", self.player))
                    add_rule(location, lambda state: state.has("Ice Golem", self.player))
                case "Combo - Goblin Guts":
                    add_rule(location, lambda state: state.has("Hobgoblin", self.player))
                    add_rule(location, lambda state: state.has("Goblin Lord", self.player))
                case "Combo - Lethal Orbit":
                    add_rule(location, lambda state: state.has("Carbuncle", self.player))
                    add_rule(location, lambda state: state.has("Juggernaut", self.player))
                    add_rule(location, lambda state: state.has("Whip Worm", self.player))
                case "Combo - Crystal Rage":
                    add_rule(location, lambda state: state.has("Dragon Knight", self.player, 2))
                    add_rule(location, lambda state: state.has("Crystal Rose", self.player))
                case "Combo - Mandragora Mixer":
                    add_rule(location, lambda state: state.has("Mandragora", self.player))
                    add_rule(location, lambda state: state.has("Mandra Dancer", self.player))
                    add_rule(location, lambda state: state.has("King Mandragora", self.player))
                case "Combo - Rust and Roll!":
                    add_rule(location, lambda state: state.has("Acid Dragon", self.player))
                    add_rule(location, lambda state: state.has("Pixie", self.player))
                case "Combo - EconoMagic":
                    add_rule(location, lambda state: state.has("Panther Mage", self.player))
                    add_rule(location, lambda state: state.has("Tiger Mage", self.player))
                case "Combo - Just Visiting":
                    add_rule(location, lambda state: state.has("Doppelganger", self.player, 2))
                case "Combo - Djinn and Bear It":
                    add_rule(location, lambda state: state.has("Efreet", self.player))
                    add_rule(location, lambda state: state.has("Dao", self.player))
                    add_rule(location, lambda state: state.has("Marid", self.player))
                case "Combo - Triple Kamikaze":
                    add_rule(location, lambda state: state.has("Flying Ray", self.player))
                    add_rule(location, lambda state: state.has("Dark Raven", self.player, 2))
                case "Combo - One Way Ticket":
                    add_rule(location, lambda state: state.has("Valkyrie", self.player))
                    add_rule(location, lambda state: state.has("Thanatos", self.player))
                case "Combo - The Master's Four":
                    add_rule(location, lambda state: state.has("Fenril", self.player))
                    add_rule(location, lambda state: state.has("Behemoth", self.player))
                    add_rule(location, lambda state: state.has("Demon Fox", self.player))
                    add_rule(location, lambda state: state.has("Ice Golem", self.player))
                case "Combo - The Big Save":
                    add_rule(location, lambda state: state.has("White Tiger", self.player))
                    add_rule(location, lambda state: state.has("Golden Phoenix", self.player))
                    add_rule(location, lambda state: state.has("Great Turtle", self.player))
                    add_rule(location, lambda state: state.has("Blue Dragon", self.player))
                case "Combo - Brutal Nightmare":
                    add_rule(location, lambda state: state.has("Succubus", self.player))
                    add_rule(location, lambda state: state.has("Incubus", self.player))
                case "Combo - Phantom Bulldozer":
                    add_rule(location, lambda state: state.has("Wraith", self.player))
                    add_rule(location, lambda state: state.has("Lich", self.player))
                    add_rule(location, lambda state: state.has("Sekmet", self.player))
                case "Combo - Living Large":
                    add_rule(location, lambda state: state.has("Phoenix", self.player))
                    add_rule(location, lambda state: state.has("Golden Phoenix", self.player))
                case "Combo - Elemental Victory":
                    add_rule(location, lambda state: state.has("Dryad", self.player))
                    add_rule(location, lambda state: state.has("Gnome", self.player))
                    add_rule(location, lambda state: state.has("Salamander", self.player))
                    add_rule(location, lambda state: state.has("Undine", self.player))
                case "Combo - Skullapalooza":
                    add_rule(location, lambda state: state.has("Ice Skeleton", self.player))
                    add_rule(location, lambda state: state.has("Demon Skeleton", self.player))
                    add_rule(location, lambda state: state.has("Steel Skeleton", self.player))
                    add_rule(location, lambda state: state.has("Skeleton", self.player))
                case "Combo - Stone Cold Sniper":
                    add_rule(location, lambda state: state.has("Stone Golem", self.player))
                    add_rule(location, lambda state: state.has("Archer Tree", self.player, 2))
                case "Combo - Mega Tremor":
                    add_rule(location, lambda state: state.has("Elephant", self.player))
                    add_rule(location, lambda state: state.has("Elephant King", self.player))
                case "Combo - Time Out!":
                    add_rule(location, lambda state: state.has("Running Bird", self.player))
                    add_rule(location, lambda state: state.has("Gold Butterfly", self.player))
                case "Combo - Hell Hole":
                    add_rule(location, lambda state: state.has("Gravity Pillar", self.player))
                    add_rule(location, lambda state: state.has("Doppelganger", self.player))
                case "Combo - Spiritual Force":
                    add_rule(location, lambda state: state.has("Earth Elemental", self.player))
                    add_rule(location, lambda state: state.has("Fire Elemental", self.player))
                    add_rule(location, lambda state: state.has("Water Elemental", self.player))
                    add_rule(location, lambda state: state.has("Wood Elemental", self.player))
                case "Combo - Air Raid":
                    add_rule(location, lambda state: state.has("Treant", self.player))
                    add_rule(location, lambda state: state.has("Dark Raven", self.player, 2))
                case "Combo - Tech Support!":
                    add_rule(location, lambda state: state.has("Acid Cloud", self.player))
                    add_rule(location, lambda state: state.has("Gold Butterfly", self.player))
                case "Combo - Song of Hades":
                    add_rule(location, lambda state: state.has("Mermaid", self.player))
                    add_rule(location, lambda state: state.has("Siren", self.player))
                case "Combo - Hearing Aid":
                    add_rule(location, lambda state: state.has("Sphinx", self.player))
                    add_rule(location, lambda state: state.has("Mummy", self.player, 2))
                case "Combo - Uber Vampire Root":
                    add_rule(location, lambda state: state.has("Vampire Bush", self.player, 2))
                case "Combo - Mo Better Moray":
                    add_rule(location, lambda state: state.has("Fire Moray", self.player))
                    add_rule(location, lambda state: state.has("Water Moray", self.player))
                    add_rule(location, lambda state: state.has("Earth Moray", self.player))
                case "Combo - Prayer of the Wise":
                    add_rule(location, lambda state: state.has("Sea Monk", self.player))
                    add_rule(location, lambda state: state.has("Mind Flayer", self.player))
                case "Combo - Hawging the Action":
                    add_rule(location, lambda state: state.has("Orc", self.player, 4))
                case "Combo - Stone All Around":
                    add_rule(location, lambda state: state.has("Cockatrice", self.player, 2))
                case "Combo - Tender Mercy":
                    add_rule(location, lambda state: state.has("Fairy", self.player))
                    add_rule(location, lambda state: state.has("Rheebus", self.player))
                case "Combo - Green Guardian":
                    add_rule(location, lambda state: state.has("Elf", self.player))
                    add_rule(location, lambda state: state.has("Elf Lord", self.player))
                    add_rule(location, lambda state: state.has("Dark Elf", self.player))

    def fill_slot_data(self) -> dict:
        #self.debug_regions()
        #self.debug_all_locations()
        return {
            "Seed": self.multiworld.seed,
            "Slot": self.player,
            "Name": self.player_name,
            "win_condition": self.options.win_condition.value,
            "fairysanity": self.options.fairysanity.value,
            "shopsanity": self.options.shopsanity.value,
            "combosanity": self.options.combosanity.value,
            "open_world": self.options.open_world.value,
            "death_link": self.options.death_link.value,
            "randomize_starting_deck": self.options.randomize_starting_deck.value,
            "randomize_shop_contents": self.options.randomize_shop_contents.value,
            "randomize_bonus_draws": self.options.randomize_bonus_draws.value,
        }

    def debug_regions(self):
        state = CollectionState(self.multiworld)

        for item in self.multiworld.itempool:
            if item.player == self.player:

                state.collect(item, True)

        state.update_reachable_regions(self.player)

        reachable = state.reachable_regions[self.player]
        unreachable = [r.name for r in self.multiworld.regions if r.player == self.player and r not in reachable]

        logger.debug(f"UNREACHABLE WITH ALL ITEMS: {unreachable}")

    def debug_all_locations(self):

        logger.debug("=== Full Location -> Item Mapping ===")
        for region in self.multiworld.regions:
            if region.player != self.player:
                continue
            for location in region.locations:
                item_name = getattr(location.item, "name", None)
                item_classification = getattr(location.item, "classification", None)
                if not item_name:
                    item_name = getattr(location, "item_name", None)
                logger.debug(f"Location '{location.name}' (Region: '{region.name}') contains: '{item_name or 'None'}' {item_classification}")

    def generate_output(self, output_directory: str):
        # Output seed name and slot number to seed RNG in randomizer client
        # noinspection PyDictCreation
        output_data = {
            "Seed": self.multiworld.seed,
            "Slot": self.player,
            "Name": self.player_name,
            #"Locations":{},
            AP_WORLD_VERSION_NAME: CLIENT_VERSION
        }

        # Outputs the plando details to our expected output file
        # Create the output path based on the current player + expected patch file ending.
        patch_path = os.path.join(output_directory, f"{self.multiworld.get_out_file_name_base(self.player)}"
                                                    f"{LK2PlayerContainer.patch_file_ending}")
        # Create a zip (container) that will contain all the necessary output files for us to use during patching.
        lk2_container = LK2PlayerContainer(output_data, patch_path, self.multiworld.player_name[self.player], self.player)
        # Write the expected output zip container to the Generated Seed folder.
        lk2_container.write()


