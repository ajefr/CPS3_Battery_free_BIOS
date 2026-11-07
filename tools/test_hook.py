#!/usr/bin/env python3
# Checks hook.py on a tiny SH-2 emulator: game choice (init,
# sel_cd, sel_simm, pre2), forced rewrite, menus, SIMM check, and the conversion
# of the words of each game against the Python reference.
# Usage: test_hook.py [map1.npz map2.npz map3.npz]   (default: 3rd Strike, JoJo, Red Earth)
import sys, os, struct, random
import numpy as np
here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, here)
import cps3crypt as t, sh2asm, hook as hu
from build_bios import bounds_from_code, load_map

M = 0xffffffff
STOP = 0xdead0000

class Mem:
    def __init__(self): self.b = {}
    def w8(self, a, v): self.b[a & M] = v & 0xff
    def r8(self, a): return self.b.get(a & M, 0)
    def w32(self, a, v):
        for i in range(4): self.w8(a + i, v >> (24 - 8 * i))
    def r32(self, a):
        assert a & 3 == 0, hex(a)
        return sum(self.r8(a + i) << (24 - 8 * i) for i in range(4))
    def load(self, a, data):
        for i, x in enumerate(data): self.b[a + i] = x

def run(mem, pc, regs, stops):
    pr = STOP; T = 0; delay = None; steps = 0
    sx8 = lambda v: v - 0x100 if v & 0x80 else v
    while True:
        steps += 1; assert steps < 20000000
        op = (mem.r8(pc) << 8) | mem.r8(pc + 1)
        n = (op >> 8) & 15; m = (op >> 4) & 15; npc = pc + 2; target = None
        s8 = sx8(op & 0xff)
        if op == 0x0009: pass
        elif op == 0x000b: target = pr
        elif op == 0x4f22: regs[15] -= 4; mem.w32(regs[15], pr)
        elif op == 0x4f26: pr = mem.r32(regs[15]); regs[15] += 4
        elif op >> 12 == 0xb:
            d = op & 0xfff; d -= 0x1000 if d & 0x800 else 0; pr = pc + 4; target = pc + 4 + d * 2
        elif op >> 12 == 0xa:
            d = op & 0xfff; d -= 0x1000 if d & 0x800 else 0; target = pc + 4 + d * 2
        elif op & 0xff00 == 0x8900:
            if T: npc = pc + 4 + s8 * 2
        elif op & 0xff00 == 0x8b00:
            if not T: npc = pc + 4 + s8 * 2
        elif op >> 12 == 0xd: regs[n] = mem.r32((pc & ~3) + 4 + (op & 0xff) * 4)
        elif op >> 12 == 0xe: regs[n] = s8 & M
        elif op >> 12 == 0x7: regs[n] = (regs[n] + s8) & M
        elif op >> 12 == 0x5: regs[n] = mem.r32((regs[m] + (op & 15) * 4) & M)
        elif op & 0xff00 == 0xc900: regs[0] &= op & 0xff
        elif op & 0xf00f == 0x000e: regs[n] = mem.r32((regs[0] + regs[m]) & M)
        elif op & 0xf00f == 0x6002: regs[n] = mem.r32(regs[m])
        elif op & 0xf00f == 0x6006: regs[n] = mem.r32(regs[m]); regs[m] += 4
        elif op >> 12 == 0x1: mem.w32((regs[n] + (op & 15) * 4) & M, regs[m])
        elif op & 0xf00f == 0x6001:
            v = (mem.r8(regs[m]) << 8) | mem.r8(regs[m] + 1); regs[n] = (v - 0x10000 if v & 0x8000 else v) & M
        elif op & 0xf00f == 0x6000: regs[n] = sx8(mem.r8(regs[m])) & M
        elif op & 0xf00f == 0x2000: mem.w8(regs[n], regs[m])
        elif op & 0xf00f == 0x600c: regs[n] = regs[m] & 0xff
        elif op & 0xf00f == 0x6004: regs[n] = sx8(mem.r8(regs[m])) & M; regs[m] += 1
        elif op & 0xf00f == 0x2002: mem.w32(regs[n], regs[m])
        elif op & 0xf00f == 0x2006: regs[n] -= 4; mem.w32(regs[n], regs[m])
        elif op & 0xf00f == 0x6003: regs[n] = regs[m]
        elif op & 0xf00f == 0x600d: regs[n] = regs[m] & 0xffff
        elif op & 0xf00f == 0x2008: T = int(regs[n] & regs[m] == 0)
        elif op & 0xf00f == 0x2009: regs[n] &= regs[m]
        elif op & 0xf00f == 0x200a: regs[n] ^= regs[m]
        elif op & 0xf00f == 0x200b: regs[n] |= regs[m]
        elif op & 0xf00f == 0x300c: regs[n] = (regs[n] + regs[m]) & M
        elif op & 0xf00f == 0x3008: regs[n] = (regs[n] - regs[m]) & M
        elif op & 0xf00f == 0x3000: T = int(regs[n] == regs[m])
        elif op & 0xf00f == 0x3002: T = int(regs[n] >= regs[m])
        elif op & 0xf00f == 0x3006: T = int(regs[n] > regs[m])
        elif op & 0xf0ff == 0x4010: regs[n] = (regs[n] - 1) & M; T = int(regs[n] == 0)
        elif op & 0xf0ff == 0x402b: target = regs[n]
        elif op & 0xf0ff == 0x400b: pr = pc + 4; target = regs[n]
        elif op & 0xf0ff == 0x4001: regs[n] >>= 1
        elif op & 0xf0ff == 0x4008: regs[n] = (regs[n] << 2) & M
        elif op & 0xf0ff == 0x4009: regs[n] >>= 2
        elif op & 0xf0ff == 0x4018: regs[n] = (regs[n] << 8) & M
        elif op & 0xf0ff == 0x4019: regs[n] >>= 8
        elif op & 0xf0ff == 0x4028: regs[n] = (regs[n] << 16) & M
        elif op & 0xf0ff == 0x4029: regs[n] >>= 16
        else: raise Exception('op %04x a %x' % (op, pc))
        if delay is not None:
            pc = delay; delay = None
            if pc in stops: return pc, steps
            continue
        if target is not None: delay = target
        pc = npc

def entry_bytes(ident, header, *prm):
    e = ident.encode().ljust(hu.IDLEN, b'\0') + header + struct.pack('>%dI' % hu.NPARAM, *prm)
    assert len(e) == hu.ENTRY
    return e

if __name__ == '__main__':
    K = [(0xA55432B4, 0x0C129981), (0x02203ee3, 0x01301972), (0x23323ee3, 0x03021972)]
    IDS = ['CAP-33S-1', 'CAP-33S-2', 'CAP-JJK']
    files = sys.argv[1:] or [os.path.join(here, '..', 'maps', m + '.npz') for m in ('sfiii3', 'jojo', 'redearth')]
    maps = [load_map(f) for f in files]
    while len(maps) < 3: maps.append(maps[-1])
    GAMES = 0x20b00
    MENU = 0x20780
    menu, title, vals = hu.menu_tables(MENU)
    code, lab = sh2asm.assemble(hu.source(GAMES, len(IDS) + 1, title, vals), hu.HOOK_ADDR)
    assert hu.HOOK_ADDR + len(code) <= MENU and MENU + len(menu) <= GAMES
    mem = Mem(); mem.load(hu.HOOK_ADDR, code); mem.load(MENU, menu)
    mem.load(0x2b0e, bytes.fromhex('000b0009'))      # file table: rts
    ROMHDR = bytes(random.getrandbits(8) for _ in range(64)); mem.load(0x1fec0, ROMHDR)
    COPY = 0x06700000
    tab = 0x21000; ents = []
    PL = 0x20f00; PATCH = {0x06010de8: 0x0001fecb, 0x06000004: 0x12345678, 0x06123450: 0x0670000b}
    for j, (a, v) in enumerate(sorted(PATCH.items())):
        mem.w32(PL + 8 * j, a); mem.w32(PL + 8 * j + 4, v)
    mem.w32(PL + 8 * len(PATCH), 0)
    for i, ident in enumerate(IDS):
        b = bounds_from_code(maps[i])
        hdr = bytes(random.getrandbits(8) for _ in range(48))
        mem.load(tab, b.astype('>u4').tobytes())
        ents.append((ident, hdr, K[i][0], K[i][1], tab, len(b), int(b[-1]), 0, PL if i == 2 else 0,
                     COPY if i == 2 else 0, 2, 0, maps[i]))
        tab += 4 * len(b)
    # CD already in dead-cart format: patches and header copy too
    ents.append(('CAP-3GA', bytes(48), 0, 0, 0, 0, 0, 1, PL, COPY, 8, 2, None))
    for i, e in enumerate(ents):
        mem.load(GAMES + i * hu.ENTRY, entry_bytes(*e[:2 + hu.NPARAM]))

    def cur(): return [mem.r32(hu.CUR + 4 * i) for i in range(hu.NPARAM)]
    def hdr(): return bytes(mem.r8(hu.HDR + i) for i in range(48))
    def check_sel(i, reg=None):
        h = bytearray(ents[i][1])
        if reg is not None: h[11] = reg
        # BIOS NOCD flag: No CD choice, cleared while P1 Start is held
        start = (mem.r32(0x05000000) & 0x10000000) == 0
        h[12] = (h[12] & 0xfe) | (0 if start else mem.r32(hu.MENUVAR + 8))
        assert hdr() == bytes(h) and cur() == list(ents[i][2:2 + hu.NPARAM]), i

    # init: no game in the SIMMs -> entry 0
    mem.w32(0x05000000, 0xffffffff)                  # no input
    regs = [0] * 16; regs[15] = 0x1000
    pc, st = run(mem, lab['init'], regs, {0x498}); assert pc == 0x498
    check_sel(0)
    # init chooses the game in the SIMMs (BIOS state 0 reads its NOCD flag)
    for i, ident in enumerate(IDS):
        mem.load(0x067fffe0, (ident + '   ').encode())
        for inp in (0xffffffff, 0xefffffff):
            mem.w32(0x05000000, inp)
            regs = [0] * 16; regs[15] = 0x1000
            pc, _ = run(mem, lab['init'], regs, {0x498}); assert pc == 0x498; check_sel(i)
    mem.w32(0x05000000, 0xffffffff); mem.load(0x067fffe0, bytes(16))
    regs = [0] * 16; regs[15] = 0x1000; run(mem, lab['init'], regs, {0x498}); check_sel(0)
    print('init OK (game from the SIMMs, default entry 0, NOCD flag); %d instructions' % st)

    # sel_cd: CD ID at @(@0x0201ef40)+7; sel_simm: ID at 0x067fffe0
    for i, ident in enumerate(IDS + ['CAP-3GA-1']):
        for kind in ('sel_cd', 'sel_simm'):
            s = (ident + '   ').encode()
            if kind == 'sel_cd':
                mem.w32(0x0201ef40, 0x0202f000); mem.load(0x0202f000 + 7, s)
            else:
                mem.load(0x067fffe0, s.ljust(32, b'\0'))
            regs = [0] * 16; regs[15] = 0x1000
            regs[4], regs[5], regs[6] = 0x0201b108, hu.HDR, 11
            pc, _ = run(mem, lab[kind], regs, {0x7750})
            assert pc == 0x7750 and regs[4:7] == [0x0201b108, hu.HDR, 11] and regs[15] == 0x1000
            check_sel(i)
    # unknown ID: nothing changes; other source: plain memcpy
    mem.load(0x067fffe0, b'CAP-XYZ-1   '); regs = [0] * 16; regs[15] = 0x1000
    regs[4], regs[5], regs[6] = 1, hu.HDR, 11
    run(mem, lab['sel_simm'], regs, {0x7750}); check_sel(3)
    regs = [0] * 16; regs[15] = 0x1000; regs[4], regs[5], regs[6] = 1, 0x1234, 11
    mem.load(0x067fffe0, b'CAP-33S-1   ')
    run(mem, lab['sel_simm'], regs, {0x7750}); check_sel(3)
    # pre2: choice from the SIMMs, then BIOS state 2
    for i, ident in enumerate(IDS):
        mem.load(0x067fffe0, (ident + '   ').encode())
        regs = [0] * 16; regs[15] = 0x1000; regs[4:8] = [4, 5, 6, 7]
        pc, _ = run(mem, lab['pre2'], regs, {0x2a36})
        assert pc == 0x2a36 and regs[4:8] == [4, 5, 6, 7] and regs[15] == 0x1000
        check_sel(i)
    # region read back from the header copy in the SIMMs (if valid)
    mem.load(COPY, ROMHDR[:8] + b'\0\0\0\x07' + bytes([ROMHDR[12] ^ 1])); mem.load(0x067fffe0, b'CAP-JJK   ')
    regs = [0] * 16; regs[15] = 0x1000; regs[5] = hu.HDR
    run(mem, lab['sel_simm'], regs, {0x7750}); check_sel(2, 7)
    assert mem.r32(hu.MENUVAR + 8) == (ROMHDR[12] ^ 1) & 1
    mem.load(COPY, b'CAP-JJK-'); regs = [0] * 16; regs[15] = 0x1000; regs[5] = hu.HDR
    run(mem, lab['sel_simm'], regs, {0x7750}); check_sel(2)
    assert mem.r32(hu.MENUVAR + 8) == ROMHDR[12] & 1
    # forced rewrite (state 10): sel_cd then copy of the SIMM ID
    FORCE = hu.MENUVAR + 12
    def state10(copy_bytes, inputs):
        mem.load(COPY, copy_bytes); mem.w32(0x05000000, inputs)
        mem.w32(0x0201ef40, 0x0202f000); mem.load(0x0202f000 + 7, b'CAP-JJK   ')
        regs = [0] * 16; regs[15] = 0x1000; regs[4], regs[5], regs[6] = 0x0201b108, hu.HDR, 11
        pc, _ = run(mem, lab['sel_cd'], regs, {0x7750}); assert pc == 0x7750; check_sel(2, copy_bytes[11] if copy_bytes[:8] == ROMHDR[:8] else None)
        f = mem.r32(FORCE)
        # 2nd call: copy of the SIMM ID; BIOS memcpy replaced by rts,
        # destination already filled
        mem.load(0x7750, bytes.fromhex('000b0009')); mem.load(0x0201b0fc, b'CAP-JJK    ')
        regs = [0] * 16; regs[15] = 0x1000; regs[4], regs[5], regs[6] = 0x0201b0fc, 0x067fffe0, 11
        pc, _ = run(mem, lab['sel_cd'], regs, {STOP}); assert pc == STOP and regs[15] == 0x1000
        assert mem.r8(0x0201b0fc) == (0 if f else ord('C')) and mem.r8(0x0201b0fd) == ord('A')
        mem.load(0x7750, bytes(4))
        return f
    good = ROMHDR[:11] + b'\x07' + ROMHDR[12:64] + struct.pack('>I', hu.MARK_DEAD)
    assert state10(good, 0xffffffff) == 0
    assert state10(good, 0xefffffff) == 1                       # P1 Start held
    assert state10(good[:64] + struct.pack('>I', hu.MARK_SH2), 0xffffffff) == 1
    assert state10(bytes(68), 0xffffffff) == 1                  # SIMMs from a battery cart
    print('forced rewrite OK (P1 Start, mark missing or other version)')
    print('selection OK (CD, SIMM, state 2, unknown ID, other memcpy, region in SIMM)')

    # region menu (state 11): BIOS display routines = rts
    for a in (0xf524, 0x1056c, 0xf446): mem.load(a, bytes.fromhex('000b0009'))
    mem.load(0x067fffe0, b'CAP-3GA-1  '); regs = [0] * 16; regs[15] = 0x1000; regs[5] = hu.HDR
    run(mem, lab['sel_simm'], regs, {0x7750}); check_sel(3)
    def st11(inp=0, idx=0):
        mem.w32(0x0201b140, idx); mem.w8(0x020389ba, inp >> 8); mem.w8(0x020389bb, inp)
        regs = [0] * 16; regs[15] = 0x1000; regs[8], regs[9] = 0x88, 0x99
        pc, _ = run(mem, lab['st11'], regs, {STOP, 0x3b0a})
        assert regs[15] == 0x1000 and (pc == 0x3b0a or (regs[8], regs[9]) == (0x88, 0x99))
        return pc
    mem.w32(0x0201d2f4, 11)
    assert st11(idx=1) == 0x3b0a                      # Cancel: original state 11
    mem.w8(hu.HDR + 11, 8)                            # Asia (code 8 for this game)
    st11(); assert mem.r32(hu.MENUVAR) == 1 and mem.r32(hu.MENUVAR + 4) == 1
    for k, e in ((2, 2), (2, 3), (1, 2), (1, 1), (1, 0), (1, 6), (2, 0), (0, 0)):
        st11(k); assert mem.r32(hu.MENUVAR + 4) == e and mem.r32(0x0201d2f4) == 11
    mem.w32(hu.MENUVAR + 8, 0)
    st11(16); assert mem.r8(hu.HDR + 11) == 1 and mem.r32(0x0201d2f4) == 11 and mem.r32(hu.MENUVAR) == 2
    assert mem.r32(hu.MENUVAR + 4) == 0                              # page 2: CD
    for k, e in ((2, 1), (2, 0), (1, 1), (1, 0), (1, 1)):
        st11(k); assert mem.r32(hu.MENUVAR + 4) == e
    st11(16); assert mem.r32(hu.MENUVAR + 8) == 1 and mem.r32(0x0201d2f4) == 5 and mem.r32(hu.MENUVAR) == 0
    assert mem.r8(hu.HDR + 11) == 2                                  # No CD -> region Asia without CD (nocd=2)
    mem.w32(0x0201d2f4, 11); st11(); st11(2); st11(16); assert mem.r32(hu.MENUVAR + 4) == 1   # No CD already chosen
    st11(1); st11(16); assert mem.r32(hu.MENUVAR + 8) == 0 and mem.r8(hu.HDR + 11) == 3 and mem.r32(0x0201d2f4) == 5
    mem.w32(0x0201d2f4, 11); st11(); st11(2); st11(16); st11(16); assert mem.r8(hu.HDR + 11) == 4
    # SIMM check when confirming: 0xA578 returns the SIMM type code (table)
    stub, _ = sh2asm.assemble('mov.l Lt,r1\nmov r4,r0\nshll2 r0\nrts\nmov.l @(r0,r1),r0\n.align\nLt:\n.long 0x0201c000', 0xa578)
    mem.load(0xa578, stub); mem.load(0x2140, bytes.fromhex('000b0009'))
    def simms(codes):
        for k, c in enumerate(codes): mem.w32(0x0201c000 + 4 * k, c)
    def flash(flags, codes):
        for k in range(8): mem.w8(hu.HDR + 0x10 + 4 * k, flags[k])
        simms(codes); mem.w32(0x0201d2f4, 11); mem.w32(0x0201b13c, 0)
        st11(); st11(16); st11(16)
        assert mem.r32(hu.MENUVAR) == 0
        return mem.r32(0x0201d2f4)
    F = [0, 1, 1, 2, 2, 2, 0, 0]
    assert flash(F, [0, 4, 4, 4, 0x34, 4, 0, 0]) == 5                  # all present (32M allowed in SIMM 3-5)
    assert flash(F, [0, 4, 4, 0, 4, 4, 4, 4]) == 13 and mem.r32(0x0201b13c) == 0xffffffff   # SIMM 3 missing
    assert flash(F, [0, 4, 0x34, 4, 4, 4, 0, 0]) == 13                # 32M in SIMM 2 (64M required)
    assert flash([0] * 8, [0] * 8) == 5
    print('region and CD/No CD menus OK, SIMM check OK')

    for gi, e in enumerate(ents):
        ident, _, k1, k2, _, _, _, flags, patch, copy, _, _, cmap = e
        # choose the game
        mem.load(0x067fffe0, (ident + '-').encode())
        regs = [0] * 16; regs[15] = 0x1000; regs[5] = hu.HDR
        run(mem, lab['sel_simm'], regs, {0x7750}); check_sel(gi)
        H = len(cmap) if cmap is not None else 0
        addrs = [random.randrange(0, 0x1000000, 4) for _ in range(1500)]
        if patch: addrs += [a - 0x06000000 for a in PATCH]
        if copy: addrs += [copy - 0x06000000 + 4 * j for j in range(-2, 18)]
        reg = mem.r8(hu.HDR + 11); nocd = random.randrange(2); mem.w32(hu.MENUVAR + 8, nocd)
        if cmap is not None:
            for v in bounds_from_code(cmap)[::23]:
                addrs += [(int(v) * 2) & ~3, (int(v) * 2 - 2) & ~3]
        mx = 0
        for off in addrs:
            a = 0x26000000 + off; data = random.getrandbits(32)
            mem.w32(0x0201b000, data)
            regs = [0] * 16; regs[10] = 0x0201b000; regs[14] = a; regs[15] = 0x1000
            for r in (9, 11, 12, 13): regs[r] = 0x1111 * r
            _, st = run(mem, lab['hook'], regs, {STOP}); mx = max(mx, st)
            if flags:
                exp = data
            else:
                plain = data ^ t.mask_scalar(0x06000000 + off, k1, k2)
                m0 = t.mask_scalar(0x06000000 + off, 0, 0) & 0xffff
                i = off // 2
                hi = i < H and cmap[i]; lo = i + 1 < H and cmap[i + 1]
                exp = plain ^ ((m0 << 16) if hi else 0) ^ (m0 if lo else 0)
            if patch: exp = PATCH.get(0x06000000 + off, exp)      # final value
            if copy and 0x06000000 + off - copy == 64:
                exp = hu.MARK_DEAD
            elif copy and 0 <= 0x06000000 + off - copy < 64:
                o = 0x06000000 + off - copy
                exp = struct.unpack('>I', ROMHDR[o:o + 4])[0]
                if o == 8: exp = (exp & 0xffffff00) | reg
                if o == 12: exp = (exp & 0xfeffffff) | (nocd << 24)
            got = mem.r32(0x0201b000)
            assert got == exp and regs[8] == exp and regs[2] == exp & 0x80808080, (ident, hex(off), hex(got), hex(exp))
            assert all(regs[r] == 0x1111 * r for r in (9, 11, 12, 13)) and regs[15] == 0x1000
        print('hook OK', ident, len(addrs), 'words; worst case', mx, 'instructions')
