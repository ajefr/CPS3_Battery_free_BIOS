#!/usr/bin/env python3
"""Builds the battery-free CPS3 BIOS from YOUR dump of the sfiii3_euro BIOS.

The BIOS recognises the inserted CD (or the game already in the SIMMs), takes
the header, key and code/data map of that game, and rewrites SIMM 1/2 in the
target format while flashing (see hook.py).

Usage: build_bios.py [--sh2] sfiii3_euro.29f400.u2 games.txt out.u2
  default: cart whose battery is dead or removed, original custom CPU (key 0/0):
           MAME set cps3boota;
  --sh2  : cart whose custom CPU was replaced by a standard SH-2 (HD6417095),
           MAME set cps3boot: nothing is encrypted, the BIOS is in clear and
           SIMM 1/2 are simply decrypted with the game key; no map needed,
           except for 2nd Impact (CD in dead-cart format: the key-0 mask is
           removed from the code half-words only, using its map). ':c' patches
           (dead cart only) are ignored.

games.txt: one line per CD (the first one is the default game):
    image.cue  key1  key2  map.npz  [options and patches]
  key1/key2 in hex (keys from MAME, src/mame/capcom/cps3.cpp);
  map = code/data map from maptools/ ("-" = none);
  "0 0" for 2nd Impact (CD already in dead-cart format).
  Comma-separated options:
    header=adr  copy of the BIOS header 0x1FEC0-0x1FEFF written to a free
                SIMM area (64 bytes + 4-byte mark), so that the region and the
                CD / No CD version can be chosen in the menu; the game's reads
                of the header are redirected to it;
    asia=n      region code of Asia for this game (default 2);
    nocd=n      for games whose "No CD" version is a region (Asia without CD):
                choosing No CD sets this region;
    adr=word    patch: the word at SIMM address adr (0x06xxxxxx) becomes word
                (final value). ':c' after the word = this word is code (the map
                is completed). Red Earth reads its region at the old place
                0x1FEDB: 06010de8=0001fecb,... JoJo and JoJo BA: their scheduler
                loads SR/GBR of a task from game code (a data read, which gives
                other bytes on a dead cart): SR is masked (and #0x11) so that
                interrupts stay enabled as on the original.
"""
import sys, os, struct, zlib
import numpy as np
here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, here)
import cps3crypt as t, sh2asm, hook as hu
from cdimage import iso_files, bin_of

def bounds_from_code(code):
    """Half-word indexes where the class changes (code <-> data); starts as data."""
    c = np.concatenate([[False], code.astype(bool), [False]])
    return np.nonzero(c[1:] != c[:-1])[0].astype(np.uint32)

def load_map(path):
    """Code/data map: one bool per half-word of SIMM 1 from 0x06000000
    (.npy, or .npz holding 'bits' = np.packbits of the map and 'n')."""
    if path.endswith('.npz'):
        z = np.load(path)
        return np.unpackbits(z['bits'])[:int(z['n'])].astype(bool)
    return np.load(path)

def parse_patch(txt, opts=None):
    """'adr=word,adr=word:c,...' -> [(adr, word)], [adr...] (':c' = the word
    becomes code). Options header=, asia=, nocd= go to opts."""
    patch, pcode = [], []
    for kv in filter(None, txt.split(',')):
        a, v = kv.split('=')
        if a in ('header', 'asia', 'nocd'):
            if opts is not None: opts[a] = int(v, 16)
            continue
        if v.endswith(':c'):
            v = v[:-2]; pcode.append(int(a, 16))
        patch.append((int(a, 16), int(v, 16)))
    return patch, pcode

def prog_plain(files, read, k1, k2):
    """File 10 (SIMM 1/2, 8 MB) as read as data by the original game."""
    lba, sz = files['10']
    w = np.frombuffer(read(lba, sz), '>u4').astype(np.uint32)
    if k1 or k2:
        w = w ^ t.mask_array(0x06000000, len(w) * 4, k1, k2)
    return w

def redirects(w, code, copy, explicit):
    """Literals 0x1FEC0-0x1FEFF close to code (pool within 1 KB) -> copy."""
    out = []
    idx = np.nonzero((w >= 0x1fec0) & (w < 0x1ff00))[0]
    cs = np.concatenate([[0], np.cumsum(code[:len(w) * 2], dtype=np.int64)])
    for i in idx:
        a = 0x06000000 + 4 * int(i)
        h = 2 * int(i); lo = max(0, h - 512); hi = min(len(cs) - 1, h + 514)
        if a in explicit or cs[hi] - cs[lo] == 0:
            continue
        out.append((a, copy + int(w[i]) - 0x1fec0))
    return out

def mark_code(code, pcode):
    code = code.copy()
    for a in pcode:
        i = (a - 0x06000000) // 2
        code[i:i + 2] = True
    return code

def make_header(vol, files, read, base_hdr):
    """Header in the format of 0x1FEC0 of the sfiii3 BIOS, from the CD contents."""
    def bsum(names):
        s = 0
        for nm in names:
            lba, sz = files[nm]
            s += int(np.frombuffer(read(lba, sz), np.uint8).sum(dtype=np.uint64))
        return s & 0xff
    h = bytearray(48)
    h[0:11] = vol.encode()[:11].ljust(11, b' ')
    h[11:13] = base_hdr[11:13]                      # region and mode of the base BIOS
    for n in range(1, 7):
        e = 0x14 + 4 * (n - 1)
        if n <= 2:
            names = [f'{n}0'] if f'{n}0' in files else []
            flag = 1 if names else 0
        else:
            names = [x for x in (f'{n}0', f'{n}1') if x in files]
            flag = 0 if not names else (1 if f'{n}1' in files else 2)
        if flag:
            h[e] = flag; h[e + 1] = bsum(names)
            if base_hdr[:8] == h[:8] and base_hdr[e:e + 2] == h[e:e + 2]:
                h[e + 2] = base_hdr[e + 2]        # 3rd byte known (original BIOS of the same game)
    return bytes(h)

def main():
    sh2 = '--sh2' in sys.argv
    src, cfg, dst = [a for a in sys.argv[1:] if a != '--sh2'][:3]
    raw = open(src, 'rb').read()
    if zlib.crc32(raw) != 0x30bbf293:
        sys.exit('%s: CRC32 %08x, expected 30bbf293 (MAME sfiii3_euro.29f400.u2, '
                 'dump of the SFIII 3rd Strike Euro cart BIOS)' % (src, zlib.crc32(raw)))
    ro = np.frombuffer(raw, '>u4').astype(np.uint32)
    K1, K2 = 0xA55432B4, 0x0C129981                 # key of the original sfiii3 BIOS
    mg = t.mask_array(0, 0x80000, K1, K2); m0 = t.mask_array(0, 0x80000, 0, 0)
    mc = t.mask_array(0xC0000000, 0x400, K1, K2); m0c = t.mask_array(0xC0000000, 0x400, 0, 0)
    plain = ro ^ mg
    p = bytearray(plain.astype('>u4').tobytes())
    base_hdr = bytes(p[0x1fec0:0x1fef0])
    assert base_hdr[:8] == b'CAP-33S-', 'expected base BIOS: sfiii3_euro.29f400.u2'

    games = []
    for line in open(cfg):
        line = line.split('#')[0].split()
        if not line: continue
        cue, k1, k2, mapf = line[0], int(line[1], 16), int(line[2], 16), line[3]
        opts = {}
        patch, pcode = parse_patch(line[4] if len(line) > 4 else '', opts)
        vol, files, read = iso_files(bin_of(cue), cue)
        hdr = make_header(vol, files, read, base_hdr)
        copy = opts.get('header', 0); asia = opts.get('asia', 2); ncd = opts.get('nocd', 0)
        if copy:
            # region chosen in the menu: BIOS header copied to the SIMMs, game reads redirected
            assert copy % 0x40 == 0 and 0x06000000 <= copy and copy + 0x44 <= 0x06000000 + files['10'][1], hex(copy)
            w = prog_plain(files, read, k1, k2)
            code = np.zeros(len(w) * 2, bool)
            if mapf != '-':
                m = load_map(mapf); code[:min(len(m), len(code))] = m[:len(code)]
            explicit = {a for a, v in patch}
            patch = [(a, copy + v - 0x1fec0 if 0x1fec0 <= v < 0x1ff00 else v) for a, v in patch]
            rd = redirects(w, code, copy, explicit)
            zone = [int(x) for x in w[(copy - 0x06000000) // 4:(copy - 0x06000000) // 4 + 17]]
            assert all(x == zone[0] for x in zone) and zone[0] in (0, 0xffffffff), ('header= area not free', [hex(x) for x in zone])
            patch += rd
            print('   header copy at %08x, %d reads redirected' % (copy, len(rd)))
        # final value in the SIMM: dead cart, code word = plain ^ m0
        if not sh2:
            patch = [(a, v ^ t.mask_scalar(a, 0, 0) if a in pcode else v) for a, v in patch]
        patch.sort()
        if sh2:
            patch = [pv for pv in patch if pv[0] not in pcode]
            if k1 == 0 and k2 == 0:
                assert mapf != '-', '--sh2: a code map is needed for a CD in dead-cart format'
                c = np.zeros(0x800000, bool); m = load_map(mapf); c[:len(m)] = m
                b = bounds_from_code(~c)          # mask removed outside code
            else:
                b = np.zeros(0, np.uint32)        # decryption only
        else:
            b = None if (mapf == '-' or (k1 == 0 and k2 == 0)) else bounds_from_code(mark_code(load_map(mapf), pcode))
        games.append((vol, hdr, k1, k2, b, patch, copy, asia, ncd))
        print('%-12s key %08x/%08x  %s  header %s' % (vol, k1, k2,
              'SIMMs as is' if b is None else '%d boundaries' % len(b) if len(b) else 'decryption only',
              hdr[0x14:0x2c].hex(' ', 4)))
        for a, v in patch:
            print('   patch %08x: %08x' % (a, v))
    ids = [g[0] for g in games]
    for i, a in enumerate(ids):                      # no ID may hide another one
        for b_ in ids[i + 1:]:
            assert not b_.startswith(a), (a, b_)

    code, lab = sh2asm.assemble(hu.source(0, len(games), sh2=sh2), hu.HOOK_ADDR)
    MENU = (hu.HOOK_ADDR + len(code) + 15) & ~15
    menu, title, vals = hu.menu_tables(MENU)
    GAMES = (MENU + len(menu) + 15) & ~15
    code, lab = sh2asm.assemble(hu.source(GAMES, len(games), title, vals, sh2=sh2), hu.HOOK_ADDR)
    assert hu.HOOK_ADDR + len(code) <= MENU
    PL = GAMES + hu.ENTRY * len(games)
    plists = bytearray(); paddr = []
    for g in games:
        if g[5]:
            paddr.append(PL + len(plists))
            for a, v in g[5]:
                assert a & 3 == 0 and 0x06000000 <= a < 0x06800000
                plists += struct.pack('>II', a, v)
            plists += struct.pack('>I', 0)
        else:
            paddr.append(0)
    tab = (PL + len(plists) + 0xff) & ~0xff
    table = bytearray(); maps = bytearray()
    for (vol, hdr, k1, k2, b, patch, copy, asia, ncd), pa in zip(games, paddr):
        if b is None:
            prm = (0, 0, 0, 0, 0, 1, pa)
        elif len(b) == 0:
            prm = (k1, k2, 0, 0, 0, 0, pa)
        else:
            prm = (k1, k2, tab + len(maps), len(b), int(b[-1]), 0, pa)
            maps += b.astype('>u4').tobytes()
        prm += (copy, asia, ncd)
        table += vol.encode().ljust(hu.IDLEN, b'\0')[:hu.IDLEN] + hdr + struct.pack('>%dI' % hu.NPARAM, *prm)
    table += plists
    end = tab + len(maps)
    assert end <= 0x7ff00, 'maps too large: %x' % end
    p[hu.HOOK_ADDR:hu.HOOK_ADDR + len(code)] = code
    p[GAMES:GAMES + len(table)] = table
    p[MENU:MENU + len(menu)] = menu
    p[tab:end] = maps

    def lit(a, old, new):
        assert struct.unpack('>I', p[a:a + 4])[0] == old, (hex(a), p[a:a + 4].hex())
        p[a:a + 4] = struct.pack('>I', new)
    H = hu.HDR
    for a, old, new in ((0x2678, 0x1fecb, H + 0xb), (0x2b5c, 0x1fed0, H + 0x10), (0x2b6c, 0x1fec0, H),
                        (0x2b90, 0x1fedc, H + 0x1c), (0x31a0, 0x1fed8, H + 0x18), (0x3508, 0x1fec0, H),
                        (0x2b74, 0x7750, lab['sel_simm']), (0x350c, 0x7750, lab['sel_cd']),
                        (0x490, 0x498, lab['init']), (0xb924, 0x80808080, lab['hook']),
                        (0x18a20, 0x2a36, lab['pre2']), (0x18a44, 0x3b0a, lab['st11'])):
        lit(a, old, new)
    assert p[0xb7be:0xb7c4] == bytes.fromhex('68a2d2582289')
    p[0xb7be:0xb7c4] = bytes.fromhex('d259420b0009')    # mov.l @r10,r8 -> jsr hook
    assert p[0x39f8:0x39fa] == bytes.fromhex('3130')
    p[0x39f8:0x39fa] = bytes.fromhex('3330')            # byte sum: of the converted buffer
    patched = np.frombuffer(bytes(p), '>u4').astype(np.uint32)

    if sh2:   # standard SH-2: all in clear; DMA area raw; cache without mask
        out = patched.copy()
        out[0x1ff00//4:0x20000//4] = ro[0x1ff00//4:0x20000//4]
        out[(end + 3) // 4:] = ro[(end + 3) // 4:]
        for i in range(0x510//4, 0x534//4):
            out[i] = plain[i] ^ mc[i - 0x510//4]
        open(dst, 'wb').write(out.astype('>u4').tobytes())
        print('wrote %s (standard SH-2); %d games; code %d bytes; table %x; maps %x-%x' % (dst, len(games), len(code), GAMES, tab, end))
        return
    out = patched ^ m0
    out[0x1ff00//4:0x20000//4] = ro[0x1ff00//4:0x20000//4]
    out[0x20000//4:] = plain[0x20000//4:]
    s = slice(hu.HOOK_ADDR // 4, (end + 3) // 4)
    out[s] = patched[s] ^ m0[s]                         # read by the CPU: dead-key encrypted
    for i in range(0x510//4, 0x534//4):
        ci = i - 0x510//4
        out[i] = (plain[i] ^ mc[ci] ^ m0c[ci]) ^ m0[i]
    open(dst, 'wb').write(out.astype('>u4').tobytes())
    print('wrote %s (dead cart); %d games; code %d bytes; table %x; maps %x-%x' % (dst, len(games), len(code), GAMES, tab, end))

if __name__ == '__main__':
    main()
