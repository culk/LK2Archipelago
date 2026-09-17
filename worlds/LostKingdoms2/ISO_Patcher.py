import json
import logging
import os
import struct
import zipfile

logger = logging.getLogger()


class BranchRangeError(Exception):
    pass


def copy_file(source_path, destination_path):
    # Manual chunked copy instead of shutil.copyfile() - shutil doesn't work
    # reliably in Archipelago's bundled/frozen runtime environment, per
    # earlier debugging on this project. Ported directly from the original
    # LK2Generator.py's copy_file().
    try:
        with open(source_path, 'rb') as src_file:
            with open(destination_path, 'wb') as dst_file:
                while True:
                    chunk = src_file.read(4096)
                    if not chunk:
                        break
                    dst_file.write(chunk)
        logger.info(f"File copied from '{source_path}' to '{destination_path}' successfully.")
    except FileNotFoundError:
        logger.error(f"Error: Source file '{source_path}' not found.")
        raise
    except PermissionError:
        logger.error(f"Error: Permission denied when accessing files.")
        raise
    except Exception as e:
        logger.error(f"An error occurred copying '{source_path}' to '{destination_path}': {e}")
        raise


class ISOPatcher:
    # --- Code cave configuration ---
    # Lives inside gTRKInterruptVectorTable (0x800033FC-0x80005330), a
    # MetroTRK debugger-support structure that's mostly unpopulated in a
    # retail build - part of the DOL's existing text[0] section, so it's
    # loaded reliably by every boot path (including Dolphin's fast/HLE boot,
    # which does NOT load newly-registered DOL sections - confirmed after
    # several failed attempts at that approach). No DOL header changes are
    # needed since nothing new is being registered.
    CAVE_RAM_ADDR = 0x800033FC  # gTRKInterruptVectorTable's own true start
    CAVE_SIZE = 0x1F34  # 7988 bytes - the table's full size
    # (0x800033FC-0x80005330). Standard default as of this revision:
    # confirmed via an in-game boot test that the back portion
    # (0x80004B30 onward, the original 1200-byte cave's own start) boots
    # and plays completely normally when overwritten, despite containing
    # non-zero, genuine MetroTRK debug-structure data - this data is boot-
    # time-populated but never read by any code path during normal
    # retail gameplay (confirmed via an exhaustive symbol/address search
    # of the decompiled source finding zero references anywhere in this
    # entire range). The earlier portion (0x800033FC-0x80004B30) hasn't
    # been separately boot-tested, but is the same kind of structure and
    # accepted as equally safe going forward per explicit user decision.

    def __init__(self, iso_path: str):
        self.iso_path = iso_path
        self.file = open(iso_path, 'r+b')
        self._read_headers()

        self.cave_ram_start = None
        self.cave_ram_end = None
        self.cave_cursor = None

        self.disc_data_cursor = None

        self._tick_table_addr = None
        self._tick_next_slot = 0

    # ------------------------------------------------------------------
    # Header parsing - read straight from the ISO, never hardcoded
    # ------------------------------------------------------------------
    def _read_u32(self, iso_off: int) -> int:
        self.file.seek(iso_off)
        return struct.unpack('>I', self.file.read(4))[0]

    def _write_u32(self, iso_off: int, value: int):
        self.file.seek(iso_off)
        self.file.write(struct.pack('>I', value & 0xFFFFFFFF))

    def _read_headers(self):
        # Disc boot header
        self.dol_offset = self._read_u32(0x420)
        self.fst_offset = self._read_u32(0x424)
        self.fst_size = self._read_u32(0x428)

        # DOL header (7 text sections, 11 data sections)
        d = self.dol_offset
        self.text_offsets = [self._read_u32(d + 0x00 + i * 4) for i in range(7)]
        self.data_offsets = [self._read_u32(d + 0x1C + i * 4) for i in range(11)]
        self.text_addrs = [self._read_u32(d + 0x48 + i * 4) for i in range(7)]
        self.data_addrs = [self._read_u32(d + 0x64 + i * 4) for i in range(11)]
        self.text_sizes = [self._read_u32(d + 0x90 + i * 4) for i in range(7)]
        self.data_sizes = [self._read_u32(d + 0xAC + i * 4) for i in range(11)]
        self.bss_addr = self._read_u32(d + 0xD8)
        self.bss_size = self._read_u32(d + 0xDC)

    def _section_table(self):
        """(ram_start, ram_end, iso_start) for every currently-registered section."""
        table = []
        for i in range(7):
            if self.text_sizes[i]:
                table.append((self.text_addrs[i], self.text_addrs[i] + self.text_sizes[i],
                               self.dol_offset + self.text_offsets[i]))
        for i in range(11):
            if self.data_sizes[i]:
                table.append((self.data_addrs[i], self.data_addrs[i] + self.data_sizes[i],
                               self.dol_offset + self.data_offsets[i]))
        return table

    # ------------------------------------------------------------------
    # RAM <-> ISO offset conversion
    # ------------------------------------------------------------------
    def ram_to_iso(self, ram_addr: int) -> int:
        for ram_start, ram_end, iso_start in self._section_table():
            if ram_start <= ram_addr < ram_end:
                return iso_start + (ram_addr - ram_start)
        raise ValueError(
            f"RAM address {hex(ram_addr)} is not mapped in any registered DOL section. "
            f"(Did you forget to call register_cave() before patching a cave address?)"
        )

    # ------------------------------------------------------------------
    # Generic write primitives
    # ------------------------------------------------------------------
    def patch_word(self, ram_addr: int, value: int):
        off = self.ram_to_iso(ram_addr)
        self._write_u32(off, value)

    def patch_bytes(self, ram_addr: int, data: bytes):
        off = self.ram_to_iso(ram_addr)
        self.file.seek(off)
        self.file.write(data)

    # The card database ("RUNE.PDM") lives in a separate resource file loaded
    # at a fixed RAM address that falls OUTSIDE any of the DOL's own declared
    # text/data sections - ram_to_iso() has no way to resolve it. The original
    # LK2Generator.py's patch_iso_from_ram() worked around this with a
    # hardcoded ISO-offset shortcut for this specific address range, which
    # (per direct confirmation) is already correct and tested - preserved
    # here verbatim rather than re-derived, since there's no DOL-header-based
    # way to compute it the way we do for everything else.
    _RUNE_PDM_RAM_START = 0x80732BE0
    _RUNE_PDM_RAM_END = 0x807F9940
    _RUNE_PDM_ISO_OFFSET = 0x1D000 + 0x6835B40

    def patch_value(self, ram_addr: int, value: int, byte_size: int = 4):
        """
        Writes an arbitrary-size big-endian integer at a RAM address -
        matches the byte_size semantics of the original patch_iso_from_ram()
        (e.g. 2 bytes for card IDs, 1 byte for mana costs). Handles both
        normal DOL-section addresses (via ram_to_iso) and the RUNE.PDM
        card-database region described above.
        """
        data = value.to_bytes(byte_size, byteorder="big")
        if self._RUNE_PDM_RAM_START <= ram_addr < self._RUNE_PDM_RAM_END:
            iso_offset = self._RUNE_PDM_ISO_OFFSET + (ram_addr - self._RUNE_PDM_RAM_START)
            self.file.seek(iso_offset)
            self.file.write(data)
        else:
            self.patch_bytes(ram_addr, data)

    def write_code(self, ram_addr: int, instructions):
        """instructions: list of 32-bit ints (already-assembled PPC words)."""
        data = b''.join(struct.pack('>I', instr & 0xFFFFFFFF) for instr in instructions)
        self.patch_bytes(ram_addr, data)

    # ------------------------------------------------------------------
    # Branch helpers
    # ------------------------------------------------------------------
    @staticmethod
    def make_bl(from_addr: int, to_addr: int) -> int:
        offset = to_addr - from_addr
        if not (-0x2000000 <= offset <= 0x1FFFFFC):
            raise BranchRangeError(
                f"bl from {hex(from_addr)} to {hex(to_addr)} is out of range "
                f"({hex(offset)}, must fit in +/-32MB)"
            )
        return 0x48000001 | (offset & 0x3FFFFFC)

    @staticmethod
    def make_b(from_addr: int, to_addr: int) -> int:
        offset = to_addr - from_addr
        if not (-0x2000000 <= offset <= 0x1FFFFFC):
            raise BranchRangeError(
                f"b from {hex(from_addr)} to {hex(to_addr)} is out of range "
                f"({hex(offset)}, must fit in +/-32MB)"
            )
        return 0x48000000 | (offset & 0x3FFFFFC)

    def write_branch(self, from_addr: int, to_addr: int, link: bool = False):
        instr = self.make_bl(from_addr, to_addr) if link else self.make_b(from_addr, to_addr)
        self.patch_word(from_addr, instr)

    # ------------------------------------------------------------------
    # Code cave management
    # ------------------------------------------------------------------
    def register_cave(self, ram_addr: int = None, size: int = None):
        """
        Points the cave bookkeeping at CAVE_RAM_ADDR/CAVE_SIZE - the full
        gTRKInterruptVectorTable, part of the DOL's existing text[0]
        section. Nothing is written to the DOL header since no new
        section is added.

        Logs a warning (not a hard failure) if the target range isn't
        genuinely all zeros in the clean ISO, as a heads-up against a
        differing game revision/region. This is a warning rather than a
        blocking error because the table is known, confirmed-safe to
        overwrite even where non-zero (boot-tested): it holds genuine,
        boot-time-populated MetroTRK debug-structure data that's never
        read by any code path during normal retail gameplay.
        """
        ram_addr = self.CAVE_RAM_ADDR if ram_addr is None else ram_addr
        size = self.CAVE_SIZE if size is None else size

        iso_off = self.ram_to_iso(ram_addr)
        self.file.seek(iso_off)
        existing = self.file.read(size)
        if existing != b'\x00' * size:
            first_bad = next(i for i, b in enumerate(existing) if b != 0)
            logger.warning(
                f"Cave region {hex(ram_addr)}-{hex(ram_addr + size)} is not all zeros "
                f"(first non-zero byte at offset {hex(first_bad)}, value {existing[first_bad]:#04x}). "
                f"This is expected for gTRKInterruptVectorTable (genuine, boot-time-populated debug "
                f"data, confirmed safe to overwrite) - only worth double-checking if this ISO is a "
                f"different revision/region than previously verified."
            )

        self.cave_ram_start = ram_addr
        self.cave_ram_end = ram_addr + size
        self.cave_cursor = ram_addr

        logger.info(f"Using existing cave: RAM {hex(ram_addr)}-{hex(ram_addr + size)} "
              f"(inside gTRKInterruptVectorTable, no new DOL section)")

    def alloc_cave(self, size: int) -> int:
        """Simple bump allocator within the registered cave. Returns a RAM address."""
        if self.cave_cursor is None:
            raise RuntimeError("Cave not registered yet - call register_cave() first.")
        size = (size + 3) & ~3  # round up to word alignment
        addr = self.cave_cursor
        if addr + size > self.cave_ram_end:
            used = self.cave_cursor - self.cave_ram_start
            total = self.cave_ram_end - self.cave_ram_start
            remaining = self.cave_ram_end - self.cave_cursor
            over_by = (addr + size) - self.cave_ram_end
            raise RuntimeError(
                f"Code cave exhausted: requested {size} bytes but only {remaining} bytes "
                f"remain ({used}/{total} bytes already used, over by {over_by} bytes). "
                f"The cave lives inside gTRKInterruptVectorTable (a fixed, already-mapped "
                f"gap) - it can't just be made bigger."
            )
        self.cave_cursor += size
        return addr

    def cave_bytes_used(self) -> int:
        return 0 if self.cave_cursor is None else self.cave_cursor - self.cave_ram_start

    # ------------------------------------------------------------------
    # Disc-backed data storage
    #
    # The code cave is only ~8KB and every mechanic competes for it, but
    # most of what fills it is not code - it is static lookup tables. Those
    # do not need to be resident: a mechanic can park them on the disc and
    # DVD-read the bytes into a heap buffer when it needs them, then free
    # it. That costs one read per level load and no cave at all.
    #
    # The region used is the mastering padding past the end of the disc's
    # own filesystem. On a retail Lost Kingdoms II image the FST's 1876
    # files all end by 0x3E7CADEB, leaving 392MB that no FST entry covers.
    # The game cannot reach it: every file it opens goes through
    # DVDConvertPathToEntrynum/DVDFastOpen against the FST, and the DVD
    # streaming API (the one way to read raw offsets outside the FST) is
    # linked but never called anywhere in main.dol.
    #
    # Reads are still bounds-checked by the game's own DVDReadAsync, which
    # validates against the length field of the DVDFileInfo the caller
    # supplies - so a mechanic that gets its own arithmetic wrong reads
    # short rather than wandering off into other data.
    # ------------------------------------------------------------------
    DISC_DATA_START = 0x3E7CB000     # first sector past the last real file
    DISC_DATA_SIZE = 0x100000        # 1MB reserved; the padding is 392MB
    DISC_SECTOR = 0x800

    def alloc_disc_data(self, size: int) -> int:
        """Reserve space in the disc padding. Returns an ISO FILE OFFSET, not
        a RAM address - nothing is mapped into memory until a mechanic reads
        it. Allocations are sector-aligned because DVD reads have to be."""
        if self.disc_data_cursor is None:
            self._verify_disc_data_region()
            self.disc_data_cursor = self.DISC_DATA_START

        size = (size + self.DISC_SECTOR - 1) & ~(self.DISC_SECTOR - 1)
        offset = self.disc_data_cursor
        if offset + size > self.DISC_DATA_START + self.DISC_DATA_SIZE:
            used = self.disc_data_cursor - self.DISC_DATA_START
            raise RuntimeError(
                f"Disc data region exhausted: requested {size} bytes but only "
                f"{self.DISC_DATA_START + self.DISC_DATA_SIZE - offset} remain "
                f"({used}/{self.DISC_DATA_SIZE} used). Unlike the code cave this "
                f"CAN be made bigger - raise DISC_DATA_SIZE; there is 392MB of "
                f"padding and only the first 1MB is reserved."
            )
        self.disc_data_cursor += size
        return offset

    def _verify_disc_data_region(self):
        """Refuse to use the region unless this really is an image whose own
        filesystem ends before it. Checked against the ISO's own FST rather
        than assumed, so a differently-mastered or trimmed image fails loudly
        instead of silently overwriting real files."""
        fst_offset = self._read_u32(0x424)
        fst_size = self._read_u32(0x428)
        self.file.seek(fst_offset)
        fst = self.file.read(fst_size)
        entry_count = struct.unpack_from(">I", fst, 8)[0]
        if entry_count == 0 or entry_count * 12 > len(fst):
            raise RuntimeError(f"FST looks invalid (entry count {entry_count})")

        end_of_files = fst_offset + fst_size
        for i in range(entry_count):
            base = i * 12
            if fst[base] & 1:
                continue  # directory
            off = struct.unpack_from(">I", fst, base + 4)[0]
            length = struct.unpack_from(">I", fst, base + 8)[0]
            end_of_files = max(end_of_files, off + length)

        if end_of_files > self.DISC_DATA_START:
            raise RuntimeError(
                f"This ISO's own files run to {hex(end_of_files)}, past the disc "
                f"data region at {hex(self.DISC_DATA_START)}. Writing there would "
                f"corrupt real game files - aborting."
            )

        self.file.seek(0, 2)
        if self.file.tell() < self.DISC_DATA_START + self.DISC_DATA_SIZE:
            raise RuntimeError(
                f"This ISO is only {self.file.tell():,} bytes - too short to hold "
                f"the disc data region ending at "
                f"{hex(self.DISC_DATA_START + self.DISC_DATA_SIZE)}. It is probably "
                f"a trimmed rip; a full-size image is required."
            )

    def write_disc_data(self, iso_offset: int, data: bytes):
        """Write bytes straight to an ISO offset from alloc_disc_data(). Not
        patch_bytes(), which takes a RAM address and resolves it through the
        DOL section table - this region is not in the DOL at all."""
        if self.disc_data_cursor is None or not (
            self.DISC_DATA_START <= iso_offset < self.disc_data_cursor
        ):
            raise ValueError(
                f"{hex(iso_offset)} is not inside an allocated disc data range"
            )
        self.file.seek(iso_offset)
        self.file.write(data)

    def disc_data_bytes_used(self) -> int:
        return 0 if self.disc_data_cursor is None else self.disc_data_cursor - self.DISC_DATA_START

    # ------------------------------------------------------------------
    # Per-tick dispatcher
    #
    # Hooks PollControllerState (0x80005ba4), which is called every game
    # tick from all major loop contexts (world map, in-level, VS mode,
    # loading screens) at the same relative position each time - runs many
    # times a second regardless of context, not tied to rendering.
    #
    # Hooked AFTER the original LR has already been saved to the stack
    # (0x80005bac: stw r0,4(r1)) rather than at the function's very first
    # instruction - our own "bl" into the dispatcher clobbers LR, which
    # would lose PollControllerState's real caller address if hooked any
    # earlier. PollControllerState's own epilogue restores its LR from the
    # stack independently of anything the dispatcher does, so this is safe
    # regardless of how many internal return paths the function has.
    #
    # IMPORTANT: the two replaced instructions (addi r5,r3,-8736 and
    # lis r4,0x8017) are NOT throwaway setup - they begin computing
    # padStateBase (&DAT_80170b00) and a related pointer that
    # PollControllerState's own later code (eventually reaching
    # DecodePadButtonState) depends on still being valid in r4/r5. Since
    # r3-r5 are otherwise volatile and freely used as scratch by the
    # dispatcher and every registered mechanic stub, they're explicitly
    # saved right after re-executing the replaced instructions and
    # restored immediately before returning - confirmed necessary by an
    # actual crash (invalid read inside DecodePadButtonState, traced via
    # SRR0) before this fix was added.
    #
    # Multiple mechanics can each call register_tick_mechanic() with their
    # own small "check and act" stub - the dispatcher calls every
    # registered stub in sequence, once per tick. Each stub must be a plain
    # void-void function (no args, no return value) that follows standard
    # calling convention (save/restore any non-volatile registers it uses).
    #
    # The dispatcher itself never assumes any register is safe to use as
    # scratch, even ones that are technically volatile per the PPC ABI -
    # r3-r12 are unconditionally saved before any of the dispatcher's own
    # work and restored immediately before returning. This was added after
    # a real crash: the two replaced instructions set up r4/r5 for
    # PollControllerState's own later use (not disposable scratch as the
    # ABI would normally allow assuming), and saving only r3-r5 still left
    # a second crash (__prep_buffer) from another register dependency -
    # rather than keep chasing individual registers one at a time, every
    # volatile GPR is now saved/restored unconditionally.
    #
    # Hooks the "bl MatrixMultiply" call site at 0x80091274, inside
    # ComputeParticleRotationMatrixAlt - runs every frame regardless of
    # context (world map, in-level, etc.), and unlike PollControllerState
    # this call site has no known live register dependencies extending
    # past it (MatrixMultiply's own return value, if used at all, is
    # fully covered by the same save/restore-everything discipline below).
    #
    # The dispatcher never assumes any register is safe to use as scratch,
    # even ones that are technically volatile per the PPC ABI - r3-r12 are
    # unconditionally saved before any of the dispatcher's own work and
    # restored immediately before returning. This was hard-won: an earlier
    # hook location (inside PollControllerState) produced two separate
    # crashes from register dependencies that were difficult to fully
    # enumerate statically, even after fixing the first one found.
    #
    # Since "bl MatrixMultiply" is PC-relative, it can't just be copied
    # verbatim into the dispatcher - it's re-encoded via make_bl() at
    # whatever position it ends up in the dispatcher's own instruction
    # stream, once dispatcher_addr is known.
    # ------------------------------------------------------------------
    _TICK_HOOK_ADDR = 0x80091274
    _TICK_HOOK_CALL_TARGET = 0x800f7f04  # MatrixMultiply
    _TICK_TABLE_SIZE = 16  # max registered per-tick mechanics

    def _ensure_tick_dispatcher_installed(self):
        if self._tick_table_addr is not None:
            return self._tick_table_addr

        table_addr = self.alloc_cave(self._TICK_TABLE_SIZE * 4)
        for i in range(self._TICK_TABLE_SIZE):
            self.patch_word(table_addr + i * 4, 0)  # empty slot marker

        dispatcher_addr = self.alloc_cave(64 * 4)
        hi = (table_addr >> 16) & 0xFFFF
        lo = table_addr & 0xFFFF

        def lis(rD, imm16): return 0x3C000000 | (rD << 21) | (imm16 & 0xFFFF)
        def ori(rA, rS, imm16): return 0x60000000 | (rS << 21) | (rA << 16) | (imm16 & 0xFFFF)
        def lwz(rD, offset, rA): return 0x80000000 | (rD << 21) | (rA << 16) | (offset & 0xFFFF)
        def stw(rS, offset, rA): return 0x90000000 | (rS << 21) | (rA << 16) | (offset & 0xFFFF)
        def stwu(rS, offset, rA): return 0x94000000 | (rS << 21) | (rA << 16) | (offset & 0xFFFF)
        def addi(rD, rA, simm): return 0x38000000 | (rD << 21) | (rA << 16) | (simm & 0xFFFF)
        def li(rD, simm): return addi(rD, 0, simm)
        def mflr(rD): return 0x7C0802A6 | (rD << 21)
        def mtlr(rS): return 0x7C0803A6 | (rS << 21)
        def mfctr(rD): return 0x7C0902A6 | (rD << 21)
        def mtctr(rS): return 0x7C0903A6 | (rS << 21)
        def mfxer(rD): return 0x7C0102A6 | (rD << 21)
        def mtxer(rS): return 0x7C0103A6 | (rS << 21)
        def mfcr(rD): return 0x7C000026 | (rD << 21)
        def mtcr(rS): return 0x7C0FF120 | (rS << 21)  # mtcrf 0xFF (all fields)
        def bctrl(): return 0x4E800421
        def cmpwi(rA, simm): return 0x2C000000 | (rA << 16) | (simm & 0xFFFF)
        def beq(from_addr, to_addr): return 0x41820000 | ((to_addr - from_addr) & 0xFFFC)
        def b(from_addr, to_addr): return 0x48000000 | ((to_addr - from_addr) & 0x3FFFFFC)

        FRAME_SIZE = 96
        # r3-r12 saved at offsets 8-44, r30/r31 at 48/52, special regs at 56-64
        VOLATILE_REGS = list(range(3, 13))  # r3..r12
        SAVE_BASE = 8
        R0_ORIG_OFF = 4    # r0's true original value (before we use r0 as scratch below)
        R30_OFF = SAVE_BASE + len(VOLATILE_REGS) * 4       # 48
        R31_OFF = R30_OFF + 4                                # 52
        CTR_OFF = R31_OFF + 4                                # 56
        XER_OFF = CTR_OFF + 4                                # 60
        CR_OFF = XER_OFF + 4                                 # 64
        LR_OFF = FRAME_SIZE + 4                              # 100

        def save_all(instrs):
            for i, reg in enumerate(VOLATILE_REGS):
                instrs.append(stw(reg, SAVE_BASE + i * 4, 1))

        def restore_all(instrs):
            for i, reg in enumerate(VOLATILE_REGS):
                instrs.append(lwz(reg, SAVE_BASE + i * 4, 1))

        REEXEC_CALL_IDX = 4  # index of the re-executed "bl MatrixMultiply" below

        instructions = [
            stwu(1, -FRAME_SIZE, 1),                      # 0
            stw(0, R0_ORIG_OFF, 1),                        # 1  save r0's true original value first
            mflr(0),                                      # 2
            stw(0, LR_OFF, 1),                             # 3
            None,                                          # 4  bl MatrixMultiply (filled below)
        ]
        # Save every volatile GPR (r3-r12) immediately after re-executing
        # the replaced call, before touching any of them ourselves.
        save_all(instructions)
        instructions += [
            stw(30, R30_OFF, 1),
            stw(31, R31_OFF, 1),
            # Special-purpose registers - never assumed safe as scratch,
            # even though only CTR is known to actually matter here (used
            # by mtctr/bctrl below to call each registered mechanic
            # indirectly - if anything up the call chain relies on CTR for
            # its own loop counting, clobbering it without restoring would
            # corrupt that loop). XER/CR saved too for the same reason.
            mfctr(0), stw(0, CTR_OFF, 1),
            mfxer(0), stw(0, XER_OFF, 1),
            mfcr(0), stw(0, CR_OFF, 1),
            lis(31, hi),                # r31 = table base
            ori(31, 31, lo),
            li(30, self._TICK_TABLE_SIZE),  # r30 = remaining slot count
        ]

        loop_idx = len(instructions)
        instructions += [
            cmpwi(30, 0),
            None,   # beq done (filled below)
            lwz(12, 0, 31),
            cmpwi(12, 0),
            None,   # beq skip (filled below)
            mtctr(12),
            bctrl(),
        ]
        skip_idx = len(instructions)
        instructions += [
            addi(31, 31, 4),
            addi(30, 30, -1),
            None,   # b loop (filled below)
        ]
        done_idx = len(instructions)
        instructions += [
            lwz(30, R30_OFF, 1),
            lwz(31, R31_OFF, 1),
            lwz(0, CR_OFF, 1), mtcr(0),
            lwz(0, XER_OFF, 1), mtxer(0),
            lwz(0, CTR_OFF, 1), mtctr(0),
        ]
        # Restore every volatile GPR before returning - regardless of what
        # any registered mechanic stub did internally.
        restore_all(instructions)
        instructions += [
            lwz(0, LR_OFF, 1),
            mtlr(0),
            lwz(0, R0_ORIG_OFF, 1),   # restore r0's true original value last
            addi(1, 1, FRAME_SIZE),
            0x4E800020,  # blr
        ]

        instructions[loop_idx + 1] = beq(dispatcher_addr + (loop_idx + 1) * 4,
                                          dispatcher_addr + done_idx * 4)
        instructions[loop_idx + 4] = beq(dispatcher_addr + (loop_idx + 4) * 4,
                                          dispatcher_addr + skip_idx * 4)
        instructions[skip_idx + 2] = b(dispatcher_addr + (skip_idx + 2) * 4,
                                        dispatcher_addr + loop_idx * 4)

        # Re-executed "bl MatrixMultiply" - PC-relative, so it must be
        # re-encoded here rather than copied verbatim from the original.
        instructions[REEXEC_CALL_IDX] = self.make_bl(
            dispatcher_addr + REEXEC_CALL_IDX * 4, self._TICK_HOOK_CALL_TARGET)

        self.write_code(dispatcher_addr, instructions)
        self.patch_word(self._TICK_HOOK_ADDR, self.make_bl(self._TICK_HOOK_ADDR, dispatcher_addr))

        self._tick_table_addr = table_addr
        self._tick_next_slot = 0
        return table_addr

    def register_tick_mechanic(self, stub_addr: int):
        """Register a per-tick mechanic's stub address into the next free
        table slot, installing the dispatcher hook itself on first use."""
        self._ensure_tick_dispatcher_installed()
        slot = self._tick_next_slot
        if slot >= self._TICK_TABLE_SIZE:
            raise ValueError("Per-tick mechanic table is full")
        self.patch_word(self._tick_table_addr + slot * 4, stub_addr)
        self._tick_next_slot = slot + 1

    # ------------------------------------------------------------------
    def close(self):
        self.file.close()


def patch(clean_iso_path: str, output_iso_path: str, aplk2_patch_path: str):
    """
    Archipelago-facing entry point.

        patch(clean_iso_path, output_iso_path, aplk2_patch_path)

    aplk2_patch_path is the path to the .aplk2 zip archive itself (see
    LK2PlayerContainer.write_contents in lk2_rom.py for what's inside it) -
    this function opens it and reads "patch.aplk2" (JSON settings) and
    "AP_Cardback.gtx" internally, so the caller just passes the path.
    """
    try:
        logger.info(f"patch() starting: clean_iso={clean_iso_path} output={output_iso_path} "
                    f"aplk2={aplk2_patch_path}")

        with zipfile.ZipFile(aplk2_patch_path, "r") as zf:
            aplk2_bytes = zf.read("patch.aplk2")
            cardback_gtx = zf.read("AP_Cardback.gtx")

        # aplk2_bytes is the raw contents of "patch.aplk2" inside the archive
        # (json.dumps(self.output_data, ...) on the generation side) - so this
        # is just the JSON-encoded randomizer settings/output data, same shape
        # as the old lk2_gen.output_data dict (e.g. output_data["Name"]).
        output_data = json.loads(aplk2_bytes)

        logger.info(f"Copying clean ISO to {output_iso_path} ...")
        copy_file(clean_iso_path, output_iso_path)
        logger.info("Copy complete.")

        if not os.path.exists(output_iso_path):
            # copy_file() re-raises on failure now, so this should be
            # unreachable, but this is cheap insurance in case some future
            # change reintroduces a silent failure path.
            raise RuntimeError(
                f"copy_file() returned without error, but '{output_iso_path}' does not exist. "
                f"This should not be possible - please report this."
            )

        patcher = ISOPatcher(output_iso_path)
        logger.info(f"DOL offset: {hex(patcher.dol_offset)}")

        patcher.register_cave()

        _apply_mechanics(patcher, output_data, cardback_gtx)

        patcher.close()
        logger.info("Done.")
    except Exception:
        # Log at ERROR (with full traceback) rather than INFO/DEBUG so this
        # is actually visible regardless of how the caller's logging is
        # configured, then re-raise so the failure still propagates normally.
        # This now wraps the ENTIRE function body - the zip read, JSON parse,
        # and copy step included - not just the ISOPatcher/mechanics part,
        # so nothing can fail silently before reaching here.
        logger.exception(f"patch() failed while producing '{output_iso_path}'")
        raise


# Mode values live in stats_database so the mechanics and this file cannot
# disagree about what an option value means.
from .Patch_Mechanics.stats_database import MODE_OFF, MODE_RANDOMIZE


def _apply_stat_randomizer(patcher, output_data, module,
                           mode_key, min_key, max_key, mult_key):
    """Run one of the four card stat randomizers, if its option is on.

    Kept in one place because all four take the same six arguments in the
    same order, and a mistake in any single call site is invisible until it
    corrupts card data.
    """
    mode = output_data.get(mode_key, MODE_OFF)
    # 100 means 1.0 - the options carry integers to stay yaml-friendly.
    multiplier = output_data.get(mult_key, 100) / 100.0

    # Note this is NOT "return unless randomizing". A multiplier applies to
    # the vanilla values even with the mode off, so a player can scale a
    # stat without shuffling or rerolling it. Only the case where nothing at
    # all would change is skipped.
    if mode == MODE_OFF and multiplier == 1:
        return

    minimum = output_data.get(min_key, 0)
    maximum = output_data.get(max_key, 0)
    # Only meaningful when rolling new values; shuffle redeals what the game
    # already had, and mode off does not generate values at all.
    if mode == MODE_RANDOMIZE and minimum > maximum:
        raise ValueError(
            f"{min_key} ({minimum}) is greater than {max_key} ({maximum})"
        )

    module.apply(
        patcher,
        output_data,
        minimum,
        maximum,
        mode,
        multiplier,
    )


def _apply_mechanics(patcher: ISOPatcher, output_data: dict, cardback_gtx: bytes):
    from .Patch_Mechanics import mechanic_player_name
    mechanic_player_name.apply(patcher, output_data)

    from .Patch_Mechanics import mechanic_code_modifications
    mechanic_code_modifications.apply(patcher)

    from .Patch_Mechanics import mechanic_ap_key_item_opcode
    mechanic_ap_key_item_opcode.apply(patcher)

    #from .Patch_Mechanics import mechanic_debug_memory_monitor
    #mechanic_debug_memory_monitor.apply(patcher)

    if output_data.get("fairysanity", 0):
        from .Patch_Mechanics import mechanic_fairysanity
        mechanic_fairysanity.apply(patcher)

    if output_data.get("progressive_leveling", 0):
        from .Patch_Mechanics import mechanic_progressive_leveling
        mechanic_progressive_leveling.apply(patcher)

    if output_data.get("progressive_attribute_proficiencies", 0):
        from .Patch_Mechanics import mechanic_progressive_attributes
        mechanic_progressive_attributes.apply(patcher)

    if output_data.get("randomize_enemies", 0):
        from .Patch_Mechanics import mechanic_randomize_monsters
        mechanic_randomize_monsters.apply(patcher, output_data)

    if output_data.get("randomize_levels", 0) and not output_data.get("level_unlocks_as_items", 0):
        from .Patch_Mechanics import mechanic_randomize_level_unlocks
        mechanic_randomize_level_unlocks.apply(patcher, output_data)

    if output_data.get("level_unlocks_as_items", 0):
        from .Patch_Mechanics import mechanic_disable_level_unlocks
        mechanic_disable_level_unlocks.apply(patcher, output_data)

    from .Patch_Mechanics import mechanic_disable_vanilla_chests
    mechanic_disable_vanilla_chests.apply(patcher)

    from .Patch_Mechanics import mechanic_choose_character_model
    mechanic_choose_character_model.apply(patcher, output_data)

    from .Patch_Mechanics import mechanic_cardback_texture
    mechanic_cardback_texture.apply(patcher, cardback_gtx)

    from .Patch_Mechanics import mechanic_randomize_magic_stone_costs
    _apply_stat_randomizer(
        patcher, output_data, mechanic_randomize_magic_stone_costs,
        "randomize_magic_stone_costs", "randomize_magic_stone_costs_min",
        "randomize_magic_stone_costs_max", "magic_stone_costs_multiplier")

    from .Patch_Mechanics import mechanic_randomize_card_prices
    _apply_stat_randomizer(
        patcher, output_data, mechanic_randomize_card_prices,
        "randomize_card_prices", "randomize_card_prices_min",
        "randomize_card_prices_max", "card_prices_multiplier")

    from .Patch_Mechanics import mechanic_randomize_copy_costs
    _apply_stat_randomizer(
        patcher, output_data, mechanic_randomize_copy_costs,
        "randomize_copy_xp_costs", "randomize_copy_xp_costs_min",
        "randomize_copy_xp_costs_max", "copy_xp_cost_multiplier")

    from .Patch_Mechanics import mechanic_randomize_upgrade_costs
    _apply_stat_randomizer(
        patcher, output_data, mechanic_randomize_upgrade_costs,
        "randomize_upgrade_xp_costs", "randomize_upgrade_xp_costs_min",
        "randomize_upgrade_xp_costs_max", "upgrade_xp_cost_multiplier")

    if output_data.get("randomize_starting_deck", 0):
        from .Patch_Mechanics import mechanic_randomize_starting_deck
        mechanic_randomize_starting_deck.apply(patcher, output_data)

    if output_data.get("randomize_shop_contents", 0):
        from .Patch_Mechanics import mechanic_randomize_shop_contents
        mechanic_randomize_shop_contents.apply(patcher, output_data)

    if output_data.get("shopsanity",0):
        from .Patch_Mechanics import mechanic_shopsanity
        mechanic_shopsanity.apply(patcher)

    if output_data.get("randomize_bonus_draws", 0):
        from .Patch_Mechanics import mechanic_randomize_bonus_draws
        mechanic_randomize_bonus_draws.apply(patcher, output_data)

    if output_data.get("randomize_level_music", 0):
        from .Patch_Mechanics import mechanic_randomize_music
        mechanic_randomize_music.apply(patcher, output_data)

    from .Patch_Mechanics import mechanic_world_map_variations
    mechanic_world_map_variations.apply(patcher, output_data)
