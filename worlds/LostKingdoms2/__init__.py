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

rng_seed = None

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
        elif item == "Progressive Player Level" or item=="Progressive Attribute Proficiency":
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
        match self.options.win_condition.value:
            case 0:
                self.multiworld.get_location("Defeat the God of Harmony",self.player,).place_locked_item(LK2Item("Victory", ItemClassification.progression, None, self.player))
            case 1:
                self.multiworld.get_location("Defeat the Emperor", self.player, ).place_locked_item(LK2Item("Victory", ItemClassification.progression, None, self.player))
            case 2:
                self.multiworld.get_location("Collect "+str(self.options.collect_red_fairies_amount.value)+" Red Fairies", self.player, ).place_locked_item(LK2Item("Victory", ItemClassification.progression, None, self.player))
        self.multiworld.completion_condition[self.player] = lambda state: state.has("Victory", self.player)

        #ensure GoD, stone golem, and all flyers/jumpers are in the pool
        lost_kingdoms_2_filler_cards = []
        lost_kingdoms_2_progression_cards = []
        multiplier = 1
        for key in lost_kingdoms_2_cards:
            lk2_item = self.create_item(key)
            if lk2_item.classification == ItemClassification.filler:
                lost_kingdoms_2_items[key]["Amount"] = 0
                lost_kingdoms_2_filler_cards.append(key)
            else:
                lost_kingdoms_2_progression_cards.append(key)
        num_of_random_cards = len(lost_kingdoms_2_chests) + (self.options.combosanity.value * len(lost_kingdoms_2_combos)) + (self.options.shopsanity.value * len(lost_kingdoms_2_shop_purchases)) - len(lost_kingdoms_2_progression_cards) - 19 * self.options.progressive_leveling.value - 34 * self.options.progressive_attribute_proficiencies.value + (self.options.enemysanity.value * len(lost_kingdoms_2_enemies))
        #Ensure there is always enough filler cards by doubling the pool until it's large enough
        while len(lost_kingdoms_2_filler_cards)*multiplier < num_of_random_cards:
            for key in lost_kingdoms_2_filler_cards:
                lost_kingdoms_2_items[key]["Amount"] += 1
            multiplier+=1
        random_cards = random.sample(lost_kingdoms_2_filler_cards, num_of_random_cards-len(lost_kingdoms_2_filler_cards)*(multiplier-1))
        for key in random_cards:
            lost_kingdoms_2_items[key]["Amount"] += 1


        for key in lost_kingdoms_2_items:
            #Only include the randomly selected cards from random_cards.
            #This is because there are more cards than locations available.
            #Only include Red Fairies if fairysanity is enabled
            if (lost_kingdoms_2_items[key]["Type"] == "Red Fairy") and (self.options.fairysanity.value != 1):
                continue
            if (lost_kingdoms_2_items[key]["Type"] == "Progressive Player Level") and (self.options.progressive_leveling.value != 1):
                continue
            if (lost_kingdoms_2_items[key]["Type"] == "Progressive Attribute Proficiency") and (self.options.progressive_attribute_proficiencies.value != 1):
                continue
            for amount in range(lost_kingdoms_2_items[key]["Amount"]):
                lk2_item = self.create_item(key)
                self.multiworld.itempool.append(lk2_item)

        # itempool and number of locations should match up.
        # If this is not the case we want to fill the itempool with junk.
        junk = 0  # calculate this based on player options
        self.multiworld.itempool += [self.create_item("nothing") for _ in range(junk)]

    def is_progression_item(self, item: str) -> bool:
        if item in ["Stone Golem", "God of Destruction", "Magic Boosters"]:
            return True
        elif item in lost_kingdoms_2_flying_cards:
            return True
        elif item in lost_kingdoms_2_jumping_cards:
            return True
        elif item in lost_kingdoms_2_key_items:
            return True

    def generate_early(self) -> None:
        re_gen_passthrough = getattr(self.multiworld, "re_gen_passthrough", {})
        logger.debug(f"re_gen_passthrough contents: {re_gen_passthrough}")
        logger.debug(f"self.game = {self.game!r}")
        if re_gen_passthrough and self.game in re_gen_passthrough:
            slot_data: dict[str, typing.Any] = re_gen_passthrough[self.game]
            global rng_seed
            rng_seed = slot_data["Seed"]
            logger.debug("Setting Universal Tracking seed to: " + str(rng_seed))

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
            if lost_kingdoms_2_locations[key]["type"] == "Enemysanity" and self.options.enemysanity.value==0:
                continue
            region = self.multiworld.get_region(lost_kingdoms_2_locations[key]["level"], self.player)
            location_data = LK2LocationData(self.location_name_to_id[key])
            location = LK2Location(self.player,key, region, location_data)
            if lost_kingdoms_2_locations[key].get("missable", 0) == 1:
                location.progress_type = LocationProgressType.EXCLUDED
            region.locations.append(location)

        match self.options.win_condition.value:
            case 0:
                victory_location = LK2Location(self.player, "Defeat the God of Harmony",self.multiworld.get_region("Royal Tower, Upper", self.player), None)
                self.multiworld.get_region("Royal Tower, Upper", self.player).locations.append(victory_location)
            case 1:
                victory_location = LK2Location(self.player, "Defeat the Emperor",self.multiworld.get_region("Proving Grounds", self.player), None)
                self.multiworld.get_region("Proving Grounds", self.player).locations.append(victory_location)
            case 2:
                victory_location = LK2Location(self.player, "Collect "+str(self.options.collect_red_fairies_amount.value)+" Red Fairies",self.multiworld.get_region("Proving Grounds", self.player), None)
                self.multiworld.get_region("Menu", self.player).locations.append(victory_location)
                victory_location.access_rule = lambda state: state.has("Red Fairy", self.player,self.options.collect_red_fairies_amount.value)


    def set_rules(self) -> None:

        exit_rules = {
                "Nobleman's Residence Exit 2": lambda state: state.has("Mysterious Key", self.player),
                "Bhashea High Road Exit 3": lambda state: state.has_any(lost_kingdoms_2_flying_cards, self.player) or state.has_any(lost_kingdoms_2_jumping_cards, self.player),
                "Gromtull Desert Exit 1": lambda state: state.has("Black Liquid", self.player),
                "Kendarie Fortress Exit 1": lambda state: state.has("Red Key", self.player) and state.has("Blue Key",self.player),
                "Runestone Caverns - Upper Chambers Exit 1": lambda state: state.has("Stone Golem", self.player),
                "Krasheen Mountains Exit 1": lambda state: state.has_any(lost_kingdoms_2_flying_cards, self.player),
                "Fossil Boneyard Exit 1": lambda state: state.has_any(lost_kingdoms_2_jumping_cards,self.player) and state.has("Magic Boosters",self.player),
                "Plains of Rowahl Exit 1": lambda state: state.has("Castle Gate Key", self.player),
                "Holzogh Town Exit 2": lambda state: state.can_reach_region("Royal Tower, Lower", self.player)
            }

        if self.options.randomize_levels.value:
            global rng_seed
            if rng_seed is None:
                rng_seed = self.multiworld.seed
            random.seed(rng_seed + 4)
            level_ordering = randomize_exits()
            logger.debug("Level ordering is: " + str(level_ordering))
            inverted_ordering = {dest: exit_key for exit_key, dest in level_ordering.items()}
        else:
            inverted_ordering = {dest: exit_key for exit_key, dest in lost_kingdoms_2_region_exits.items()}

        for region_name in lost_kingdoms_2_regions:
            region = self.multiworld.get_region(region_name, self.player)
            match region_name:
                case "Nobleman's Residence":
                    previous_region = self.multiworld.get_region("Menu", self.player)
                    previous_region.connect(region, "Nobleman's Residence")
                case "Bhashea High Road":
                    exit_key = inverted_ordering[region_name]
                    previous_region = self.multiworld.get_region(source_of(exit_key), self.player)
                    previous_region.connect(region, f"{region.name}", exit_rules.get(exit_key))
                case "Isamat Urbur":
                    exit_key = inverted_ordering[region_name]
                    previous_region = self.multiworld.get_region(source_of(exit_key), self.player)
                    previous_region.connect(region, f"{region.name}", exit_rules.get(exit_key))
                case "Kendarie Fortress":
                    exit_key = inverted_ordering[region_name]
                    previous_region = self.multiworld.get_region(source_of(exit_key), self.player)
                    previous_region.connect(region, f"{region.name}", exit_rules.get(exit_key))
                case "Kadishu":
                    exit_key = inverted_ordering[region_name]
                    previous_region = self.multiworld.get_region(source_of(exit_key), self.player)
                    previous_region.connect(region, f"{region.name}", exit_rules.get(exit_key))
                case "Bhashea Castle":
                    exit_key = inverted_ordering[region_name]
                    previous_region = self.multiworld.get_region(source_of(exit_key), self.player)
                    previous_region.connect(region, f"{region.name}", exit_rules.get(exit_key))
                case "Kadishu Shop":
                    exit_key = inverted_ordering[region_name]
                    previous_region = self.multiworld.get_region(source_of(exit_key), self.player)
                    previous_region.connect(region, f"{region.name}", exit_rules.get(exit_key))
                case "Fairy House":
                    exit_key = inverted_ordering[region_name]
                    previous_region = self.multiworld.get_region(source_of(exit_key), self.player)
                    previous_region.connect(region, f"{region.name}", exit_rules.get(exit_key))
                case "Gromtull Desert":
                    exit_key = inverted_ordering[region_name]
                    previous_region = self.multiworld.get_region(source_of(exit_key), self.player)
                    previous_region.connect(region, f"{region.name}", exit_rules.get(exit_key))
                case "Runestone Caverns - Upper Chambers":
                    exit_key = inverted_ordering[region_name]
                    previous_region = self.multiworld.get_region(source_of(exit_key), self.player)
                    previous_region.connect(region, f"{region.name}", exit_rules.get(exit_key))
                case "Runestone Caverns - Lower Chambers":
                    exit_key = inverted_ordering[region_name]
                    previous_region = self.multiworld.get_region(source_of(exit_key), self.player)
                    previous_region.connect(region, f"{region.name}", exit_rules.get(exit_key))
                case "Ruldo Forest":
                    exit_key = inverted_ordering[region_name]
                    previous_region = self.multiworld.get_region(source_of(exit_key), self.player)
                    previous_region.connect(region, f"{region.name}", exit_rules.get(exit_key))
                case "Sacred Battle Arena 1":
                    exit_key = inverted_ordering[region_name]
                    previous_region = self.multiworld.get_region(source_of(exit_key), self.player)
                    previous_region.connect(region, f"{region.name}", exit_rules.get(exit_key))
                case "Sacred Battle Arena 2":
                    previous_region = self.multiworld.get_region("Sacred Battle Arena 1", self.player)
                    previous_region.connect(region, f"{region.name}")
                case "Fossil Boneyard":
                    exit_key = inverted_ordering[region_name]
                    previous_region = self.multiworld.get_region(source_of(exit_key), self.player)
                    previous_region.connect(region, f"{region.name}", exit_rules.get(exit_key))
                case "Sarvan":
                    exit_key = inverted_ordering[region_name]
                    previous_region = self.multiworld.get_region(source_of(exit_key), self.player)
                    previous_region.connect(region, f"{region.name}", exit_rules.get(exit_key))
                case "Holzogh Town":
                    exit_key = inverted_ordering[region_name]
                    previous_region = self.multiworld.get_region(source_of(exit_key), self.player)
                    previous_region.connect(region, f"{region.name}", exit_rules.get(exit_key))
                case "Plains of Rowahl":
                    exit_key = inverted_ordering[region_name]
                    previous_region = self.multiworld.get_region(source_of(exit_key), self.player)
                    previous_region.connect(region, f"{region.name}", exit_rules.get(exit_key))
                case "Alanjeh Castle":
                    exit_key = inverted_ordering[region_name]
                    previous_region = self.multiworld.get_region(source_of(exit_key), self.player)
                    previous_region.connect(region, f"{region.name}", exit_rules.get(exit_key))
                case "Krasheen Mountains":
                    exit_key = inverted_ordering[region_name]
                    previous_region = self.multiworld.get_region(source_of(exit_key), self.player)
                    previous_region.connect(region, f"{region.name}", exit_rules.get(exit_key))
                case "Obenoix Gorge":
                    exit_key = inverted_ordering[region_name]
                    previous_region = self.multiworld.get_region(source_of(exit_key), self.player)
                    previous_region.connect(region, f"{region.name}", exit_rules.get(exit_key))
                case "Grenfoel Cathedral":
                    exit_key = inverted_ordering[region_name]
                    previous_region = self.multiworld.get_region(source_of(exit_key), self.player)
                    previous_region.connect(region, f"{region.name}", exit_rules.get(exit_key))
                case "Temple of Sharacia":
                    exit_key = inverted_ordering[region_name]
                    previous_region = self.multiworld.get_region(source_of(exit_key), self.player)
                    previous_region.connect(region, f"{region.name}", exit_rules.get(exit_key))
                case "Grenfoel Cathedral Shop":
                    exit_key = inverted_ordering[region_name]
                    previous_region = self.multiworld.get_region(source_of(exit_key), self.player)
                    previous_region.connect(region, f"{region.name}", exit_rules.get(exit_key))
                case "Royal Tower, Lower":
                    previous_region = self.multiworld.get_region("Alanjeh Castle", self.player)
                    previous_region.connect(region, f"{region.name}")
                case "Royal Tower, Middle":
                    previous_region = self.multiworld.get_region("Royal Tower, Lower", self.player)
                    previous_region.connect(region, f"{region.name}", lambda state: state.has("God of Destruction", self.player))
                case "Royal Tower, Upper":
                    previous_region = self.multiworld.get_region("Royal Tower, Middle", self.player)
                    previous_region.connect(region, f"{region.name}")
                case "Proving Grounds":
                    previous_region = self.multiworld.get_region("Royal Tower, Upper", self.player)
                    previous_region.connect(region, f"{region.name}")

        for location in self.multiworld.get_locations(self.player):
            if location.name in lost_kingdoms_2_locations:
                rule_key = lost_kingdoms_2_locations[location.name].get("rule")
                if rule_key in lost_kingdoms_2_logic:
                    logic_func = lost_kingdoms_2_logic[rule_key]

                    # Use 'l_func=logic_func' to capture the current function in the local scope
                    add_rule(location, lambda state, l_func=logic_func: l_func(state, self.player))

            # Specific option override for Sacred Battle Arena
            if self.options.exclude_sacred_battle_arena_checks.value and "Sacred Battle Arena" in location.name:
                location.progress_type = LocationProgressType.EXCLUDED

            match location.name:
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
                    add_rule(location, lambda state: state.has("Stone Head", self.player)) #3
                    add_rule(location, lambda state: state.can_reach_region("Kadishu Shop", self.player) or state.can_reach_region("Grenfoel Cathedral Shop", self.player))
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
                    add_rule(location, lambda state: state.has("Dragon Knight", self.player)) #2
                    add_rule(location, lambda state: state.has("Crystal Rose", self.player))
                    add_rule(location, lambda state: state.can_reach_region("Kadishu Shop", self.player) or state.can_reach_region("Grenfoel Cathedral Shop", self.player))
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
                    add_rule(location, lambda state: state.has("Doppelganger", self.player)) #2
                    add_rule(location, lambda state: state.has("God of Destruction", self.player))
                    add_rule(location, lambda state: state.can_reach_region("Kadishu Shop", self.player) or state.can_reach_region("Grenfoel Cathedral Shop", self.player))
                case "Combo - Djinn and Bear It":
                    add_rule(location, lambda state: state.has("Efreet", self.player))
                    add_rule(location, lambda state: state.has("Dao", self.player))
                    add_rule(location, lambda state: state.has("Marid", self.player))
                case "Combo - Triple Kamikaze":
                    add_rule(location, lambda state: state.has("Flying Ray", self.player))
                    add_rule(location, lambda state: state.has("Dark Raven", self.player)) #2
                    add_rule(location, lambda state: state.can_reach_region("Kadishu Shop", self.player) or state.can_reach_region("Grenfoel Cathedral Shop", self.player))
                case "Combo - One Way Ticket":
                    add_rule(location, lambda state: state.has("Valkyrie", self.player))
                    add_rule(location, lambda state: state.has("Thanatos", self.player))
                case "Combo - The Masters Four":
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
                case "Combo - Phantom BullDozer":
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
                    add_rule(location, lambda state: state.has("Archer Tree", self.player)) #2
                    add_rule(location, lambda state: state.can_reach_region("Kadishu Shop", self.player) or state.can_reach_region("Grenfoel Cathedral Shop", self.player))
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
                    add_rule(location, lambda state: state.has("Dark Raven", self.player)) #2
                    add_rule(location, lambda state: state.can_reach_region("Kadishu Shop", self.player) or state.can_reach_region("Grenfoel Cathedral Shop", self.player))
                case "Combo - Tech Support!":
                    add_rule(location, lambda state: state.has("Acid Cloud", self.player))
                    add_rule(location, lambda state: state.has("Gold Butterfly", self.player))
                case "Combo - Song of Hades":
                    add_rule(location, lambda state: state.has("Mermaid", self.player))
                    add_rule(location, lambda state: state.has("Siren", self.player))
                case "Combo - Hearing Aid":
                    add_rule(location, lambda state: state.has("Sphinx", self.player))
                    add_rule(location, lambda state: state.has("Mummy", self.player)) #2
                    add_rule(location, lambda state: state.can_reach_region("Kadishu Shop", self.player) or state.can_reach_region("Grenfoel Cathedral Shop", self.player))
                case "Combo - Uber Vampire Root":
                    add_rule(location, lambda state: state.has("Vampire Bush", self.player)) #2
                    add_rule(location, lambda state: state.can_reach_region("Kadishu Shop", self.player) or state.can_reach_region("Grenfoel Cathedral Shop", self.player))
                case "Combo - Mo Better Moray":
                    add_rule(location, lambda state: state.has("Fire Moray", self.player))
                    add_rule(location, lambda state: state.has("Water Moray", self.player))
                    add_rule(location, lambda state: state.has("Earth Moray", self.player))
                case "Combo - Prayer of the Wise":
                    add_rule(location, lambda state: state.has("Sea Monk", self.player))
                    add_rule(location, lambda state: state.has("Mind Flayer", self.player))
                case "Combo - Hawging the Action":
                    add_rule(location, lambda state: state.has("Orc", self.player)) #4
                    add_rule(location, lambda state: state.can_reach_region("Kadishu Shop", self.player) or state.can_reach_region("Grenfoel Cathedral Shop", self.player))
                case "Combo - Stone All Around":
                    add_rule(location, lambda state: state.has("Cockatrice", self.player)) #2
                    add_rule(location, lambda state: state.can_reach_region("Kadishu Shop", self.player) or state.can_reach_region("Grenfoel Cathedral Shop", self.player))
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
            "collect_red_fairies_amount": self.options.collect_red_fairies_amount.value,
            "fairysanity": self.options.fairysanity.value,
            "shopsanity": self.options.shopsanity.value,
            "combosanity": self.options.combosanity.value,
            "enemysanity": self.options.enemysanity.value,
            "open_world": self.options.open_world.value,
            "exclude_sacred_battle_arena_checks": self.options.exclude_sacred_battle_arena_checks.value,
            "death_link": self.options.death_link.value,
            "randomize_starting_deck": self.options.randomize_starting_deck.value,
            "randomize_shop_contents": self.options.randomize_shop_contents.value,
            "randomize_bonus_draws": self.options.randomize_bonus_draws.value,
            "randomize_magic_stone_costs": self.options.randomize_magic_stone_costs.value,
            "randomize_levels": self.options.randomize_levels.value,
            "progressive_leveling": self.options.progressive_leveling.value,
            "progressive_attribute_proficiencies":self.options.progressive_attribute_proficiencies.value
        }

    #This function exists for universal tracker to align the rng
    @staticmethod
    def interpret_slot_data(slot_data: dict[str, typing.Any]) -> dict[str, typing.Any]:
        # Trigger a regen in UT
        return slot_data

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
            "win_condition": self.options.win_condition.value,
            "collect_red_fairies_amount": self.options.collect_red_fairies_amount.value,
            "fairysanity": self.options.fairysanity.value,
            "shopsanity": self.options.shopsanity.value,
            "combosanity": self.options.combosanity.value,
            "enemysanity": self.options.enemysanity.value,
            "open_world": self.options.open_world.value,
            "exclude_sacred_battle_arena_checks": self.options.exclude_sacred_battle_arena_checks.value,
            "death_link": self.options.death_link.value,
            "randomize_starting_deck": self.options.randomize_starting_deck.value,
            "randomize_shop_contents": self.options.randomize_shop_contents.value,
            "randomize_bonus_draws": self.options.randomize_bonus_draws.value,
            "randomize_magic_stone_costs": self.options.randomize_magic_stone_costs.value,
            "randomize_levels": self.options.randomize_levels.value,
            "progressive_leveling": self.options.progressive_leveling.value,
            "progressive_attribute_proficiencies":self.options.progressive_attribute_proficiencies.value,
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


EXCLUDED_REGIONS = {
    "Royal Tower, Lower",
    "Royal Tower, Middle",
    "Royal Tower, Upper",
    "Proving Grounds",
    "Sacred Battle Arena 2"
}

def source_of(exit_key: str) -> str:
    return exit_key.rsplit(" Exit ", 1)[0]


def randomize_exits(start_region: str = "Nobleman's Residence") -> dict:
    logger.info(f"Starting Level Randomization from {start_region}...")

    # 1. SETUP - Locked Sorts
    exits_by_source = {}
    # Sort keys first to ensure we process sources in a fixed order
    for ek in sorted(lost_kingdoms_2_region_exits.keys()):
        source = source_of(ek)
        if source not in exits_by_source:
            exits_by_source[source] = []
        exits_by_source[source].append(ek)

    # Sort the lists within the dictionary so exit indices are always identical
    for source in exits_by_source:
        exits_by_source[source].sort()

    all_regions = set(lost_kingdoms_2_regions.keys())
    # Ensure regions_to_place is a strictly sorted list from the start
    regions_to_place = sorted(list(all_regions - {start_region} - EXCLUDED_REGIONS))

    # Initialize available_exits and sort immediately
    available_exits = sorted(exits_by_source.get(start_region, []))
    result = {}

    def get_provided_exits(r: str) -> list[str]:
        # Always return a sorted list of exits
        if r == "Alanjeh Castle":
            return sorted(exits_by_source.get("Royal Tower, Lower", []))
        return sorted(exits_by_source.get(r, []))

    # 2. PLACEMENT LOOP
    while regions_to_place:
        if not available_exits:
            logger.error(f"CRITICAL: No available exits left! Remaining regions: {regions_to_place}")
            raise IndexError(f"Map generation failed: Out of exits with {len(regions_to_place)} left.")

        # Re-sort before every choice to ensure index selection is stable
        available_exits.sort()
        exit_choice = random.choice(available_exits)
        available_exits.remove(exit_choice)

        # Build candidates from the already-sorted regions_to_place
        valid_candidates = [r for r in regions_to_place]

        # --- RULE 1: THE HOLZOGH DEAD-END RULE ---
        if exit_choice == "Holzogh Town Exit 2":
            dead_ends = [r for r in valid_candidates if len(get_provided_exits(r)) == 0]
            if dead_ends:
                # No extra sort needed (they are filtered from a sorted list), but safety first
                dead_ends.sort()
                valid_candidates = dead_ends
                logger.info("Logic: Forcing Dead-End behind Holzogh Exit 2.")

        # --- RULE 2: FRONTIER HEALTH ---
        if len(available_exits) <= 1 and len(regions_to_place) > 1:
            hubs = [r for r in valid_candidates if len(get_provided_exits(r)) >= 1]
            if hubs:
                hubs.sort()
                valid_candidates = hubs
                logger.info(f"Logic: Frontier low ({len(available_exits)}), forcing branching region.")

        # --- RULE 3: BURY ALANJEH ---
        if "Alanjeh Castle" in valid_candidates and len(valid_candidates) > 1:
            valid_candidates = [r for r in valid_candidates if r != "Alanjeh Castle"]

        # --- EXECUTION ---
        if not valid_candidates:
            valid_candidates = regions_to_place

        # Final safety sort before random selection
        valid_candidates.sort()
        region = random.choice(valid_candidates)

        result[exit_choice] = region
        regions_to_place.remove(region)

        # Extend with sorted exits
        new_exits = get_provided_exits(region)
        available_exits.extend(new_exits)
        available_exits.sort()  # Ensure next iteration's choice is based on a sorted pool

        logger.debug(f"Placed: {exit_choice} -> {region}")

    logger.info("Level Randomization Complete.")
    return result

lost_kingdoms_2_logic = {
    # Movement Logic
    "jump_or_flight": lambda state, p: state.has_any(lost_kingdoms_2_jumping_cards, p) or state.has_any(
        lost_kingdoms_2_flying_cards, p),
    "flight_only": lambda state, p: state.has_any(lost_kingdoms_2_flying_cards, p),
    "jumping_only": lambda state, p: state.has_any(lost_kingdoms_2_jumping_cards, p),
    "jump_and_boosters": lambda state, p: state.has_any(lost_kingdoms_2_jumping_cards, p) and state.has(
        "Magic Boosters", p),
    "jump_boost_flight": lambda state, p: state.has_any(lost_kingdoms_2_jumping_cards, p) and state.has(
        "Magic Boosters", p) and state.has_any(lost_kingdoms_2_flying_cards, p),

    # Region/Event Logic
    "reach_upper_caverns": lambda state, p: state.can_reach_region("Runestone Caverns - Upper Chambers", p),
    "reach_royal_upper": lambda state, p: state.can_reach_region("Royal Tower, Upper", p),
    "reach_royal_lower": lambda state, p: state.can_reach_region("Royal Tower, Lower", p),
    "reach_ruldo": lambda state, p: state.can_reach_region("Ruldo Forest", p),

    # Specific Card/Item Logic
    "flight_and_god": lambda state, p: state.has_any(lost_kingdoms_2_flying_cards, p) and state.has(
        "God of Destruction", p),
    "hellhound_and_god": lambda state, p: state.has("Hell Hound", p) and state.has("God of Destruction", p),
    "hellhound_only": lambda state, p: state.has("Hell Hound", p),
    "hellhound_and_boosters": lambda state, p: state.has("Hell Hound", p) and state.has("Magic Boosters", p),
    "golem_only": lambda state, p: state.has("Stone Golem", p),
    "golem_and_boosters": lambda state, p: state.has("Stone Golem", p) and state.has("Magic Boosters", p),
    "black_liquid_logic": lambda state, p: state.has_any(lost_kingdoms_2_jumping_cards, p) and state.has(
        "Black Liquid", p),
    "black_liquid_only": lambda state, p: state.has("Black Liquid", p),
    "bottle_only": lambda state, p: state.has("Bottle", p),

    # Key/Quest Logic
    "mysterious_key": lambda state, p: state.has("Mysterious Key", p),
    "fountain_key": lambda state, p: state.has("Key to Fountain", p),
    "castle_gate": lambda state, p: state.has("Castle Gate Key", p),
    "blue_key": lambda state, p: state.has("Blue Key", p),
    "red_key": lambda state, p: state.has("Red Key", p),
    "blue_and_red": lambda state, p: state.has("Blue Key", p) and state.has("Red Key", p),
    "flight_or_blue": lambda state, p: state.has_any(lost_kingdoms_2_flying_cards, p) or state.has("Blue Key", p),
    "jewel_and_gate": lambda state, p: state.has("Jewel of Alanjeh", p) and state.has("Castle Gate Key", p),
    "green_key_and_blue_flight": lambda state, p: state.has("Green Key", p) and (
                state.has_any(lost_kingdoms_2_flying_cards, p) or state.has("Blue Key", p)),

    # Collection Logic
    "all_runestones": lambda state, p: state.has_all([
        "Eno Runestone", "Oht Runestone", "Elise Runestone", "Olf Runestone",
        "Ebin Runestone", "Keil Runestone", "Nebeth Runestone"], p),
    "all_blades": lambda state, p: state.has_all([
        "Blade of Skill", "Blade of Power", "Blade of Wisdom", "Blade of Time"], p),
    "zombie_dragon": lambda state, p: state.has_all(["Fossil Head", "Fossil Torso", "Fossil Tail",
        "Fossil Rt Wing", "Fossil Lt Wing", "Fossil Rt Arm",
        "Fossil Lt Arm", "Fossil Rt Leg", "Fossil Lt Leg"], p),

    # Fairy Progression
    "fairy_1": lambda state, p: state.has("Red Fairy", p, 1),
    "fairy_10": lambda state, p: state.has("Red Fairy", p, 10),
    "fairy_20": lambda state, p: state.has("Red Fairy", p, 20),
    "fairy_30": lambda state, p: state.has("Red Fairy", p, 30),
    "fairy_50": lambda state, p: state.has("Red Fairy", p, 50),
    "fairy_70": lambda state, p: state.has("Red Fairy", p, 70),
    "fairy_80": lambda state, p: state.has("Red Fairy", p, 80),
    "fairy_90": lambda state, p: state.has("Red Fairy", p, 90),
    "fairy_100": lambda state, p: state.has("Red Fairy", p, 100),
}