import shutil

from worlds.Files import APPatch, APPlayerContainer, AutoPatchRegister
from settings import get_settings, Settings
from NetUtils import convert_to_base_types
import Utils

from hashlib import md5
from typing import Any
import json, logging, sys, os, zipfile, tempfile
import requests, ssl, certifi, urllib.request

from worlds.LostKingdoms2.LK2Generator import LK2Randomizer

logger = logging.getLogger()
MAIN_PKG_NAME = "worlds.lostkingdoms2.LK2Generator"

RANDOMIZER_NAME = "Lost Kingdoms II"
LK2_USA_MD5 = 0x37d3f930fd53334040f4dfcce94970c8

class InvalidCleanISOError(Exception):
    """
    Exception raised for when user has an issue with their provided Luigi's Mansion ISO.

    Attributes:
        message -- Explanation of the error
    """

    def __init__(self, message="Invalid Clean ISO provided"):
        self.message = message
        super().__init__(self.message)

    def __str__(self):
        return f"InvalidCleanISOError: {self.message}"

class LK2PlayerContainer(APPlayerContainer):
    game = RANDOMIZER_NAME
    compression_method = zipfile.ZIP_DEFLATED
    patch_file_ending = ".aplk2"

    def __init__(self, player_choices: dict, patch_path: str, player_name: str, player: int,
        server: str = ""):
        self.output_data = player_choices
        super().__init__(patch_path, player, player_name, server)

    def write_contents(self, opened_zipfile: zipfile.ZipFile) -> None:
        opened_zipfile.writestr("patch.aplk2", json.dumps(self.output_data, indent=4, default=convert_to_base_types))
        super().write_contents(opened_zipfile)


class LK2USAAPPatch(APPatch, metaclass=AutoPatchRegister):
    game = RANDOMIZER_NAME
    hash = LK2_USA_MD5
    patch_file_ending = ".aplk2"
    result_file_ending = ".iso"

    procedure = ["custom"]

    def __init__(self, *args: Any, **kwargs: Any):
        super(LK2USAAPPatch, self).__init__(*args, **kwargs)

    def __get_archive_name(self) -> str:
        if not (Utils.is_linux or Utils.is_windows):
            message = f"Your OS is not supported with this randomizer {sys.platform}."
            logger.error(message)
            raise RuntimeError(message)

        lib_path = ""
        if Utils.is_windows:
            lib_path = "lib-windows"
        elif Utils.is_linux:
            lib_path = "lib-linux"

        logger.info(f"Dependency archive name to use: {lib_path}")
        return lib_path

    def __get_temp_folder_name(self) -> str:
        from ..LK2Client import CLIENT_VERSION
        temp_path = os.path.join(tempfile.gettempdir(), "lost_kingdoms_2", CLIENT_VERSION, "libs")
        return temp_path

    def patch(self, aplk2_patch: str) -> str:
        # Get the AP Path for the base ROM
        lk2_clean_iso = self.get_base_rom_path()
        logger.info("Provided Lost Kingdoms 2 ISO Path was: " + lk2_clean_iso)

        base_path = os.path.splitext(aplk2_patch)[0]
        output_file = base_path + self.result_file_ending

        try:
            # Verify we have a clean rom of the game first
            self.verify_base_rom(lk2_clean_iso, throw_on_missing_speedups=True)

            # Use our randomize function to patch the file into an ISO.
            from ..LK2Generator import LK2Randomizer
            with zipfile.ZipFile(aplk2_patch, "r") as zf:
               aplk2_bytes = zf.read("patch.aplk2")
            LK2Randomizer(lk2_clean_iso, output_file, aplk2_bytes)
        except ImportError:
            logger.error(ImportError)
        return output_file

    def read_contents(self, aplk2_patch: str) -> dict[str, Any]:
        with zipfile.ZipFile(aplk2_patch, "r") as zf:
            with zf.open("archipelago.json", "r") as f:
                manifest = json.load(f)
        if manifest["compatible_version"] > self.version:
            raise Exception(f"File (version: {manifest['compatible_version']}) too new "
                            f"for this handler (version: {self.version})")
        return manifest

    @classmethod
    def get_base_rom_path(cls) -> str:
        options: Settings = get_settings()
        file_name = options["lostkingdoms2_options"]["iso_file"]
        if not os.path.exists(file_name):
            file_name = Utils.user_path(file_name)
        return file_name

    @classmethod
    def verify_base_rom(cls, lk2_rom_path: str, throw_on_missing_speedups: bool = False):
        # Verifies we have a valid installation of Lost Kingdoms 2 USA. There are some regional file differences.
        logger.info("Verifying if the provided ISO is a valid copy of Lost Kingdoms 2 USA edition.")
        logger.info("Checking GCLib and speedup libs.")

        base_md5 = md5()
        with open(lk2_rom_path, "rb") as f:
            while chunk := f.read(1024 * 1024):  # Read the file in chunks.
                base_md5.update(chunk)

        # Verify that the file has the right has first, as the wrong file could have been loaded.
        md5_conv = int(base_md5.hexdigest(), 16)
        if md5_conv != LK2_USA_MD5:
            raise InvalidCleanISOError(f"Invalid vanilla {RANDOMIZER_NAME} ISO.\nYour ISO may be corrupted or your " +
                f"MD5 hashes do not match.\nCorrect ISO MD5 hash: {LK2_USA_MD5:x}\nYour ISO's MD5 hash: {md5_conv}")

    def create_iso(self, temp_dir_path: str, patch_file_path: str, output_iso_path: str, vanilla_iso_path: str):
        logger.info(f"Appending the following to sys path to get dependencies correctly: {temp_dir_path}")
        sys.path.insert(0, temp_dir_path)

        # Verify we have a clean rom of the game first
        self.verify_base_rom(vanilla_iso_path)

        # Use our randomize function to patch the file into an ISO.
        with zipfile.ZipFile(patch_file_path, "r") as zf:
            aplk2_bytes = zf.read("patch.aplk2")
        LK2Randomizer(vanilla_iso_path, output_iso_path, aplk2_bytes)

