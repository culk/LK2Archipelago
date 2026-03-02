import asyncio
import logging
import random
import sys
import time
import traceback
from typing import TYPE_CHECKING, Any, Optional

import dolphin_memory_engine

from NetUtils import ClientStatus
from .client.constants import *

import Utils
from CommonClient import ClientCommandProcessor, CommonContext, get_base_parser, gui_enabled, logger, server_loop
from .iso_helper.lk2_rom import LK2USAAPPatch

from .Locations import lost_kingdoms_2_locations, lost_kingdoms_2_regions, lost_kingdoms_2_combos, \
    lost_kingdoms_2_bonus_draws
from worlds.LostKingdoms2 import lost_kingdoms_2_cards, lost_kingdoms_2_key_items, lost_kingdoms_2_items, \
    location_name_to_id, lost_kingdoms_2_shop_purchases, lost_kingdoms_2_jumping_cards, lost_kingdoms_2_flying_cards, \
    lostkingdoms_2_custom_prices

if TYPE_CHECKING:
    import kvui

CONNECTION_REFUSED_GAME_STATUS = (
    "Dolphin failed to connect. Please load a randomized ROM for Lost Kingdoms 2. Trying again in 5 seconds..."
)
CONNECTION_REFUSED_SAVE_STATUS = (
    "Dolphin failed to connect. Please load into the save file. Trying again in 5 seconds..."
)
CONNECTION_LOST_STATUS = (
    "Dolphin connection was lost. Please restart your emulator and make sure Lost Kingdoms 2 is running."
)
CONNECTION_CONNECTED_STATUS = "Dolphin connected successfully."
CONNECTION_INITIAL_STATUS = "Dolphin connection has not been initiated."

SLOT_NAME_ADDR = 0x80003DA0
IS_IN_GAME_ADDR = 0x80223c88
IS_IN_LEVEL_ADDRESS = 0x80223c88

RED_FAIRY_COUNT_ADDRESS = 0x8025d032
KEY_ITEM_ITEM_ADDRESS = 0x8025d068
KEY_ITEM_LOCATION_ADDRESS = 0x8025d010
MAGIC_BOOSTER_LOCATION_ADDRESS = 0x8025dd90
MAGIC_BOOSTER_ITEM_ADDRESS = 0x8025d014
ITEM_INDEX_ADDRESS = 0x8025d016
Valkyrie_Ashura_ADDRESS = 0x8025e28c
God_of_Harmony_Health_ADDRESS = 0x80223eb8
God_of_Harmony_ID_ADDRESS = 0x80223e5c # = 2164498496
Emperor_Health_ADDRESS = 0x80223fb8
Emperor_ID_ADDRESS = 0x80223f6c # = 8153e580
TEMP_DECK_ADDRESS = 0x80257ada
CARD_INFO_TABLE_ADDRESS = 0x80732be0
CARD_SHOP_ADDRESS = 0x80168700
STARTING_DECK_ADDRESS = 0x80152640
BONUS_DRAW_ADDRESS = 0x80168168
COMBO_LOCATION_ADDRESS = 0x8025d070
KADISHU_SHOP_1_AND_2_ADDRESS = 0x8123cdc0
KADISHU_SHOP_3_ADDRESS = 0x8124aa60
CATHEDRAL_SHOP_ADDRESS = 0x812b2880
KADISHU_SHOP_1_AND_2_UI_SELECTION_ADDRESS = 0x8125884a
KADISHU_SHOP_3_UI_SELECTION_ADDRESS = 0x8123a7aa
CATHEDRAL_SHOP_UI_SELECTION_ADDRESS = 0x812b026a
SHOP_SUB_UI_FLAG = 0x80275c58
THIRD_SHOP_UNLOCK_FLAG = 0x8025e04c
SHOP_MENU_ADDRESS = 0x80275c58
LEVEL_ID_ADDRESS = 0x80209262
PLAYER_GOLD_ADDRESS = 0x8025d022
CURR_HEALTH_ADDR = 0x80223c98
SHOP_LOCATION_ADDRESS = 0x8025d018


ONE_TIME_MODIFIERS_IN_GAME = False
ONE_TIME_MODIFIERS_MAIN_MENU = False
HAS_GOALED = False
PLAYER_PREVIOUS_GOLD = 0


class LK2CommandProcessor(ClientCommandProcessor):
    """
    Command Processor for Lost Kingdoms 2 client commands.

    This class handles commands specific to Lost Kingdoms 2.
    """

    def __init__(self, ctx: CommonContext):
        """
        Initialize the command processor with the provided context.

        :param ctx: Context for the client.
        """
        super().__init__(ctx)

    def _cmd_dolphin(self) -> None:
        """
        Display the current Dolphin emulator connection status.
        """
        if isinstance(self.ctx, LK2Context):
            logger.info(f"Dolphin Status: {self.ctx.dolphin_status}")


class LK2Context(CommonContext):
    """
    The context for Lost Kingdoms 2 client.

    This class manages all interactions with the Dolphin emulator and the Archipelago server for Lost Kingdoms 2.
    """

    command_processor = LK2CommandProcessor
    game: str = "Lost Kingdoms II"
    items_handling: int = 0b111  # full remote
    slot: str

    def __init__(self, server_address: Optional[str], password: Optional[str]) -> None:
        """
        :param server_address: Address of the Archipelago server.
        :param password: Password for server authentication.
        """

        super().__init__(server_address, password)
        self.dolphin_sync_task: Optional[asyncio.Task[None]] = None
        self.dolphin_status: str = CONNECTION_INITIAL_STATUS
        self.awaiting_rom: bool = False
        self.has_send_death: bool = False
        self.send_hints: int = 0
        self.hints = {}
        self.slot_data = {}
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

    async def disconnect(self, allow_autoreconnect: bool = False) -> None:
        """
        Disconnect the client from the server and reset game state variables.

        :param allow_autoreconnect: Allow the client to auto-reconnect to the server. Defaults to `False`.

        """
        await super().disconnect(allow_autoreconnect)

    def on_package(self, cmd: str, args: dict[str, Any]) -> None:
        """
        Handle incoming packages from the server.

        :param cmd: The command received from the server.
        :param args: The command arguments.
        """
        if cmd == "Connected":
            logger.debug(f"CONNECTED SLOT DATA = {args['slot_data']}")
            self.slot_data = args["slot_data"]
            if "death_link" in args["slot_data"]:
                Utils.async_start(self.update_death_link(bool(args["slot_data"]["death_link"])))

        if cmd == "Retrieved":
            # This is the response to a Get command
            keys = args.get("keys", {})

            for key in keys:
                if keys[key] is not None:
                    if key == f"lk2_{self.team}_{self.slot}_{self.auth}_key_items":
                            write_memory(KEY_ITEM_LOCATION_ADDRESS, keys[key],4)
                    elif key == f"lk2_{self.team}_{self.slot}_{self.auth}_magic_booster":
                            write_memory(MAGIC_BOOSTER_ITEM_ADDRESS, keys[key])
                    elif key == f"lk2_{self.team}_{self.slot}_{self.auth}_item_index":
                            write_memory(ITEM_INDEX_ADDRESS, keys[key])


    def on_deathlink(self, data: dict[str, Any]) -> None:
        """
        Handle a DeathLink event.

        :param data: The data associated with the DeathLink event.
        """
        super().on_deathlink(data)
        _give_death(self)

    def make_gui(self) -> type["kvui.GameManager"]:
        """
        Initialize the GUI for Lost Kingdoms 2  client.

        :return: The client's GUI.
        """
        ui = super().make_gui()
        ui.base_title = "Archipelago Lost Kingdoms 2 Client"
        return ui

    async def wait_for_next_loop(self, time_to_wait: float):
        await asyncio.sleep(time_to_wait)

    async def server_auth(self, password_requested: bool = False) -> None:
        """
        Authenticate with the Archipelago server.

        :param password_requested: Whether the server requires a password. Defaults to `False`.
        """
        if password_requested and not self.password:
            await super().server_auth(password_requested)
        if not self.auth:
            if self.awaiting_rom:
                return
            self.awaiting_rom = True
            logger.info("Awaiting connection to Dolphin to get player information.")
            return
        await self.send_connect()


def read_memory(console_address: int, byte_size: int = 2) -> int:
    """
    Read a 2-byte short from Dolphin memory.

    :param byte_size: The size of the data to read in bytes.
    :param console_address: Address to read from.
    :return: The value read from memory.
    """
    if byte_size != 1:
        return int.from_bytes(dolphin_memory_engine.read_bytes(console_address, byte_size), byteorder="big")
    else:
        return dolphin_memory_engine.read_byte(console_address)


def write_memory(console_address: int, value: int, byte_size: int = 2) -> None:
    """
    Write a 2-byte short to Dolphin memory.

    :param byte_size: The size of the memory to write in bytes
    :param console_address: Address to write to.
    :param value: Value to write.
    """
    if byte_size != 1:
        dolphin_memory_engine.write_bytes(console_address, value.to_bytes(byte_size, byteorder="big"))
    else:
        dolphin_memory_engine.write_byte(console_address, value)


def read_string(console_address: int, strlen: int) -> str:
    """
    Read a string from Dolphin memory.

    :param console_address: Address to start reading from.
    :param strlen: Length of the string to read.
    :return: The string.
    """
    string = dolphin_memory_engine.read_bytes(console_address, strlen).split(b"\0", 1)[0].decode()
    return string


def _give_death(ctx: LK2Context) -> None:
    """
    Trigger the player's death in-game by setting their current health to zero.

    :param ctx: The Lost Kingdoms 2 client context.
    """
    if (
        ctx.slot is not None
        and dolphin_memory_engine.is_hooked()
        and ctx.dolphin_status == CONNECTION_CONNECTED_STATUS
        and check_ingame()
    ):
        ctx.has_send_death = True
        write_memory(CURR_HEALTH_ADDR, 0)


def _give_item(ctx: LK2Context, item_name: str) -> bool:
    """
    Give an item to the player in-game.

    :param ctx: Lost Kingdoms 2 client context.
    :param item_name: Name of the item to give.
    :return: Whether the item was successfully given.
    """
    item = lost_kingdoms_2_items.get(item_name, None)
    if item is None:
        return False
    elif item["Type"] == "Card":
        return give_card(ctx,item_name)
    elif item["Type"] == "Red Fairy":
        return give_red_fairy(ctx)
    elif item["Type"] == "Key Item":
        return give_key_item(ctx,item_name)
    elif item["Type"] == "Magic Boosters":
        return activate_magic_boosters(ctx)
    elif item == "Victory":
        return True
    else:
        logger.error("Received Invalid Item:" + item_name + " " + str(item_name))
        return False

def give_red_fairy(ctx) -> bool:
    logger.debug("Giving fairy")
    try:
        memory_address = RED_FAIRY_COUNT_ADDRESS
        current_amount_of_item = read_memory(memory_address, 1)
        write_memory(memory_address, current_amount_of_item + 1,1)
        logger.debug("Red fairy amount = " + str(current_amount_of_item + 1))

        increment_item_index(ctx)
        return True
    except Exception as e:
        logger.error(e)
        return False

def give_card(ctx,card_name: str) -> bool:
    logger.debug("Giving card " + card_name)

    try:
        #add card to player's collection
        if True: #read_memory(IS_IN_LEVEL_ADDRESS,1) != 1:
            memory_address = int(lost_kingdoms_2_cards[card_name]["DolphinAddress"], 16)
            current_amount_of_item = read_memory(memory_address)
            write_memory(memory_address, current_amount_of_item + 1)
        else:
            #add card to player's available cards at a deck point
            offset = 0
            while read_memory(TEMP_DECK_ADDRESS + offset) != 0xffff and offset <= 480:
                offset += 16
            if offset < 480:
                hex_code = int(lost_kingdoms_2_cards[card_name]["hexCode"],16)
                write_memory(TEMP_DECK_ADDRESS + offset, hex_code)

                #Get the card type
                card_info_memory = CARD_INFO_TABLE_ADDRESS+0x160*(hex_code-0x01)
                card_type_value = read_memory(card_info_memory+0x10*17+0x01,1)

                #0 = independent, 1 = helper, 2 = summon, 3 = weapon, 4 = transform,
                if card_type_value in [0, 1, 4]:
                    card_lifespan_value = read_memory(card_info_memory+ 0x10 * 12 + 0x06)
                else:
                    card_lifespan_value = read_memory(card_info_memory + 0x10 * 14)
                #Set the lifespan of the newly added card
                write_memory(TEMP_DECK_ADDRESS + offset + 2, card_lifespan_value)

        increment_item_index(ctx)
        return True
    except Exception as e:
        logger.error(e)
        return False

def give_key_item(ctx,item_name: str) -> bool:
    logger.debug("Giving key item " + item_name)
    try:
        offset = 1
        for key_item in lost_kingdoms_2_key_items:
            if key_item == item_name:
                value = read_memory(KEY_ITEM_ITEM_ADDRESS,4)
                write_memory(KEY_ITEM_ITEM_ADDRESS, value | (1 << offset), 4)

                match item_name:
                    case "Blue Key":
                        write_memory(0x8025d897, 0, 1)
                        write_memory(0x8025d8a7, 0, 1)
                        write_memory(0x8025d8b7, 0, 1)
                        value = read_memory(0x8025dcd1, 1)
                        write_memory(0x8025dcd1, value | (1 << 1), 1)
                        logger.debug("Blue Key Found")
                    case "Red Key":
                        write_memory(0x8025d867, 0, 1)
                        write_memory(0x8025d877, 0, 1)
                        write_memory(0x8025d887, 0, 1)
                        value = read_memory(0x8025dcd1, 1)
                        write_memory(0x8025dcd1, value | (1 << 0), 1)
                        logger.debug("Red Key Found")
                    case "Green Key":
                        write_memory(0x8025d8c7, 0, 1)
                        value = read_memory(0x8025dcd1, 1)
                        write_memory(0x8025dcd1, value | (1 << 2), 1)
                        logger.debug("Green Key Found")
                    case "Bottle":
                        value = read_memory(0x8025e150)
                        write_memory(0x8025e150, value + 2)
                    case "Black Liquid":
                        value = read_memory(0x8025e150)
                        write_memory(0x8025e150, value + 4)

                increment_item_index(ctx)
                return True
            else:
                offset+=1

        return False
    except Exception as e:
        logger.error(e)
        return False


def increment_item_index(ctx):
    index = read_memory(ITEM_INDEX_ADDRESS)
    write_memory(ITEM_INDEX_ADDRESS, index + 1)

def activate_magic_boosters(ctx) -> bool:
    write_memory(MAGIC_BOOSTER_ITEM_ADDRESS, 8)
    increment_item_index(ctx)
    return True

def modify_code(ctx):
    # Change the key item location addresses so the locations can be checked
    # even after receiving the key items.

    #Key locations
    write_memory(0x8006e78c, 0x80850004, 4)
    write_memory(0x8006e798, 0x90050004,4)
    #Prevent KF doors being openable after killing the guards
    #write_memory(0x80078fc0,0x60000000, 4)
    #write_memory(0x80088188, 0x60000000, 4)
    #write_memory(0x800874dc, 0x60000000, 4)
    #Prevent fossils respawning
    #write_memory(0x8006e7c4, 0x80030004, 4) Fixes fossils respawning, but breaks every other key item item
    #Magic Boosters visuals
    write_memory(0x80075738, 0x3C808026, 4)
    write_memory(0x8007573c, 0x8004D014, 4)
    write_memory(0x80075740, 0x60000000, 4)
    #Magic Boosters trigger
    write_memory(0x8007b334, 0x3C608026, 4)
    write_memory(0x8007b338, 0x8003D014, 4)
    #Remove the branch preventing duplicates in shops
    write_memory(0x800dc438, 0x60000000, 4)
    #Prevent red fairies from increasing red fairy count
    if ctx.slot_data.get("fairysanity", 0):
        write_memory(0x80077034, 0x38040000, 4)

    logger.debug("Modified code")

def prevent_KF_gates_from_being_openable():
    if read_memory(LEVEL_ID_ADDRESS, 1) == 4:
        if not ((read_memory(KEY_ITEM_ITEM_ADDRESS, 4) >> 2) & 1):
            write_memory(0x8025d897, 1, 1)
            write_memory(0x8025d8a7, 1, 1)
            write_memory(0x8025d8b7, 1, 1)
        if not ((read_memory(KEY_ITEM_ITEM_ADDRESS, 4) >> 1) & 1):
            write_memory(0x8025d867, 1, 1)
            write_memory(0x8025d877, 1, 1)
            write_memory(0x8025d887, 1, 1)
        if not ((read_memory(KEY_ITEM_ITEM_ADDRESS, 4) >> 3) & 1):
            write_memory(0x8025d8c7, 1, 1)

def set_shop_contents_to_AP():
    for x in range(40):
        write_memory(0x80168700+(x*0x2), 0x00000000)

def open_world():
    logger.debug("Opening world")
    for region in lost_kingdoms_2_regions:
        write_memory(int(lost_kingdoms_2_regions[region]["RAMAddress"],16), 128, 1)

def randomize_shop_contents(ctx):
    random.seed(ctx.slot_data.get("Seed", -1))
    cards = list(lost_kingdoms_2_cards.keys())
    excluded_cards = lost_kingdoms_2_flying_cards + lost_kingdoms_2_jumping_cards + ["God of Destruction"] + ["Stone Golem"]
    cards = list(set(cards) - set(excluded_cards))
    for x in range (32):
        card_name = random.choice(cards)
        write_memory(CARD_SHOP_ADDRESS+x*2,int(lost_kingdoms_2_cards[card_name]["hexCode"],16))
        cards.remove(card_name)

    #Add custom prices for cards that lack prices
    for card in lostkingdoms_2_custom_prices:
        write_memory(CARD_INFO_TABLE_ADDRESS+230+22*16*lost_kingdoms_2_cards[card]["number"], lostkingdoms_2_custom_prices[card])

def randomize_starting_deck(ctx):
    random.seed(ctx.slot_data.get("Seed", -1)+1)
    cards = list(lost_kingdoms_2_cards.keys())
    excluded_cards = lost_kingdoms_2_flying_cards + lost_kingdoms_2_jumping_cards + ["God of Destruction"] + ["Stone Golem"]
    cards = list(set(cards) - set(excluded_cards))
    for x in range(12):
        card_name = random.choice(cards)
        cards.remove(card_name)
        write_memory(STARTING_DECK_ADDRESS + x * 2,int(lost_kingdoms_2_cards[card_name]["hexCode"],16))

def randomize_bonus_draws(ctx):
    random.seed(ctx.slot_data.get("Seed", -1)+2)
    cards = list(lost_kingdoms_2_cards.keys())
    excluded_cards = lost_kingdoms_2_flying_cards + lost_kingdoms_2_jumping_cards + ["God of Destruction"] + ["Stone Golem"]
    cards = list(set(cards) - set(excluded_cards))
    group_dict = {}
    for key in lost_kingdoms_2_bonus_draws:
        bonus_draw = lost_kingdoms_2_bonus_draws[key]
        if group_dict.get(bonus_draw["cardGroup"], 0):
            card_name = group_dict.get(bonus_draw["cardGroup"])
            write_memory(BONUS_DRAW_ADDRESS + int(bonus_draw["address"], 16) - 0x183169, int(lost_kingdoms_2_cards[card_name]["hexCode"], 16))
        else:
            card_name = random.choice(cards)
            cards.remove(card_name)
            write_memory(BONUS_DRAW_ADDRESS + int(bonus_draw["address"], 16) - 0x183169, int(lost_kingdoms_2_cards[card_name]["hexCode"], 16))
            group_dict[bonus_draw["cardGroup"]] = card_name


def has_item(self, name: str) -> bool:
    """Check if player has received an item"""
    try:
        item_id = lost_kingdoms_2_items[name]["id"]
        for item in self.items_received:
            if item_id == item.item:
                return True
    except Exception as e:
        logger.error(name + " is an invalid item")
    return False

async def check_victory_conditions(ctx: LK2Context):
    global HAS_GOALED
    if not HAS_GOALED:
        match ctx.slot_data.get("win_condition", -1):
            case 0:
                if read_memory(God_of_Harmony_Health_ADDRESS) == 0 and read_memory(God_of_Harmony_ID_ADDRESS,4) == 2164498496:
                    await ctx.send_msgs([{
                        "cmd": "StatusUpdate",
                        "status": ClientStatus.CLIENT_GOAL
                    }])
                    HAS_GOALED = True
            case 1:
                if read_memory(Emperor_Health_ADDRESS) == 0 and read_memory(Emperor_ID_ADDRESS,4) == 2169759104:
                    await ctx.send_msgs([{
                        "cmd": "StatusUpdate",
                        "status": ClientStatus.CLIENT_GOAL
                    }])
                    HAS_GOALED = True
            case 2:
                for key in lost_kingdoms_2_cards:
                    if read_memory(lost_kingdoms_2_cards[key]) <= 0:
                        return
                await ctx.send_msgs([{
                    "cmd": "StatusUpdate",
                    "status": ClientStatus.CLIENT_GOAL
                }])
                HAS_GOALED = True

async def save_data(ctx: LK2Context):
    logger.debug("Saving data")
    await ctx.send_msgs([{
        "cmd": "Set",
        "key": f"lk2_{ctx.team}_{ctx.slot}_{ctx.auth}_item_index",  # Unique key per player
        "default": None,  # Default value if key doesn't exist
        "want_reply": False,  # Set to True if you want confirmation
        "operations": [{"operation": "replace", "value": read_memory(ITEM_INDEX_ADDRESS)}]
    }])
    await ctx.send_msgs([{
        "cmd": "Set",
        "key": f"lk2_{ctx.team}_{ctx.slot}_{ctx.auth}_magic_booster",  # Unique key per player
        "default": None,  # Default value if key doesn't exist
        "want_reply": False,  # Set to True if you want confirmation
        "operations": [{"operation": "replace", "value": read_memory(MAGIC_BOOSTER_ITEM_ADDRESS)}]
    }])
    await ctx.send_msgs([{
        "cmd": "Set",
        "key": f"lk2_{ctx.team}_{ctx.slot}_{ctx.auth}_key_items",  # Unique key per player
        "default": None,  # Default value if key doesn't exist
        "want_reply": False,  # Set to True if you want confirmation
        "operations": [{"operation": "replace", "value": read_memory(KEY_ITEM_LOCATION_ADDRESS,4)}]
    }])

    ctx.need_to_save = False

async def load_data(ctx: LK2Context):
    logger.debug("Loading data")
    await ctx.send_msgs([{
        "cmd": "Get",
        "keys": [f"lk2_{ctx.team}_{ctx.slot}_{ctx.auth}_key_items",f"lk2_{ctx.team}_{ctx.slot}_{ctx.auth}_magic_booster",f"lk2_{ctx.team}_{ctx.slot}_{ctx.auth}_item_index"]
    }])

async def give_items(ctx: LK2Context) -> None:
    """
    Give the player all outstanding items they have yet to receive.

    :param ctx: Lost Kingdoms 2 client context.
    """
    received_items = ctx.items_received
    NUM_ITEMS_RECEIVED = read_memory(ITEM_INDEX_ADDRESS)
    if len(received_items) <= NUM_ITEMS_RECEIVED:
        return
    pass

    for x, item in enumerate(received_items[NUM_ITEMS_RECEIVED:], start=NUM_ITEMS_RECEIVED):
        item_name = None
        for lk2_item in lost_kingdoms_2_items:
            if lost_kingdoms_2_items[lk2_item]["id"] == item.item:
                item_name = lk2_item
                break
        if item_name is not None:
            while not _give_item(ctx, item_name):
                await asyncio.sleep(0.01)
        else:
            logger.error("Invalid item id" + str(item.item))

def check_regular_location(ctx: LK2Context, location: str) -> bool:
    """
    Check that the player has checked a given location.
    This function handles locations that only require checking that a particular bit is set.

    The check looks at the saved data for the stage at which the location is located and the data for the current stage.
    In the latter case, this data includes data that has not yet been written to the saved data.

    :param location: The location.
    :param ctx: Lost Kingdoms 2 client context.
    :raises NotImplementedError: If a location with an unknown type is provided.
    """
    match lost_kingdoms_2_locations[location]["type"]:
        case "Chest" | "Red Fairy" | "Magic Boosters":
            if lost_kingdoms_2_locations[location]["RAMAddress"]!="":
                if (location == "help valkyrie") | (location == "help ashura"):
                    if read_memory(Valkyrie_Ashura_ADDRESS) != 256:
                        return False
                elif "FH - collect" in location:
                    memory_value = read_memory(int(lost_kingdoms_2_locations[location]["RAMAddress"], 16),1)
                    return memory_value >= lost_kingdoms_2_locations[location]["bitOffset"]
                memory_value = read_memory(int(lost_kingdoms_2_locations[location]["RAMAddress"], 16))
                if lost_kingdoms_2_locations[location]["bitOffset"] >= 0:
                    bit_value = (memory_value & (1 << lost_kingdoms_2_locations[location]["bitOffset"]))
                    return bit_value != 0
                else:
                    return False
            else:
                return False
        case "Key Item":
            memory_value = read_memory(KEY_ITEM_LOCATION_ADDRESS,4)
            bit_value = (memory_value & (1 << lost_kingdoms_2_locations[location]["bitOffset"]))
            if bit_value != 0:
                if location == "Bottle" and not has_item(ctx,"Bottle"):
                    value = read_memory(0x8025e150)
                    if value & (1 << 1):
                        write_memory(0x8025e150, value - 2)
                elif location == "Black Liquid" and not has_item(ctx,"Black Liquid"):
                    value = read_memory(0x8025e150)
                    if value & (1 << 2):
                        write_memory(0x8025e150, value - 4)
                return True
            else:
                return False
        case "Combo":
            memory_value = read_memory(COMBO_LOCATION_ADDRESS, 8)
            bit_value = (memory_value >> lost_kingdoms_2_combos[location]["bitOffset"]) & 1
            return bit_value
        case "Shop Purchase":
            memory_value = read_memory(SHOP_LOCATION_ADDRESS, 5)
            bit_value = (memory_value >> lost_kingdoms_2_shop_purchases[location]["bitOffset"]) & 1
            return bit_value

    return False

async def check_locations(ctx: LK2Context) -> set[int]:
    """
    Iterate through all locations and check whether the player has checked each location.

    Update the server with all newly checked locations since the last update. If the player has completed the goal,
    notify the server.

    :param ctx: The Lost Kingdoms 2 client context.
    """

    # Loop through all locations to see if each has been checked.
    for key in lost_kingdoms_2_locations:
        if check_regular_location(ctx, key):
            ctx.locations_checked.add(location_name_to_id[key])

    # Send the list of newly-checked locations to the server.
    locations_checked = ctx.locations_checked.difference(ctx.checked_locations)
    if locations_checked:
        logger.debug("sending newly checked locations: " + str(locations_checked))
        await ctx.send_msgs([{"cmd": "LocationChecks", "locations": list(locations_checked)}])
        ctx.checked_locations.update(locations_checked)
    return locations_checked

async def check_alive() -> bool:
    """
    Check if the player is currently alive in-game.

    :return: `True` if the player is alive, otherwise `False`.
    """
    cur_health = read_memory(CURR_HEALTH_ADDR)
    return cur_health > 0


async def check_death(ctx: LK2Context) -> None:
    """
    Check if the player is currently dead in-game.
    If DeathLink is on, notify the server of the player's death.

    :return: `True` if the player is dead, otherwise `False`.
    """
    if ctx.slot is not None and check_ingame():
        cur_health = read_memory(CURR_HEALTH_ADDR)
        if cur_health <= 0:
            if not ctx.has_send_death and time.time() >= ctx.last_death_link + 10:
                ctx.has_send_death = True
                await ctx.send_death(ctx.player_names[1] + " did not believe in the heart of the cards.")
        else:
            ctx.has_send_death = False


def check_ingame() -> bool:
    """
    Check if the player is currently in-game.

    :return: `True` if the player is in-game, otherwise `False`.
    """
    try:
        return read_memory(IS_IN_GAME_ADDR) != 0
    except:
        return False

def check_inshop() -> bool:
    try:
        return read_memory(SHOP_MENU_ADDRESS) != 0
    except:
        return False

async def track_shop_purchases():
    shop_id = 0
    shop_address = KADISHU_SHOP_1_AND_2_ADDRESS
    ui_address = KADISHU_SHOP_1_AND_2_UI_SELECTION_ADDRESS
    if read_memory(LEVEL_ID_ADDRESS, 1) == 42:
        shop_id = 3
        shop_address = CATHEDRAL_SHOP_ADDRESS
        ui_address = CATHEDRAL_SHOP_UI_SELECTION_ADDRESS
    elif read_memory(int(lost_kingdoms_2_regions["Runestone Caverns - Lower Chambers"]["RAMAddress"],16)-0x2, 1) == 1:
        if read_memory(THIRD_SHOP_UNLOCK_FLAG, 1) == 1:
            shop_id = 2
            shop_address = KADISHU_SHOP_3_ADDRESS
            ui_address = KADISHU_SHOP_3_UI_SELECTION_ADDRESS
        else:
            shop_id = 1

    if read_memory(SHOP_SUB_UI_FLAG) == 1:
        global PLAYER_PREVIOUS_GOLD
        current_gold = read_memory(PLAYER_GOLD_ADDRESS)
        if current_gold < PLAYER_PREVIOUS_GOLD:
            index = read_memory(ui_address) + 10*shop_id
            logger.debug("shop index" + str(index))
            shop_location_data = read_memory(SHOP_LOCATION_ADDRESS, 5)
            logger.debug("shop location data before: " + str(shop_location_data))
            if (shop_location_data >> index) & 1 == 0:
                shop_location_data = shop_location_data | (1<<index)
                logger.debug("shop location data after: " + str(shop_location_data))
                write_memory(SHOP_LOCATION_ADDRESS, shop_location_data, 5)
        PLAYER_PREVIOUS_GOLD = current_gold




async def dolphin_sync_task_main_task(ctx: LK2Context):
    """
    The task loop for managing the connection to Dolphin.

    While connected, read the emulator's memory to look for any relevant changes made by the player in the game.

    :param ctx: Lost Kingdoms 2 client context.
    """
    global ONE_TIME_MODIFIERS_IN_GAME
    global ONE_TIME_MODIFIERS_MAIN_MENU
    global HAS_GOALED
    logger.info("Starting Dolphin connector. Use /dolphin for status information." + str(ctx.auth))
    sleep_time = 0.0
    while not ctx.exit_event.is_set():
        if sleep_time > 0.0:
            try:
                # ctx.watcher_event gets set when receiving ReceivedItems or LocationInfo, or when shutting down.
                await asyncio.wait_for(ctx.watcher_event.wait(), sleep_time)
            except asyncio.TimeoutError:
                pass
            sleep_time = 0.0
        ctx.watcher_event.clear()

        try:
            if dolphin_memory_engine.is_hooked() and ctx.dolphin_status == CONNECTION_CONNECTED_STATUS:
                if (not ONE_TIME_MODIFIERS_MAIN_MENU) and ctx.slot_data:
                    logger.debug("Seed is " + str(ctx.slot_data["Seed"]))
                    if ctx.slot_data.get("randomize_starting_deck", 0):
                        randomize_starting_deck(ctx)
                    if ctx.slot_data.get("randomize_shop_contents", 0):
                        randomize_shop_contents(ctx)
                    if ctx.slot_data.get("randomize_bonus_draws", 0):
                        randomize_bonus_draws(ctx)
                    ONE_TIME_MODIFIERS_MAIN_MENU = True
                if (not ONE_TIME_MODIFIERS_IN_GAME) and ctx.slot_data and check_ingame():
                    modify_code(ctx)
                    logger.debug("Slot data:" + str(ctx.slot_data))
                    if ctx.slot_data.get("open_world", 0):
                        open_world()
                    if ctx.slot_data.get("shopsanity", 0):
                        pass
                        #set_shop_contents_to_AP()
                    ONE_TIME_MODIFIERS_IN_GAME = True
                if ctx.slot is not None :
                    if check_ingame():
                        if "DeathLink" in ctx.tags:
                            await check_death(ctx)
                        #if ctx.slot_data.get("shopsanity", 0) & check_inshop():
                            #await track_shop_purchases()
                        prevent_KF_gates_from_being_openable()
                        await check_victory_conditions(ctx)
                        await give_items(ctx)
                        await check_locations(ctx)
                else:
                    HAS_GOALED = False
                    if not ctx.auth:
                        ctx.auth = read_string(SLOT_NAME_ADDR, 0x40)
                    if ctx.awaiting_rom:
                        await ctx.server_auth()
                sleep_time = 0.1
            else:
                ONE_TIME_MODIFIERS_IN_GAME = False
                ONE_TIME_MODIFIERS_MAIN_MENU = False
                HAS_GOALED = False
                if ctx.dolphin_status == CONNECTION_CONNECTED_STATUS:
                    logger.info("Connection to Dolphin lost, reconnecting...")
                    ctx.dolphin_status = CONNECTION_LOST_STATUS
                logger.info("Attempting to connect to Dolphin...")
                dolphin_memory_engine.hook()
                if dolphin_memory_engine.is_hooked():
                    if dolphin_memory_engine.read_bytes(0x80000000, 6) != b"GR2E52":
                        logger.info(dolphin_memory_engine.read_bytes(0x80000000, 6))
                        logger.info(CONNECTION_REFUSED_GAME_STATUS)
                        ctx.dolphin_status = CONNECTION_REFUSED_GAME_STATUS
                        dolphin_memory_engine.un_hook()
                        sleep_time = 5
                    else:
                        logger.info(CONNECTION_CONNECTED_STATUS)
                        ctx.dolphin_status = CONNECTION_CONNECTED_STATUS
                        ctx.locations_checked = set()
                else:
                    logger.info("Connection to Dolphin failed, attempting again in 5 seconds...")
                    ctx.dolphin_status = CONNECTION_LOST_STATUS
                    await ctx.disconnect()
                    sleep_time = 5
                    continue
        except Exception:
            dolphin_memory_engine.un_hook()
            logger.info("Connection to Dolphin failed, attempting again in 5 seconds...")
            logger.error(traceback.format_exc())
            ctx.dolphin_status = CONNECTION_LOST_STATUS
            await ctx.disconnect()
            sleep_time = 5
            continue


def main(*launch_args: str):
    from .client.dolphin_launcher import DolphinLauncher
    import colorama

    server_address: str = ""
    rom_path: str = ""

    Utils.init_logging(CLIENT_NAME)
    logger.info(f"Starting LK2 Client {CLIENT_VERSION}")
    dolphin_launcher: DolphinLauncher = DolphinLauncher()

    parser = get_base_parser()
    parser.add_argument('aplk2_file', default="", type=str, nargs="?", help='Path to an APLK2 file')
    parser.add_argument('--name', default=None, help="Slot Name to connect as.")
    args = parser.parse_args(launch_args)
    logger.info("Launch args: " + str(launch_args))

    lk2_usa_manifest = None
    if args.aplk2_file:
        lk2_usa_patch = LK2USAAPPatch()
        try:
            lk2_usa_manifest = lk2_usa_patch.read_contents(args.aplk2_file)
            server_address = lk2_usa_manifest["server"]
            rom_path= lk2_usa_patch.patch(args.aplk2_file)
        except Exception as ex:
            err_msg: str = f"Unable to patch your Lost Kingdoms 2 ROM as expected.\n" + \
                f"APWorld Version: '{CLIENT_VERSION}'\nAdditional details:{str(ex)}"
            logger.error(err_msg)
            Utils.messagebox("Cannot Lost Kingdoms 2", err_msg, True)
            raise ex

    async def _main(connect, password):

        ctx = LK2Context(server_address if server_address else connect, password)

        logger.info("Creating Server Loop")
        ctx.server_task = asyncio.create_task(server_loop(ctx), name="ServerLoop")

        if gui_enabled:
            ctx.run_gui()
        ctx.run_cli()
        await asyncio.sleep(1)

        ctx.dolphin_sync_task = asyncio.create_task(dolphin_sync_task_main_task(ctx), name="DolphinSync")

        await ctx.exit_event.wait()

        #ctx.watcher_event.set()
        #ctx.server_address = None

        await ctx.shutdown()

        if ctx.dolphin_sync_task:
            await ctx.dolphin_sync_task

    Utils.asyncio.run(dolphin_launcher.launch_dolphin_async(rom_path))

    colorama.just_fix_windows_console()
    asyncio.run(_main(args.connect, args.password))
    colorama.deinit()

if __name__ == "__main__":
    Utils.init_logging(CLIENT_NAME, exception_logger="Client")
    main(*sys.argv[1:])

