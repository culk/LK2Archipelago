import asyncio
import hashlib
import logging
import random
import sys
import time
import traceback
from typing import TYPE_CHECKING, Any, Optional
from unittest import case

import dolphin_memory_engine

from NetUtils import ClientStatus
from .client.constants import *

import Utils
from CommonClient import ClientCommandProcessor, CommonContext, get_base_parser, gui_enabled, logger, server_loop
from .iso_helper.lk2_rom import LK2USAAPPatch

from .Locations import *
from worlds.LostKingdoms2 import *

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
IS_IN_GAME_ADDR = 0x80a98aa8
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
Emperor_Health_ADDRESS = 0x80223fc8
Emperor_ID_ADDRESS = 0x80223f6c # = 8153e580
Emperor_Status = 0
TEMP_DECK_ADDRESS = 0x80257ada
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
PLAYER_LEVEL_ADDRESS = 0x8025d02c
CURR_HEALTH_ADDR = 0x80223c98
SHOP_LOCATION_ADDRESS = 0x8025d018
CARDS_LOADED = 0x80732bd4
CUSTOM_CODE_JUMP_1 = 0x8007b724
CUSTOM_CODE_RETURN_1 = 0x80005FE4
CUSTOM_CODE_ADDRESS_1 = 0x80001850
CUSTOM_CODE_JUMP_2 = 0x80091274
CUSTOM_CODE_RETURN_2 = 0x800F7F04
CUSTOM_CODE_ADDRESS_2 = CUSTOM_CODE_ADDRESS_1+60
CUSTOM_LEVEL_UP_CODE = CUSTOM_CODE_ADDRESS_2+108
CUSTOM_ATTRIBUTE_UP_CODE = CUSTOM_LEVEL_UP_CODE+80
CUSTOM_ATTRIBUTE_UP_TRIGGER = 0x8025d01c
INVALIDATE_ADDRESS = 0x800f31dc
PROGRESSIVE_LEVELING_ADDRESS = 0X8025d01d


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
    level_id: int = 0

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

def replace_game_id(ctx:LK2Context):
        data = f"{ctx.slot_data.get("Seed", -1)}:{ctx.slot_data.get("Slot", -1)}".encode()
        digest = hashlib.md5(data).hexdigest()

        charset = b"ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"


        encoded_bytes = bytes([
            charset[int(digest[i * 2:i * 2 + 2], 16) % 36]
            for i in range(6)
        ])

        write_memory(0x80000000, int.from_bytes(encoded_bytes, byteorder="big"), 6)


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
    item = lost_kingdoms_2_items.get(item_name)

    # We match on the "Type" key
    match item.get("Type"):
        case "Card":
            return give_card(ctx, item_name)
        case "Red Fairy":
            return give_red_fairy(ctx)
        case "Key Item":
            return give_key_item(ctx, item_name)
        case "Magic Boosters":
            return activate_magic_boosters(ctx)
        case "Progressive Player Level":
            return give_progressive_level(ctx)
        case "Progressive Attribute Proficiency":
            return add_to_progressive_attribute_proficiency_buffer(ctx, item_name)
        case "Blue Fairy":
            return give_blue_fairy(ctx)
        case "Victory":
            return True
        case _:
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

            #Update the catalogue
            if read_memory(memory_address+6) == 0:
                write_memory(memory_address+6, 3)
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
                increment_item_index(ctx)
                return True
            else:
                offset+=1

        return False
    except Exception as e:
        logger.error(e)
        return False

def give_progressive_level(ctx) -> bool:
    try:
        if read_memory(PROGRESSIVE_LEVELING_ADDRESS, 1)==0:
            write_memory(PROGRESSIVE_LEVELING_ADDRESS, 1,1)
        if is_in_level():
            write_memory(PROGRESSIVE_LEVELING_ADDRESS, read_memory(PROGRESSIVE_LEVELING_ADDRESS, 1)+1,1)
        else:
            write_memory(PLAYER_LEVEL_ADDRESS, read_memory(PLAYER_LEVEL_ADDRESS, 1) + 1, 1)
        increment_item_index(ctx)
        return True
    except Exception as e:
        logger.error(e)
        return False

progressive_attribute_proficiency_buffer = []
def add_to_progressive_attribute_proficiency_buffer(ctx,item_name) -> bool:
    global progressive_attribute_proficiency_buffer
    progressive_attribute_proficiency_buffer.append(item_name)
    increment_item_index(ctx)
    logger.debug("Added " +str(item_name) + " to buffer")
    return True

async def give_progressive_attribute_proficiency(ctx):
    try:
        if len(progressive_attribute_proficiency_buffer)!=0 and read_memory(0x8025d01e,1)==0:
            item_name = progressive_attribute_proficiency_buffer.pop(0)
            attribute = 0
            match item_name:
                case "Progressive Attribute Proficiency: Fire":
                    attribute = 0
                case "Progressive Attribute Proficiency: Water":
                    attribute = 1
                case "Progressive Attribute Proficiency: Earth":
                    attribute = 2
                case "Progressive Attribute Proficiency: Wood":
                    attribute = 3
                case "Progressive Attribute Proficiency: Neutral":
                    attribute = 4
                case "Progressive Attribute Proficiency: Mech":
                    attribute = 5
            write_memory(CUSTOM_CODE_ADDRESS_2 + 40,0x38800000+attribute,4)
            current_attribute_level = read_memory(0x8025d060+attribute,1)
            match current_attribute_level:
                case 1:
                    write_memory(0x8025d048+4*attribute,500,4)
                case 2:
                    write_memory(0x8025d048+4*attribute,1500,4)
                case 3:
                    write_memory(0x8025d048+4*attribute,3000,4)
                case 4:
                    write_memory(0x8025d048+4*attribute,5000,4)
                case 5:
                    write_memory(0x8025d048+4*attribute,7500,4)
                case 6:
                    write_memory(0x8025d048+4*attribute,10500,4)
                case 7:
                    write_memory(0x8025d048+4*attribute,14000,4)

            write_memory(0x8025d01e,1,1)
    except Exception as e:
        logger.error(e)

def give_blue_fairy(ctx) -> bool:
    try:
        value = read_memory(0x8025d0e0, 1)
        write_memory(0x8025d0e0, min(value+1,255), 1)
        increment_item_index(ctx)
        return True
    except Exception as e:
        logger.error(e)
        return False
    return False

def increment_item_index(ctx):
    index = read_memory(ITEM_INDEX_ADDRESS)
    write_memory(ITEM_INDEX_ADDRESS, index + 1)

def activate_magic_boosters(ctx) -> bool:
    write_memory(MAGIC_BOOSTER_ITEM_ADDRESS, 8)
    increment_item_index(ctx)
    return True

def make_bl(from_addr: int, to_addr: int) -> int:
    offset = to_addr - from_addr
    return 0x48000001 | (offset & 0x3FFFFFC)

def make_b(from_addr: int, to_addr: int) -> int:
    offset = to_addr - from_addr
    return 0x48000000 | (offset & 0x3FFFFFC)

def randomize_levels(ctx):
    random.seed(ctx.slot_data.get("Seed", -1) + 4)
    global level_ordering
    level_ordering = randomize_exits()
    logger.debug("Level ordering is:" + str(level_ordering))

def level_modifications(ctx):
    item_memory = read_memory(KEY_ITEM_ITEM_ADDRESS, 4)
    level_id = read_memory(LEVEL_ID_ADDRESS, 1)
    # Keep doors openable if they have key, otherwise, unopenable
    if level_id == lost_kingdoms_2_regions["Kendarie Fortress"]["levelID"]:
        if (item_memory >> 2) & 1:
            write_memory(0x8025d8a7, 0, 1)
            write_memory(0x8025d8b7, 0, 1)
        else:
            write_memory(0x8025d8a7, 1, 1)
            write_memory(0x8025d8b7, 1, 1)
        if (item_memory >> 1) & 1:
            write_memory(0x8025d867, 0, 1)
            write_memory(0x8025d887, 0, 1)
        else:
            write_memory(0x8025d867, 1, 1)
            write_memory(0x8025d887, 1, 1)
        if (item_memory >> 3) & 1:
            write_memory(0x8025d8d7, 0, 1)
        else:
            write_memory(0x8025d8d7, 1, 1)
        #Kill the final guard when he spawns to prevent crashing. Temporary.
        if read_memory(0x802241d8) not in [255,7]:
            write_memory(0x802241d8,7)
        #Set his health to 0 for good measure
            write_memory(0x802241e8, 0)
    #Let swords be placed in Bhashea Castle
    elif level_id == lost_kingdoms_2_regions["Bhashea Castle"]["levelID"]:
        #Blade of Skill placement
        if (item_memory >> 16) & 1:
            write_memory(0x8025d917, 0, 1)
        else:
            write_memory(0x8025d917, 1, 1)
        #Blade of Power placement
        if (item_memory >> 17) & 1:
            write_memory(0x8025d927, 0, 1)
        else:
            write_memory(0x8025d927, 1, 1)
        #Blade of Wisdom placement
        if (item_memory >> 18) & 1:
            write_memory(0x8025d937, 0, 1)
        else:
            write_memory(0x8025d937, 1, 1)
        #Blade of Time placement
        if (item_memory >> 19) & 1:
            write_memory(0x8025d947, 0, 1)
        else:
            write_memory(0x8025d947, 1, 1)

    #Make the runestones placeable in Isamat Urbur
    elif level_id == lost_kingdoms_2_regions["Isamat Urbur"]["levelID"]:
        #Eno Runestone
        if (item_memory >> 20) & 1:
            write_memory(0x8025d870, 2149662488, 4)
            write_memory(0x8025d867,0,1)
        else:
            write_memory(0x8025d870, 0, 4)
        #Nebeth Runestone
        if (item_memory >> 26) & 1:
            write_memory(0x8025d860, 2149662216, 4)
        else:
            write_memory(0x8025d860, 0, 4)
        #Olf Runestone
        if (item_memory >> 23) & 1:
            write_memory(0x8025d880, 2149662760, 4)
        else:
            write_memory(0x8025d880, 0, 4)
        #Ebin Runestone
        if (item_memory >> 24) & 1:
            write_memory(0x8025d8a0, 2149663304, 4)
        else:
            write_memory(0x8025d8a0, 0, 4)
        #Oht Runestone
        if (item_memory >> 21) & 1:
            write_memory(0x8025d890, 2149663032, 4)
        else:
            write_memory(0x8025d890, 0, 4)
        #Elise Runestone
        if (item_memory >> 22) & 1:
            write_memory(0x8025d8c0, 2149663848, 4)
        else:
            write_memory(0x8025d8c0, 0, 4)
        #Keil Runestone
        if (item_memory >> 25) & 1:
            write_memory(0x8025d8b0, 2149663576, 4)
        else:
            write_memory(0x8025d8b0, 0, 4)
    elif level_id == lost_kingdoms_2_regions["Gromtull Desert"]["levelID"]:
        #Black Liquid
        if ((item_memory >> 14) & 1) and read_memory(0x802e941e) == 55264:
            logger.debug("black liquid usage")
            value = read_memory(0x8025e151,1)
            write_memory(0x8025e151, value | 1 << 2, 1)
        #Bottle
        elif ((item_memory >> 13) & 1) and read_memory(0x802e941e) == 55248:
            logger.debug("bottle usage")
            value = read_memory(0x8025e151, 1)
            write_memory(0x8025e151, value | 1 << 1, 1)
        else:
            value = read_memory(0x8025e151, 1)
            write_memory(0x8025e151, value & ~((1 << 1) | (1 << 2)), 1)
    #Fix the first chest of fossil boneyard so it doesn't give a Hell Hound
    elif level_id == lost_kingdoms_2_regions["Fossil Boneyard"]["levelID"]:
        write_memory(0x8025d964,0,1)
    #Ensure that you can always unlock a level by talking to Jarvi's wife.
    elif level_id == lost_kingdoms_2_regions["Kadishu"]["levelID"]:
        if read_memory(0x802e941e)==55968 and is_in_level() and read_memory(0x8025e151,1) != 0:
            write_memory(0x8025e150, read_memory(0x8025e151,1),1)
            write_memory(0x8025e151,0,1)
        elif (not is_in_level() or read_memory(0x802e941e)!=55968) and read_memory(0x8025e150,1) != 0:
            write_memory(0x8025e151, read_memory(0x8025e150, 1), 1)
            write_memory(0x8025e150, 0, 1)
    #Make it so if you beat Bhashea High Road, p2 loads without needing to enter Kadishu
    elif level_id==lost_kingdoms_2_regions["Bhashea High Road"]["levelID"] and ctx.slot_data.get("randomize_levels", 0):
        #If Kadishu hasn't been beaten, then load the first part of it
        if read_memory(0x8025dc4c,1)==0:
            if read_memory(0x8025dc91,1)!=0:
                write_memory(0x8025dc90,read_memory(0x8025dc91,1),1)
                write_memory(0x8025dc91, 0, 1)
        #If Kadishu has been beaten exactly once, load the 2nd part of it
        elif read_memory(0x8025dc4c,1)==2:
            if read_memory(0x8025dc91,1)==0:
                write_memory(0x8025dc91, 4, 1)
    #Put the value back in the right place if not in Bhashea High Road
    if not is_in_level() and ctx.slot_data.get("randomize_levels", 0):
        if read_memory(0x8025dc90,1) != 0:
            write_memory(0x8025dc91, read_memory(0x8025dc90,1), 1)
            write_memory(0x8025dc90, 0, 1)


    #Ensure you can place the fossils in fossil boneyard, open the doors in Nobleman's Residence,
    #the fountain in Holzogh Town and the gate in Plains of Rowahl
    if ((level_id==lost_kingdoms_2_regions["Fossil Boneyard"]["levelID"] and read_memory(0x802e941e) == 55232) or
            (level_id==lost_kingdoms_2_regions["Plains of Rowahl"]["levelID"] and read_memory(0x802e941e) in [55296,55344] and read_memory(0x802250c9)==0) or
            (level_id==lost_kingdoms_2_regions["Holzogh Town"]["levelID"] and read_memory(0x802e941e) == 55264) or
            (level_id==lost_kingdoms_2_regions["Nobleman's Residence"]["levelID"] and read_memory(0x802e941e) in [55296,55472,55456,55440,55488] and read_memory(0x8025dc0c,1)!=0)):
        write_memory(0x8006e7c4, 0x8003005c, 4)
    #Make it so the guard that opens up Krasheen Mountains always spawns, but not if they haven't finished the forced sequence(to ensure stone of sealing works)
    elif level_id==lost_kingdoms_2_regions["Royal Tower, Lower"]["levelID"] and read_memory(0x8025e04c, 1) == 1:
        write_memory(0x8006e7c4,0x38000001,4)
    else:
        write_memory(0x8006e7c4, 0x80030004, 4)

    if ctx.slot_data.get("randomize_levels", 0):
        global level_ordering
        if is_in_level():
            if level_id == lost_kingdoms_2_regions["Nobleman's Residence"]["levelID"]:
                write_memory(0x810879f8, lost_kingdoms_2_regions[level_ordering["Nobleman's Residence Exit 1"]]["levelID"], 4)
                write_memory(0x81088290, lost_kingdoms_2_regions[level_ordering["Nobleman's Residence Exit 2"]]["levelID"], 4)
            elif level_id == lost_kingdoms_2_regions["Bhashea High Road"]["levelID"]:
                # Vanilla: Kendarie Fortress (Exit 2), Kadishu (Exit 1), Bhashea Castle (Exit 3)
                write_memory(0x8113f89c, lost_kingdoms_2_regions[level_ordering["Bhashea High Road Exit 1"]]["levelID"], 4)
                write_memory(0x8113fcfc, lost_kingdoms_2_regions[level_ordering["Bhashea High Road Exit 2"]]["levelID"], 4)
                write_memory(0x8113ff08, lost_kingdoms_2_regions[level_ordering["Bhashea High Road Exit 3"]]["levelID"], 4)
            elif level_id == lost_kingdoms_2_regions["Kadishu"]["levelID"]:
                # Vanilla: Gromtull Desert (Exit 2), Kadishu Shop (Exit 1)
                write_memory(0x810c99dc, lost_kingdoms_2_regions[level_ordering["Kadishu Exit 2"]]["levelID"], 4)
                write_memory(0x810c9774, lost_kingdoms_2_regions[level_ordering["Kadishu Exit 1"]]["levelID"], 4)
                write_memory(0x810c9780, lost_kingdoms_2_regions[level_ordering["Kadishu Exit 1"]]["levelID"], 4)
            elif level_id == lost_kingdoms_2_regions["Gromtull Desert"]["levelID"]:
                write_memory(0x8106dcac, lost_kingdoms_2_regions[level_ordering["Gromtull Desert Exit 1"]]["levelID"], 4)
            elif level_id == lost_kingdoms_2_regions["Kendarie Fortress"]["levelID"]:
                write_memory(0x81052dbc, lost_kingdoms_2_regions[level_ordering["Kendarie Fortress Exit 1"]]["levelID"], 4)
            elif level_id == lost_kingdoms_2_regions["Runestone Caverns - Upper Chambers"]["levelID"]:
                write_memory(0x80f91f04, lost_kingdoms_2_regions[level_ordering["Runestone Caverns - Upper Chambers Exit 1"]]["levelID"], 4)
            elif level_id == lost_kingdoms_2_regions["Runestone Caverns - Lower Chambers"]["levelID"]:
                write_memory(0x81053798, lost_kingdoms_2_regions[level_ordering["Runestone Caverns - Lower Chambers Exit 1"]]["levelID"], 4)
            elif level_id == lost_kingdoms_2_regions["Ruldo Forest"]["levelID"]:
                # Vanilla: Fossil Boneyard (Exit 1), Sacred Battle Arena 1 (Exit 2)
                write_memory(0x80ffa518, lost_kingdoms_2_regions[level_ordering["Ruldo Forest Exit 1"]]["levelID"], 4)
                write_memory(0x80ffacf8, lost_kingdoms_2_regions[level_ordering["Ruldo Forest Exit 2"]]["levelID"], 4)
            elif level_id == lost_kingdoms_2_regions["Fossil Boneyard"]["levelID"]:
                write_memory(0x8100f988, lost_kingdoms_2_regions[level_ordering["Fossil Boneyard Exit 1"]]["levelID"], 4)
            elif level_id == lost_kingdoms_2_regions["Sarvan"]["levelID"]:
                write_memory(0x8104b6c8, lost_kingdoms_2_regions[level_ordering["Sarvan Exit 1"]]["levelID"], 4)
            elif level_id == lost_kingdoms_2_regions["Holzogh Town"]["levelID"]:
                write_memory(0x81113dd8, lost_kingdoms_2_regions[level_ordering["Holzogh Town Exit 1"]]["levelID"], 4)
                write_memory(0x8111488c, lost_kingdoms_2_regions[level_ordering["Holzogh Town Exit 2"]]["levelID"], 4)
            elif level_id == lost_kingdoms_2_regions["Plains of Rowahl"]["levelID"]:
                write_memory(0x81044b3c, lost_kingdoms_2_regions[level_ordering["Plains of Rowahl Exit 1"]]["levelID"], 4)
            elif level_id == lost_kingdoms_2_regions["Royal Tower, Lower"]["levelID"]:
                # Vanilla: Krasheen Mountains (Exit 1), Obenoix Gorge (Exit 2)
                write_memory(0x810c1cf4, lost_kingdoms_2_regions[level_ordering["Royal Tower, Lower Exit 1"]]["levelID"], 4)
            elif level_id == lost_kingdoms_2_regions["Krasheen Mountains"]["levelID"]:
                write_memory(0x80f2743c, lost_kingdoms_2_regions[level_ordering["Krasheen Mountains Exit 1"]]["levelID"], 4)
            elif level_id == lost_kingdoms_2_regions["Grenfoel Cathedral"]["levelID"]:
                # Vanilla: Temple of Sharacia (Exit 1), Grenfoel Cathedral Shop (Exit 2)
                write_memory(0x810ac678, lost_kingdoms_2_regions[level_ordering["Grenfoel Cathedral Exit 1"]]["levelID"], 4)
                write_memory(0x810ac70c, lost_kingdoms_2_regions[level_ordering["Grenfoel Cathedral Exit 2"]]["levelID"], 4)
                write_memory(0x810ac718, lost_kingdoms_2_regions[level_ordering["Grenfoel Cathedral Exit 2"]]["levelID"], 4)
        else:
            modify_default_level_selections()

def modify_default_level_selections():
    if is_level_unlocked("Runestone Caverns - Upper Chambers"):
        write_memory(0x80167668,0x80167420, 4)
    elif is_level_unlocked("Runestone Caverns - Lower Chambers"):
        write_memory(0x80167668, 0x80167430, 4)

    if is_level_unlocked("Kadishu"):
        write_memory(0x80167664, 0x801673e0, 4)
    elif is_level_unlocked("Fairy House"):
        write_memory(0x80167664, 0x801673f0, 4)
    elif is_level_unlocked("Kadishu Shop"):
        write_memory(0x80167664, 0x80167400, 4)

    if is_level_unlocked("Sacred Battle Arena 1"):
        write_memory(0x8016766c, 0x80167450, 4)
    elif is_level_unlocked("Sacred Battle Arena 2"):
        write_memory(0x8016766c, 0x80167460, 4)

    if is_level_unlocked("Alanjeh Castle"):
        write_memory(0x80167670, 0x80167480, 4)
    elif is_level_unlocked("Royal Tower, Lower"):
        write_memory(0x80167670, 0x80167490, 4)
    elif is_level_unlocked("Royal Tower, Middle"):
        write_memory(0x80167670, 0x801674a0, 4)
    elif is_level_unlocked("Royal Tower, Upper"):
        write_memory(0x80167670, 0x801674b0, 4)

    if is_level_unlocked("Grenfoel Cathedral"):
        write_memory(0x80167674,0x801674d0, 4)
    elif is_level_unlocked("Grenfoel Cathedral Shop"):
        write_memory(0x80167674, 0x801674e0, 4)

def is_level_unlocked(level: str) -> bool:
    return read_memory(int(lost_kingdoms_2_regions[level]["RAMAddress"],16), 1) == 128

def is_in_level() -> bool:
    return read_memory(IS_IN_LEVEL_ADDRESS, 1) == 1

def set_shop_contents_to_AP():
    for x in range(40):
        write_memory(0x80168700+(x*0x2), 0x00000000)

def open_world():
    logger.debug("Opening world")
    for region in lost_kingdoms_2_regions:
        write_memory(int(lost_kingdoms_2_regions[region]["RAMAddress"],16), 128, 1)

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
                if read_memory(Emperor_Health_ADDRESS) == 0 and read_memory(Emperor_ID_ADDRESS,4) == 2169768032:
                    await ctx.send_msgs([{
                        "cmd": "StatusUpdate",
                        "status": ClientStatus.CLIENT_GOAL
                    }])
                    HAS_GOALED = True
            case 2:
                if read_memory(RED_FAIRY_COUNT_ADDRESS,1) + read_memory(RED_FAIRY_COUNT_ADDRESS+1,1) >= ctx.slot_data.get("collect_red_fairies_amount", 50):
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

    level_name = lost_kingdoms_2_locations[location].get("level")
    if level_name == "Menu" or lost_kingdoms_2_regions[level_name]["levelID"] == read_memory(LEVEL_ID_ADDRESS, 1):
        match lost_kingdoms_2_locations[location]["type"]:
            case "Chest" | "Red Fairy" | "Magic Boosters":
                if lost_kingdoms_2_locations[location]["RAMAddress"]!="":
                    if (location == "Temple of Sharacia - help valkyrie") | (location == "Temple of Sharacia - help ashura"):
                        if read_memory(Valkyrie_Ashura_ADDRESS) != 256:
                            return False
                    elif "Fairy House - collect" in location:
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
                return bit_value
            case "Combo":
                memory_value = read_memory(COMBO_LOCATION_ADDRESS, 8)
                bit_value = (memory_value >> lost_kingdoms_2_combos[location]["bitOffset"]) & 1
                return bit_value
            case "Enemysanity":
                if is_in_level():
                    return check_enemy_death(location)
                return False
            case "Shop Purchase":
                memory_value = read_memory(SHOP_LOCATION_ADDRESS, 5)
                bit_value = (memory_value >> lost_kingdoms_2_shop_purchases[location]["bitOffset"]) & 1
                return bit_value

        return False
    else:
        return False

def check_enemy_death(location: str) -> bool:
    # Helper to get all enemies in the same group for the current level
    def get_group_members(target_location):
        group_id = target_location["group"]
        level_id = target_location["level"]
        return [
            loc_name for loc_name, data in lost_kingdoms_2_locations.items()
            if data.get("group") == group_id and data.get("level") == level_id
        ]

    # Revised check logic
    current_loc_data = lost_kingdoms_2_locations[location]
    target_species = location.split(" - ")[-1].split(" #")[0]

    # If already sent, skip
    if current_loc_data["currentState"] == 2:
        return False

    # Identify the "Pool" of addresses for this group
    group_member_names = get_group_members(current_loc_data)
    group_addresses = [lost_kingdoms_2_locations[name]["RAMAddress"] for name in group_member_names]

    # STATE 0: Waiting for a valid, ACTIVE spawn
    if current_loc_data["currentState"] == 0:
        for addr in group_addresses:
            # Check 1: Is the memory slot actually active (set to 1)?
            is_alive = read_memory(int(addr, 16), 1) == 1

            if is_alive:
                # Check 2: Does the species in this active slot match our target?
                if get_enemy_species(addr) == target_species:
                    # Record which specific address this location is currently 'using'
                    current_loc_data["active_addr"] = addr
                    current_loc_data["currentState"] = 1
                    break

    # 2. Check for Death (currentState 2)
    elif current_loc_data["currentState"] == 1:
        target_species = location.split(" - ")[-1].split(" #")[0]

        # Count how many locations of this species in this group are already "Done" (State 2)
        already_killed_count = sum(
            1 for name in group_member_names
            if name.startswith(location.rsplit(" #", 1)[0]) and lost_kingdoms_2_locations[name]["currentState"] == 2
        )

        # Count how many slots in RAM are currently dead and match our species
        current_dead_in_ram = 0
        for addr in group_addresses:
            # Check your death flag logic: read_memory(...) == 0
            is_dead = read_memory(int(addr, 16), 1) == 0 and read_memory(int(addr, 16) + 0x10, 2) == 0

            if is_dead:
                # Use your species helper to see what was in this slot
                if get_enemy_species(addr) == target_species:
                    current_dead_in_ram += 1

        # If there are more dead ravens in RAM than we have already "checked off" in AP,
        # then THIS specific location (e.g., Raven #2) is the one that just died.
        if current_dead_in_ram > already_killed_count:
            current_loc_data["currentState"] = 2
            return True

    return False

def get_enemy_species(RAMAddress: str) -> str:
    hex_code_of_enemy = read_memory(read_memory(int(RAMAddress, 16) - 0x54,4)+0x8,2)
    match hex_code_of_enemy:
        case 0x0:
            return ""
        case 0x00f2:
            return "Tentacle"
        case 0x00f1:
            return "God of Harmony"
        case 0x00fd:
            return "Leod VIII"
        case 0x00f0:
            return "Body of the God"
        case 0x0120:
            return "Kendarie Soldier"

    for card in lost_kingdoms_2_cards:
        if hex_code_of_enemy == int(lost_kingdoms_2_cards[card]["hexCode"].lower(), 16):
            return str(card)

    logger.debug("Missing species " + str(hex_code_of_enemy))
    return ""


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
    if ctx.slot is not None and is_in_level() and read_memory(LEVEL_ID_ADDRESS, 1) != 1:
        cur_health = read_memory(CURR_HEALTH_ADDR)
        if cur_health <= 0:
            if not ctx.has_send_death and time.time() >= ctx.last_death_link + 10:
                ctx.has_send_death = True
                await ctx.send_death(ctx.player_names[1] + " did not believe in the heart of the cards.")
        else:
            ctx.has_send_death = False


async def check_map(ctx: LK2Context) -> None:
    """
    Check if the player's current map has changed.
    If the player is in a new map then send a bounce packet to the AP server with level ID.
    """
    if ctx.slot is None:
        return

    level_id = 0  # overworld menu
    if is_in_level():
        level_id = read_memory(LEVEL_ID_ADDRESS, 1)
    if level_id == ctx.level_id:
        return

    logger.debug(f"Sending bounce packet for map update to level_id {level_id}")
    await ctx.send_msgs([{
        "cmd": "Bounce",
        "slots": [ctx.slot],
        "data": {
            "level_id": level_id
        }
    }])
    ctx.level_id = level_id

def check_ingame() -> bool:
    """
    Check if the player is currently in-game, and not the main menu.
    :return: `True` if the player is in-game, otherwise `False`.
    """
    try:
        return read_memory(IS_IN_GAME_ADDR,4) != 0
    except:
        return False

def check_cards_loaded() -> bool:
    try:
        return read_memory(CARDS_LOADED,4) == 80416
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
                if (not ONE_TIME_MODIFIERS_MAIN_MENU) and ctx.slot_data and not check_ingame():
                    logger.debug("Seed is " + str(ctx.slot_data["Seed"]))
                    logger.debug("Triggering one time main menu modifiers")
                    #This prevents saves from other playthroughs being loaded.
                    replace_game_id(ctx)
                    ONE_TIME_MODIFIERS_MAIN_MENU = True
                    ONE_TIME_MODIFIERS_IN_GAME = False
                if (not ONE_TIME_MODIFIERS_IN_GAME) and ctx.slot_data and check_ingame():
                    logger.debug("Triggering one time in game modifiers")
                    randomize_levels(ctx)
                    logger.debug("Slot data:" + str(ctx.slot_data))
                    if ctx.slot_data.get("open_world", 0):
                        open_world()
                    if ctx.slot_data.get("shopsanity", 0):
                        pass
                        #set_shop_contents_to_AP()
                    ONE_TIME_MODIFIERS_IN_GAME = True
                    ONE_TIME_MODIFIERS_MAIN_MENU = False
                if ctx.slot is not None :
                    if check_ingame():
                        if "DeathLink" in ctx.tags:
                            await check_death(ctx)
                        #if ctx.slot_data.get("shopsanity", 0) & check_inshop():
                            #await track_shop_purchases()
                        level_modifications(ctx)
                        await check_victory_conditions(ctx)
                        await give_items(ctx)
                        await check_locations(ctx)
                        await give_progressive_attribute_proficiency(ctx)
                        await check_map(ctx)
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
                    if dolphin_memory_engine.read_bytes(0x80000000, 6) == 0:
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

