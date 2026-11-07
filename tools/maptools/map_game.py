#!/usr/bin/env python3
"""Code/data map of a CPS3 program (SIMM 1/2 in clear, base 0x06000000).

Static analysis only: recursive descent from the vector table, GCC 'switch'
tables (mova + braf, and the older mov.w/add/jmp form), then repeated passes
over pointers into the code area and over function starts after an
unconditional jump. Each new piece is accepted only if it decodes without an
invalid opcode and without overlapping known data.

Usage: map_game.py prog.bin out.npz [code_area_end_hex] [--dead-key]
  prog.bin: SIMM1 then SIMM2 in clear (16 MB, from ../cdimage.py), big-endian
            32-bit words.
  --dead-key: prog.bin is in dead-cart format (2nd Impact, raw CD).
  Recommended end: 800000 (the whole SIMM 1; JoJo and Red Earth have code far
  away). Without an end, it is found where the code density drops.
  Isolated code (less than 10 % of a 16 KB block) is removed at the end.
The maps in ../../maps were made this way, then corrected with MAME coverage
logs (coverage.lua + play.lua, then fix_map.py).
"""
import sys, os, numpy as np, static

B = static.BASE

def run(d, END, op=None):
    """d: bytes read as data; op: bytes seen as instructions (default d)."""
    if op is None: op = d
    H = END // 2
    vec = [int.from_bytes(d[i:i + 4], 'big') for i in range(0, 0x400, 4)]
    seeds = [v for v in vec if B <= v < B + END and not v & 1]
    code, lit, mova, bad = static.analyse(op, seeds, end=END, ddata=d)
    st = {'code': code, 'lit': lit}

    def trial(seed):
        c2, l2 = st['code'].copy(), st['lit'].copy()
        _, _, _, bad = static.analyse(op, [seed], end=END, code=c2, lit=l2, barrier=st['lit'], ddata=d)
        if bad or (c2 & l2).any():
            return False
        new = c2 & ~st['code']
        if SUSPECT[new].any():          # opcodes typical of small values (data)
            return False
        st['code'], st['lit'] = c2, l2
        return True

    ops0 = np.frombuffer(op[:END], '>u2')
    SUSPECT = np.isin(ops0, [0x0004, 0x0005, 0x0006, 0x0007, 0x000c, 0x000d, 0x000e, 0x000f, 0x001b])
    w = np.frombuffer(d, '>u4')
    cands = sorted(set(int(v) for v in w if B <= v < B + END and not v & 1))
    ops = np.frombuffer(op[:END], '>u2')
    unc = (ops >> 12 == 0xa) | ((ops & 0xf0ff) == 0x402b) | (ops == 0x000b) | (ops == 0x002b)
    for it in range(60):
        acc = 0
        for v in cands:
            i = (v - B) >> 1
            if not (st['code'][i] or st['lit'][i]):
                acc += trial(v)
        code, lit = st['code'], st['lit']
        ends = np.nonzero(code[:-2] & unc[:-2] & code[1:-1])[0] + 2
        for i in ends:
            j = i
            while j < H and (st['lit'][j] or ops[j] in (0x0009, 0x0000)) and not st['code'][j]:
                j += 1
            if j < H and not st['code'][j] and not st['lit'][j]:
                acc += trial(B + 2 * j)
            # function prologue (sts.l pr,@-r15 / mov.l rm,@-r15) a bit further
            for k in range(i, min(i + 64, H)):
                if st['code'][k]: break
                if not st['lit'][k] and (ops[k] == 0x4f22 or ops[k] & 0xff0f == 0x2f06):
                    acc += trial(B + 2 * k); break
        if acc == 0:
            break
    return st['code'], st['lit']

def filter_isolated(code, blk=8192, threshold=0.10):
    """Removes isolated code: 16 KB blocks where it is under 10 % (false code
    found in data by the pointer pass)."""
    H = len(code) // blk * blk
    fr = code[:H].reshape(-1, blk).mean(1)
    out = code.copy()
    out[:H] &= np.repeat(fr >= threshold, blk)
    return out

def find_end(d):
    """Wide area, then end of the last 4 KB block dense in code (>= 50 %);
    false code found in data stays much less dense."""
    code, _ = run(d, 0x400000)
    blk = code.reshape(-1, 2048).mean(1)
    last = np.nonzero(blk >= 0.5)[0].max()
    end = (np.nonzero(code[:(last + 1) * 2048])[0].max() + 1) * 2
    return (end + 0xfff) & ~0xfff

if __name__ == '__main__':
    dead = '--dead-key' in sys.argv
    args = [a for a in sys.argv[1:] if a != '--dead-key']
    d = open(args[0], 'rb').read()
    op = None
    if dead:   # program in dead-cart format (2nd Impact): instructions = bytes ^ mask(0,0)
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
        import cps3crypt as cn
        w = np.frombuffer(d, '>u4').astype(np.uint32)
        op = (w ^ cn.mask_array(B, len(d), 0, 0)).astype('>u4').tobytes()
    END = int(args[2], 16) if len(args) > 2 else find_end(d)
    code, lit = run(d, END, op)
    code = filter_isolated(code)
    np.savez_compressed(args[1], bits=np.packbits(code), n=np.array(len(code)))
    c = np.concatenate([[False], code, [False]])
    print('code area 0x06000000-0x%08x; code %d half-words; %d boundaries'
          % (B + END, code.sum(), np.count_nonzero(c[1:] != c[:-1])))
