import json, os
import random
import shutil
import struct
from random import Random

import Utils

from worlds.LostKingdoms2 import *
from worlds.LostKingdoms2.iso_helper.DOL_Updater import update_dol_offsets

from .client.constants import CLIENT_VERSION, AP_WORLD_VERSION_NAME
import logging

logger = logging.getLogger()

RANDOMIZER_NAME = "Lost Kingdoms II"

CUSTOM_CODE_JUMP_1 = 0x8007b724
CUSTOM_CODE_RETURN_1 = 0x80005FE4
CUSTOM_CODE_ADDRESS_1 = 0x80004b50
CUSTOM_CODE_JUMP_2 = 0x80091274
CUSTOM_CODE_RETURN_2 = 0x800F7F04
CUSTOM_CODE_ADDRESS_2 = CUSTOM_CODE_ADDRESS_1+60
CUSTOM_LEVEL_UP_CODE = CUSTOM_CODE_ADDRESS_2+108
CUSTOM_ATTRIBUTE_UP_CODE = CUSTOM_LEVEL_UP_CODE+80
CUSTOM_ATTRIBUTE_UP_TRIGGER = 0x8025d01c
INVALIDATE_ADDRESS = 0x800f31dc
PROGRESSIVE_LEVELING_ADDRESS = 0X8025d01d
CARD_INFO_TABLE_ADDRESS = 0x80732be0
CARD_SHOP_ADDRESS = 0x80168700
STARTING_DECK_ADDRESS = 0x80152640
BONUS_DRAW_ADDRESS = 0x80168168


class LK2Randomizer:
    def __init__(self, clean_iso_path: str, randomized_output_file_path: str, ap_output_data: bytes, cardback_gtx: bytes = None, debug_flag=False):
        # Takes note of the provided Randomized Folder path and if files should be exported instead of making an ISO.
        self.debug = debug_flag
        self.clean_iso_path = clean_iso_path
        self.randomized_output_file_path = randomized_output_file_path
        self.cardback_gtx = cardback_gtx
        self.output_data = json.loads(ap_output_data.decode('utf-8'))

        # Set the random's seed for uses in other files.
        self.random = Random()
        local_seed: str = str(self.output_data["Seed"])
        self.random.seed(local_seed)

        logger.info(randomized_output_file_path)
        logger.info("Beginning Log Patching Process")
        try:
            new_iso = self.copy_iso(clean_iso_path, randomized_output_file_path, local_seed)
        except IOError:
            logger.error("IO Error")
            raise Exception("'" + randomized_output_file_path + "' is currently in use by another program.")

        # Make sure that the server and client versions match before attempting to patch ISO.
        self._check_server_version(self.output_data)

        # Saves the randomized iso file, with all files updated.
        if new_iso is not None:
            self.write_to_iso(new_iso)

    def copy_iso(self, iso_path, destination, seed):
        # make copy of .iso with filename @newISO
        logger.info("Rom copying to " + destination)
        copy_file(iso_path, destination)
        logger.info("Rom copied to " + destination)
        return destination

    def write_to_iso(self, iso):
        with open(iso, 'r+b') as iso_file:
            for key in lost_kingdoms_2_chests:
                location = lost_kingdoms_2_chests[key]
                if location["isoAddress"] != "":
                    iso_file.seek(int(location["isoAddress"],16))
                    iso_file.write((int("0", 16).to_bytes(1, byteorder='big')))
            self.patch_sp_tex_entry(iso_file)
            self.modify_code(iso_file)
            if self.output_data.get("randomize_magic_stone_costs", 0):
                self.randomize_magic_stone_costs(iso_file)
            if self.output_data.get("randomize_starting_deck", 0):
                self.randomize_starting_deck(iso_file)
            if self.output_data.get("randomize_shop_contents", 0):
                self.randomize_shop_contents(iso_file)
            if self.output_data.get("randomize_bonus_draws", 0):
                self.randomize_bonus_draws(iso_file)

        self.write_string(iso,0x1E000,0x00000100,0x80003100,0x80003DA0,self.output_data["Name"])

        logger.info("Rom modified")

    def modify_code(self,iso_file):
        self.patch_iso_from_ram(iso_file,0x8006e78c, 0x80850004)
        self.patch_iso_from_ram(iso_file,0x8006e798, 0x90050004)
        self.patch_iso_from_ram(iso_file, 0x8006e7c4, 0x80030004)
        self.patch_iso_from_ram(iso_file, 0x80075738, 0x3C808026)
        self.patch_iso_from_ram(iso_file, 0x8007573c, 0x8004D014)
        self.patch_iso_from_ram(iso_file, 0x80075740, 0x60000000)
        self.patch_iso_from_ram(iso_file, 0x8007b334, 0x3C608026)
        self.patch_iso_from_ram(iso_file, 0x8007b338, 0x8003D014)
        self.patch_iso_from_ram(iso_file, 0x800dc438, 0x60000000)

        if self.output_data.get("fairysanity", 0):
            self.patch_iso_from_ram(iso_file, 0x80077034, 0x38040000)

        self.patch_iso_from_ram(iso_file,CUSTOM_CODE_JUMP_1, self.make_bl(CUSTOM_CODE_JUMP_1, CUSTOM_CODE_ADDRESS_1), 4)
        # 1. Prologue: Create Stack Frame and Save Registers
        # stwu sp, -0x20(sp) -> Decrement SP and save old SP
        self.patch_iso_from_ram(iso_file, CUSTOM_CODE_ADDRESS_1, 0x9421FFE0)
        # stw r3, 0x0008(sp) -> Save r3 into our safe frame
        self.patch_iso_from_ram(iso_file, CUSTOM_CODE_ADDRESS_1 + 4, 0x90610008)
        # stw r4, 0x000C(sp) -> Save r4 into our safe frame
        self.patch_iso_from_ram(iso_file, CUSTOM_CODE_ADDRESS_1 + 8, 0x9081000C)
        # mflr r0 / stw r0, 0x0024(sp) -> Save LR into the 'Linkage Area' (parent's frame)
        self.patch_iso_from_ram(iso_file, CUSTOM_CODE_ADDRESS_1 + 12, 0x7C0802A6)
        self.patch_iso_from_ram(iso_file, CUSTOM_CODE_ADDRESS_1 + 16, 0x90010024)
        
        # 2. Logic: Setup and Call ICInvalidateRange
        # lis r3, 0x8006 / ori r3, r3, 0xE7C4
        self.patch_iso_from_ram(iso_file, CUSTOM_CODE_ADDRESS_1 + 20, 0x3C608006)
        self.patch_iso_from_ram(iso_file, CUSTOM_CODE_ADDRESS_1 + 24, 0x6063E7C4)
        # li r4, 4
        self.patch_iso_from_ram(iso_file, CUSTOM_CODE_ADDRESS_1 + 28, 0x38800004)
        # bl INVALIDATE_ADDRESS
        self.patch_iso_from_ram(iso_file, CUSTOM_CODE_ADDRESS_1 + 32, self.make_bl(CUSTOM_CODE_ADDRESS_1 + 32, INVALIDATE_ADDRESS))
        
        # 3. Epilogue: Restore Registers and Tear Down Frame
        # lwz r0, 0x0024(sp) / mtlr r0 -> Restore the original LR
        self.patch_iso_from_ram(iso_file, CUSTOM_CODE_ADDRESS_1 + 36, 0x80010024)
        self.patch_iso_from_ram(iso_file, CUSTOM_CODE_ADDRESS_1 + 40, 0x7C0803A6)
        # lwz r3, 0x0008(sp) -> Restore r3
        self.patch_iso_from_ram(iso_file, CUSTOM_CODE_ADDRESS_1 + 44, 0x80610008)
        # lwz r4, 0x000C(sp) -> Restore r4
        self.patch_iso_from_ram(iso_file, CUSTOM_CODE_ADDRESS_1 + 48, 0x8081000C)
        # addi sp, sp, 32 -> Collapse the stack frame
        self.patch_iso_from_ram(iso_file, CUSTOM_CODE_ADDRESS_1 + 52, 0x38210020)
        
        # 4. Final Jump: Continue to original destination
        # Now that SP and LR are restored, the 'blr' at the end of RETURN_1
        # will correctly return to the original hijacked site's caller.
        self.patch_iso_from_ram(iso_file, CUSTOM_CODE_ADDRESS_1 + 56, self.make_b(CUSTOM_CODE_ADDRESS_1 + 56, CUSTOM_CODE_RETURN_1))
        
        # Change the bl at CUSTOM_CODE_JUMP_2 to go to our custom code
        self.patch_iso_from_ram(iso_file, CUSTOM_CODE_JUMP_2, self.make_bl(CUSTOM_CODE_JUMP_2, CUSTOM_CODE_ADDRESS_2))
        # Allocate stack frame
        self.patch_iso_from_ram(iso_file, CUSTOM_CODE_ADDRESS_2, 0x9421FFE0)  # stwu sp, -0x20(sp)
        # Store the current value of r3
        self.patch_iso_from_ram(iso_file, CUSTOM_CODE_ADDRESS_2 + 4, 0x9061000C)  # stw r3, 0x000C(sp)
        # Store the current value of r4
        self.patch_iso_from_ram(iso_file, CUSTOM_CODE_ADDRESS_2 + 8, 0x90810010)  # stw r4, 0x0010(sp)
        # Store the current value of r5
        self.patch_iso_from_ram(iso_file, CUSTOM_CODE_ADDRESS_2 + 12, 0x90A10014)  # stw r5, 0x0014(sp)
        # Store the address we want to invalidate in r3
        self.patch_iso_from_ram(iso_file, CUSTOM_CODE_ADDRESS_2 + 16, 0x3C608000)  # lis r3, 0x8000
        self.patch_iso_from_ram(iso_file, CUSTOM_CODE_ADDRESS_2 + 20, 0x606318A8)  # ori r3, r3, 0x18A8
        # Store the value 0x28 to invalidate all the nops
        self.patch_iso_from_ram(iso_file, CUSTOM_CODE_ADDRESS_2 + 24, 0x38800028)  # li r4, 0x28
        # Store the LR onto the stack
        self.patch_iso_from_ram(iso_file, CUSTOM_CODE_ADDRESS_2 + 28, 0x7C0802A6)  # mflr r0
        self.patch_iso_from_ram(iso_file, CUSTOM_CODE_ADDRESS_2 + 32, 0x90010008)  # stw r0, 0x0008(sp)
        # Write 10 nop instructions that can be used in the future
        for x in range(10):
            self.patch_iso_from_ram(iso_file, CUSTOM_CODE_ADDRESS_2 + x * 4 + 36, 0x60000000)
        if self.output_data.get("progressive_leveling", 0):
            # Progressive leveling code jump
            self.patch_iso_from_ram(iso_file, CUSTOM_CODE_ADDRESS_2 + 36, self.make_bl(CUSTOM_CODE_ADDRESS_2 + 36, CUSTOM_LEVEL_UP_CODE))
        if self.output_data.get("progressive_attribute_proficiencies", 0):
            #Add the code to call the Attribute up code
            self.patch_iso_from_ram(iso_file, CUSTOM_CODE_ADDRESS_2+44, self.make_bl(CUSTOM_CODE_ADDRESS_2+44, CUSTOM_ATTRIBUTE_UP_CODE))
        # Jump to the ICInvalidateRange function
        self.patch_iso_from_ram(iso_file, CUSTOM_CODE_ADDRESS_2 + 76, self.make_bl(CUSTOM_CODE_ADDRESS_2 + 76, INVALIDATE_ADDRESS))
        # Write the stored LR back into the LR register
        self.patch_iso_from_ram(iso_file, CUSTOM_CODE_ADDRESS_2 + 80, 0x80010008)  # lwz r0, 0x0008(sp)
        self.patch_iso_from_ram(iso_file, CUSTOM_CODE_ADDRESS_2 + 84, 0x7C0803A6)  # mtlr r0
        # Write the stored r3 value back into r3
        self.patch_iso_from_ram(iso_file, CUSTOM_CODE_ADDRESS_2 + 88, 0x8061000C)  # lwz r3, 0x0008(sp)
        # Write the stored value of r4 back into r4
        self.patch_iso_from_ram(iso_file, CUSTOM_CODE_ADDRESS_2 + 92, 0x80810010)  # lwz r4, 0x0010(sp)
        # Write the stored value of r5 back into r5
        self.patch_iso_from_ram(iso_file, CUSTOM_CODE_ADDRESS_2 + 96, 0x80A10014)  # lwz r5, 0x0014(sp)
        # Deallocate stack frame
        self.patch_iso_from_ram(iso_file, CUSTOM_CODE_ADDRESS_2 + 100, 0x38210020)  # addi sp, sp, 0x20
        # Jump back to original destination
        self.patch_iso_from_ram(iso_file, CUSTOM_CODE_ADDRESS_2 + 104, self.make_b(CUSTOM_CODE_ADDRESS_2 + 104, CUSTOM_CODE_RETURN_2))
        
        if self.output_data.get("progressive_leveling", 0):
            #Remove the xp check
            self.patch_iso_from_ram(iso_file, 0x800736d0, 0x60000000)
            #Remove the standard level up function call
            self.patch_iso_from_ram(iso_file, 0x8007d0f8, 0x60000000)
        
            #Level up trigger
            # --- PROLOGUE: Save State & Create Frame ---
            # --- Save State ---
            self.patch_iso_from_ram(iso_file, CUSTOM_LEVEL_UP_CODE, 0x9421FFD0)  # stwu sp, -0x30(sp)
            self.patch_iso_from_ram(iso_file, CUSTOM_LEVEL_UP_CODE + 4, 0x7C0802A6)  # mflr r0
            self.patch_iso_from_ram(iso_file, CUSTOM_LEVEL_UP_CODE + 8, 0x90010024)  # stw r0, 0x0024(sp)
            self.patch_iso_from_ram(iso_file, CUSTOM_LEVEL_UP_CODE + 12, 0x90610008)  # stw r3, 0x0008(sp)
            self.patch_iso_from_ram(iso_file, CUSTOM_LEVEL_UP_CODE + 16, 0x9081000C)  # stw r4, 0x000C(sp)
        
            # --- Load Desired Level (0x8025D01D) ---
            self.patch_iso_from_ram(iso_file, CUSTOM_LEVEL_UP_CODE + 20, 0x3C608025)  # lis r3, 0x8025
            self.patch_iso_from_ram(iso_file, CUSTOM_LEVEL_UP_CODE + 24, 0x6063D01D)  # ori r3, r3, 0xD01D
            self.patch_iso_from_ram(iso_file, CUSTOM_LEVEL_UP_CODE + 28, 0x88030000)  # lbz r0, 0(r3)
        
            # --- Load Current Level (0x8025D02C) ---
            self.patch_iso_from_ram(iso_file, CUSTOM_LEVEL_UP_CODE + 32, 0x3C808025)  # lis r4, 0x8025
            self.patch_iso_from_ram(iso_file, CUSTOM_LEVEL_UP_CODE + 36, 0x6084D02C)  # ori r4, r4, 0xD02C
            self.patch_iso_from_ram(iso_file, CUSTOM_LEVEL_UP_CODE + 40, 0x88840000)  # lbz r4, 0(r4)
        
            # --- Compare and Call ---
            self.patch_iso_from_ram(iso_file, CUSTOM_LEVEL_UP_CODE + 44, 0x7C002040)  # cmplw r0, r4
            self.patch_iso_from_ram(iso_file, CUSTOM_LEVEL_UP_CODE + 48, 0x40810008)  # ble +0x08 (Skip bl if r0 <= r4)
            self.patch_iso_from_ram(iso_file, CUSTOM_LEVEL_UP_CODE + 52, self.make_bl(CUSTOM_LEVEL_UP_CODE + 52, 0x80073674))
        
            # --- Cleanup ---
            self.patch_iso_from_ram(iso_file, CUSTOM_LEVEL_UP_CODE + 56, 0x80010024)  # lwz r0, 0x0024(sp)
            self.patch_iso_from_ram(iso_file, CUSTOM_LEVEL_UP_CODE + 60, 0x7C0803A6)  # mtlr r0
            self.patch_iso_from_ram(iso_file, CUSTOM_LEVEL_UP_CODE + 64, 0x80610008)  # lwz r3, 0x0008(sp)
            self.patch_iso_from_ram(iso_file, CUSTOM_LEVEL_UP_CODE + 68, 0x8081000C)  # lwz r4, 0x000C(sp)
            self.patch_iso_from_ram(iso_file, CUSTOM_LEVEL_UP_CODE + 72, 0x38210030)  # addi sp, sp, 0x30
            self.patch_iso_from_ram(iso_file, CUSTOM_LEVEL_UP_CODE + 76, 0x4E800020)  # blr
        
        if self.output_data.get("progressive_attribute_proficiencies", 0):
            #Remove the attribute xp additions/subtractions
            self.patch_iso_from_ram(iso_file, 0x80070af8, 0x48000144)
            self.patch_iso_from_ram(iso_file, 0x80070aec, 0x480001dc)
        
            # 0x00: Prologue
            self.patch_iso_from_ram(iso_file, CUSTOM_ATTRIBUTE_UP_CODE + 0, 0x9421FFD0)  # stwu sp, -0x30(sp)
            self.patch_iso_from_ram(iso_file, CUSTOM_ATTRIBUTE_UP_CODE + 4, 0x7C0802A6)  # mflr r0
            self.patch_iso_from_ram(iso_file, CUSTOM_ATTRIBUTE_UP_CODE + 8, 0x90010024)  # stw r0, 0x0024(sp)
            self.patch_iso_from_ram(iso_file, CUSTOM_ATTRIBUTE_UP_CODE + 12, 0x90610008)  # stw r3, 0x0008(sp)
            self.patch_iso_from_ram(iso_file, CUSTOM_ATTRIBUTE_UP_CODE + 16, 0x90810010)  # stw r4, 0x0010(sp)
        
            # +20: Address Prep & Trigger Check
            self.patch_iso_from_ram(iso_file, CUSTOM_ATTRIBUTE_UP_CODE + 20, 0x3C608025)  # lis r3, 0x8025
            self.patch_iso_from_ram(iso_file, CUSTOM_ATTRIBUTE_UP_CODE + 24, 0x6063D01E)  # ori r3, r3, 0xD01E
            self.patch_iso_from_ram(iso_file, CUSTOM_ATTRIBUTE_UP_CODE + 28, 0x88030000)  # lbz r0, 0(r3)
            self.patch_iso_from_ram(iso_file, CUSTOM_ATTRIBUTE_UP_CODE + 32, 0x2C000000)  # cmpwi r0, 0
        
            # +36: Skip if 0 (Jump 28 bytes forward to +64)
            self.patch_iso_from_ram(iso_file, CUSTOM_ATTRIBUTE_UP_CODE + 36, 0x4182001C)  # beq +0x1C
        
            # +40: Setup Arguments & Call
            self.patch_iso_from_ram(iso_file, CUSTOM_ATTRIBUTE_UP_CODE + 40, 0x38600000)  # li r3, 0
            self.patch_iso_from_ram(iso_file, CUSTOM_ATTRIBUTE_UP_CODE + 44, self.make_bl(CUSTOM_ATTRIBUTE_UP_CODE + 44, 0x80070A88))
        
            # +48: Fresh Address Prep for Reset (Ensures r3 is correct)
            self.patch_iso_from_ram(iso_file, CUSTOM_ATTRIBUTE_UP_CODE + 48, 0x3C608025)  # lis r3, 0x8025
            self.patch_iso_from_ram(iso_file, CUSTOM_ATTRIBUTE_UP_CODE + 52, 0x6063D01E)  # ori r3, r3, 0xD01E
            self.patch_iso_from_ram(iso_file, CUSTOM_ATTRIBUTE_UP_CODE + 56, 0x38000000)  # li r0, 0
            self.patch_iso_from_ram(iso_file, CUSTOM_ATTRIBUTE_UP_CODE + 60, 0x98030000)  # stb r0, 0(r3)
        
            # +64: Cleanup & Return
            self.patch_iso_from_ram(iso_file, CUSTOM_ATTRIBUTE_UP_CODE + 64, 0x80010024)  # lwz r0, 0x0024(sp)
            self.patch_iso_from_ram(iso_file, CUSTOM_ATTRIBUTE_UP_CODE + 68, 0x7C0803A6)  # mtlr r0
            self.patch_iso_from_ram(iso_file, CUSTOM_ATTRIBUTE_UP_CODE + 72, 0x80610008)  # lwz r3, 0x0008(sp)
            self.patch_iso_from_ram(iso_file, CUSTOM_ATTRIBUTE_UP_CODE + 76, 0x80810010)  # lwz r4, 0x0010(sp)
            self.patch_iso_from_ram(iso_file, CUSTOM_ATTRIBUTE_UP_CODE + 80, 0x38210030)  # addi sp, sp, 48
            self.patch_iso_from_ram(iso_file, CUSTOM_ATTRIBUTE_UP_CODE + 84, 0x4E800020)  # blr
        
        #setup for level randomization
        if self.output_data.get("randomize_levels", 0):
            self.patch_iso_from_ram(iso_file, 0x800a69a8, 0x60000000)

    # The higher the bias value, the less bias there is. 1 is the minimum
    def get_card_weights(self, cards, is_weighted: bool, target_cost: int, bias: int = 3) -> list[int]:
        weights = []
        for card_name in cards:
            if is_weighted:
                weights.append(1 / (abs(lost_kingdoms_2_cards[card_name]["mana_cost"] - target_cost) + bias))
            else:
                weights.append(1)

        return weights

    def randomize_shop_contents(self, iso_file):
        random.seed(self.output_data.get("Seed", -1))
        cards = sorted(list(lost_kingdoms_2_cards.keys()))
        excluded_cards = lost_kingdoms_2_flying_cards + lost_kingdoms_2_jumping_cards + ["God of Destruction"] + [
            "Stone Golem"]
        cards = sorted(list(set(cards) - set(excluded_cards)))

        for x in range(32):
            weights = self.get_card_weights(cards, self.output_data.get("randomize_shop_contents", 0) == 1, (x // 8) * 4)
            card_name = random.choices(cards, weights=weights, k=1)[0]
            logger.debug("Card set to shop slot " + str(x) + ": " + card_name)
            # Card IDs are 2 bytes
            self.patch_iso_from_ram(iso_file, CARD_SHOP_ADDRESS + x * 2,
                                    int(lost_kingdoms_2_cards[card_name]["hexCode"], 16), 2)
            cards.remove(card_name)

        # Add custom prices for cards that lack prices
        for card in lostkingdoms_2_custom_prices:
            # Prices are usually 2 bytes
            self.patch_iso_from_ram(iso_file, CARD_INFO_TABLE_ADDRESS + 230 + 22 * 16 * lost_kingdoms_2_cards[card][
                "orderInMemory"], lostkingdoms_2_custom_prices[card]["price"], 2)

    def randomize_starting_deck(self, iso_file):
        random.seed(self.output_data.get("Seed", -1) + 1)
        cards = sorted(list(lost_kingdoms_2_cards.keys()))
        excluded_cards = lost_kingdoms_2_flying_cards + lost_kingdoms_2_jumping_cards + ["God of Destruction"] + [
            "Stone Golem"]
        cards = sorted(list(set(cards) - set(excluded_cards)))

        for x in range(12):
            weights = self.get_card_weights(cards, self.output_data.get("randomize_starting_deck", 0) == 1, 1)
            card_name = random.choices(cards, weights=weights, k=1)[0]
            cards.remove(card_name)
            # Card IDs are 2 bytes
            self.patch_iso_from_ram(iso_file, STARTING_DECK_ADDRESS + x * 2,
                                    int(lost_kingdoms_2_cards[card_name]["hexCode"], 16), 2)

    def randomize_bonus_draws(self, iso_file):
        random.seed(self.output_data.get("Seed", -1) + 2)
        cards = sorted(list(lost_kingdoms_2_cards.keys()))
        excluded_cards = lost_kingdoms_2_flying_cards + lost_kingdoms_2_jumping_cards + ["God of Destruction"] + [
            "Stone Golem"]
        cards = sorted(list(set(cards) - set(excluded_cards)))
        group_dict = {}

        for key in lost_kingdoms_2_bonus_draws:
            bonus_draw = lost_kingdoms_2_bonus_draws[key]
            if group_dict.get(bonus_draw["cardGroup"], 0):
                card_name = group_dict.get(bonus_draw["cardGroup"])
                self.patch_iso_from_ram(iso_file, BONUS_DRAW_ADDRESS + int(bonus_draw["address"], 16) - 0x183169,
                                        int(lost_kingdoms_2_cards[card_name]["hexCode"], 16), 2)
            else:
                weights = self.get_card_weights(cards, self.output_data.get("randomize_bonus_draws", 0) == 1,
                                           bonus_draw["cardGroup"] // 5)
                card_name = random.choices(cards, weights=weights, k=1)[0]
                cards.remove(card_name)
                self.patch_iso_from_ram(iso_file, BONUS_DRAW_ADDRESS + int(bonus_draw["address"], 16) - 0x183169,
                                        int(lost_kingdoms_2_cards[card_name]["hexCode"], 16), 2)
                group_dict[bonus_draw["cardGroup"]] = card_name

    def randomize_magic_stone_costs(self, iso_file):
        random.seed(self.output_data.get("Seed", -1) + 3)
        for card_name in sorted(lost_kingdoms_2_cards):
            new_mana_cost = random.randint(1, 15)
            # Mana cost is 1 byte
            self.patch_iso_from_ram(iso_file, CARD_INFO_TABLE_ADDRESS + 352 * lost_kingdoms_2_cards[card_name][
                "orderInMemory"] + 226, new_mana_cost, 1)
            lost_kingdoms_2_cards[card_name]["mana_cost"] = new_mana_cost
            logger.debug("Setting " + str(card_name) + " mana cost to " + str(new_mana_cost))

    def make_bl(self, from_addr: int, to_addr: int) -> int:
        offset = to_addr - from_addr
        return 0x48000001 | (offset & 0x3FFFFFC)

    def make_b(self, from_addr: int, to_addr: int) -> int:
        offset = to_addr - from_addr
        return 0x48000000 | (offset & 0x3FFFFFC)

    def patch_iso_from_ram(self,iso_file, target_ram: int, hex_value: int, byte_size: int = 4):
        """
        Calculates the exact ISO offset for a RAM address and writes the value.
        """
        # Based on your provided Start.dol header
        MAIN_DOL_ISO_OFFSET = 0x1D000

        # Fully expanded section list based on Start.dol header
        sections = [
            # --- START.DOL SECTIONS (0x80003100 - 0x80731E60) ---
            (0x80003100, 0x80003DA0, 0x100),  # Section 0
            (0x80003DA0, 0x80373020, 0x1DA0),  # Section 1
            (0x80373020, 0x80373800, 0x371020),  # Section 2
            (0x80373800, 0x80375E60, 0x371800),  # Section 3
            (0x80375E60, 0x8045F120, 0x373E60),  # Section 4
            (0x8045F120, 0x80731E60, 0x45D120),  # Section 5

            # --- RUNE.PDM VIRTUAL SECTION (0x80732BE0+) ---
            (0x80732BE0, 0x807F9940, 0x6835B40)
        ]

        for ram_start, ram_end, file_off in sections:
            if ram_start <= target_ram < ram_end:
                delta = target_ram - ram_start

                # This logic stays consistent with your working code
                iso_offset = MAIN_DOL_ISO_OFFSET + file_off + delta

                iso_file.seek(iso_offset)
                iso_file.write(hex_value.to_bytes(byte_size, byteorder="big"))

                # Optional debug to see where your card prices are actually landing
                # logger.debug(f"Patched RAM {hex(target_ram)} at ISO {hex(iso_offset)}")
                return

        raise ValueError(f"Address {hex(target_ram)} is not mapped in DOL or PDM sections.")

        # Convert to Big Endian bytes
        data = hex_value.to_bytes(byte_size, byteorder="big")

        # Write to file
        iso_file.seek(iso_offset)
        iso_file.write(data)
        logger.debug(f"Patched {hex(hex_value)} to ISO offset {hex(iso_offset)} (RAM: {hex(target_ram)})")

    # --- Example Usage ---
    # patch_iso_from_ram("game.iso", 0x8006e78c, 0x80850004)

    def patch_sp_tex_entry(self, iso_file, entry_index=62):
        # The signature we confirmed at 0x41D04E0
        iso_tex_header_signature = b'\x00\x0c\x2d\xc0\x00\x00\x00\x41\x00\x00\x01\x20\x00\x00\x2a\x80'

        search_start = 0x41D0000
        iso_file.seek(search_start)
        chunk = iso_file.read(4096)
        header_pos = chunk.find(iso_tex_header_signature)

        if header_pos == -1:
            logger.error("Could not find the .TEX container signature.")
            return

        sp_tex_iso_offset = search_start + header_pos

        # 1. Locate Entry 62 in the offset table
        iso_file.seek(sp_tex_iso_offset + 0x08 + (entry_index * 4))
        entry_offset = struct.unpack('>I', iso_file.read(4))[0]
        next_offset = struct.unpack('>I', iso_file.read(4))[0]

        original_total_size = next_offset - entry_offset
        target_address = sp_tex_iso_offset + entry_offset

        # 2. SURGICAL STEP: Read the original entry's header (first 32 bytes)
        # This contains the format, width, height, and mipmap data the game expects.
        iso_file.seek(target_address)
        original_gtx_header = iso_file.read(32)

        # 3. PREPARE PAYLOAD: Use your new pixels but skip its own header
        # We assume your cardback_gtx has its own 32-byte header we want to discard.
        new_pixel_data = self.cardback_gtx[32:]

        # Reconstruct the entry: Original Header + New Pixels
        final_patch = original_gtx_header + new_pixel_data

        # 4. STRICT SIZE ENFORCEMENT
        # We MUST stay within the original byte-count of Entry 62.
        if len(final_patch) > original_total_size:
            logger.warning("Patch too large; truncating to match original entry size.")
            final_patch = final_patch[:original_total_size]
        elif len(final_patch) < original_total_size:
            padding_needed = original_total_size - len(final_patch)
            final_patch += b'\x00' * padding_needed

        # 5. WRITE & VERIFY
        iso_file.seek(target_address)
        iso_file.write(final_patch)
        iso_file.flush()

        iso_file.seek(target_address)
        verification = iso_file.read(4)
        if verification == original_gtx_header[:4]:  # Should still start with 'GTX1'
            logger.info(f"SUCCESS: Surgical patch applied to Entry {entry_index} at {hex(target_address)}")
        else:
            logger.error("FAILURE: Write verification failed.")

    def write_string(self, iso_path: str,main_dol_iso_offset: int,section_file_offset: int,section_ram: int,target_ram: int,text: str,max_len: int = 64):

        delta = target_ram - section_ram
        dol_offset2 = section_file_offset + delta
        iso_offset = main_dol_iso_offset + dol_offset2

        data = text.encode("ascii")[:max_len]
        data += b"\x00" * (max_len - len(data))

        with open(iso_path, "r+b") as f:
            f.seek(iso_offset)
            f.write(data)

    def _check_server_version(self, output_data):
        """
        Compares the version provided in the patch manifest against the client's version.

        :param output_data: The manifest's output data which we attempt to acquire the generated version.
        """
        ap_world_version = "<0.5.6"

        if AP_WORLD_VERSION_NAME in output_data:
            ap_world_version = output_data[AP_WORLD_VERSION_NAME]
        if ap_world_version != CLIENT_VERSION:
            raise Utils.VersionException("Error! Server was generated with a different Lost Kingdoms 2 " +
                                         f"APWorld version.\nThe client version is {CLIENT_VERSION}!\nPlease verify you are using the " +
                                         f"same APWorld as the generator, which is '{ap_world_version}'")

def copy_file(source_path, destination_path):
    try:
        # Open source file in read-binary mode
        with open(source_path, 'rb') as src_file:
            # Open destination file in write-binary mode ('wb')
            # 'wb' creates the file if it doesn't exist, and overwrites if it does
            with open(destination_path, 'wb') as dst_file:
                # Read from source and write to destination in chunks (e.g., 4KB buffer)
                while True:
                    chunk = src_file.read(4096)  # Read 4096 bytes
                    if not chunk:
                        break  # End of file
                    dst_file.write(chunk)
        print(f"File copied from '{source_path}' to '{destination_path}' successfully.")
    except FileNotFoundError:
        print(f"Error: Source file '{source_path}' not found.")
    except PermissionError:
        print(f"Error: Permission denied when accessing files.")
    except Exception as e:
        print(f"An error occurred: {e}")



if __name__ == '__main__':
    print("Run this from Launcher.py instead.")
