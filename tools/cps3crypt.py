"""CPS3 encryption mask (exact port of cps3_mask by Andreas Naive, MAME
src/mame/capcom/cps3.cpp).

The custom SH-2 of a CPS3 cart decrypts on the fly, with the key kept in its
battery-backed SRAM:
  - CPU reads from the cart BIOS flash (0x00000000-0x0007FFFF),
  - CPU reads from program SIMMs 1 and 2 (0x06000000-0x06FFFFFF),
  - execution from the SH-2 internal cache (0xC0000000-0xC00003FF).
DMA bypasses the decryption (it reads raw bytes).
When the battery dies the key becomes 0/0 (same as SFIII 2nd Impact): BIOS
and cache still "encrypted" with the key-0 mask, SIMM 1/2 data reads in clear,
SIMM 1/2 instruction fetches decrypted with the key-0 mask.

Game keys (MAME, cps3.cpp):
  redearth 9E300AB1 A175B82C   sfiii  B5FE053E FC03925A   sfiii2 0 0
  jojo     02203EE3 01301972   sfiii3 A55432B4 0C129981   jojoba 23323EE3 03021972
"""
import numpy as np


def _rotl16(v, n):
    return ((v << n) | (v >> (16 - n))) & 0xFFFF


def _rotxor(val, xorval):
    res = (val + _rotl16(val, 2)) & 0xFFFF
    return (_rotl16(res, 4) ^ (res & (val ^ xorval))) & 0xFFFF


def mask_scalar(address, key1, key2):
    """Mask of the 32-bit word at `address` (same as the MAME code, line by line)."""
    address = (address ^ key1) & 0xFFFFFFFF
    val = (address & 0xFFFF) ^ 0xFFFF
    val = _rotxor(val, key2 & 0xFFFF)
    val ^= ((address >> 16) ^ 0xFFFF) & 0xFFFF
    val = _rotxor(val, key2 >> 16)
    val ^= (address & 0xFFFF) ^ (key2 & 0xFFFF)
    return val | (val << 16)


def mask_array(base, nbytes, key1, key2):
    """Masks of the 32-bit words in [base, base+nbytes), vectorised (uint32)."""
    addr = (np.arange(base, base + nbytes, 4, dtype=np.uint64) ^ key1).astype(np.uint32)
    m16 = np.uint32(0xFFFF)

    def rotl(v, n):
        return ((v << np.uint32(n)) | (v >> np.uint32(16 - n))) & m16

    def rotxor(val, x):
        res = (val + rotl(val, 2)) & m16
        return (rotl(res, 4) ^ (res & (val ^ np.uint32(x)))) & m16

    val = (addr & m16) ^ m16
    val = rotxor(val, key2 & 0xFFFF)
    val ^= ((addr >> np.uint32(16)) ^ m16) & m16
    val = rotxor(val, key2 >> 16)
    val ^= (addr & m16) ^ np.uint32(key2 & 0xFFFF)
    return val | (val << np.uint32(16))
