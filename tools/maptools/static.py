"""SH-2 recursive descent over the program in clear (SIMM1/2, base 0x06000000).
Inputs: program bytes, seed addresses. Output: code / literal-data sets."""
import sys, numpy as np
BASE = 0x06000000

def load(path='prog.bin'):
    return open(path, 'rb').read()

def s8(v): return v - 0x100 if v & 0x80 else v
def s12(v): return v - 0x1000 if v & 0x800 else v

def valid(op):
    """Approximation: rejects undefined SH-2 opcodes."""
    n = op >> 12
    if n == 0:
        lo = op & 0xf
        if lo in (0, 1): return False
        if lo == 2: return (op & 0xf0) in (0x00, 0x10, 0x20)
        if lo == 3: return (op & 0xf0) in (0x00, 0x20)
        if lo in (4, 5, 6, 7, 0xc, 0xd, 0xe, 0xf): return True
        if lo == 8: return (op & 0xff0) in (0x000, 0x010, 0x020) and (op & 0xf00) == 0
        if lo == 9: return (op & 0xff0) in (0x000, 0x010) and (op & 0xf00) == 0 or (op & 0xf0) == 0x20
        if lo == 0xa: return (op & 0xf0) in (0x00, 0x10, 0x20)
        if lo == 0xb: return (op & 0xff0) in (0x000, 0x010, 0x020)
        return False
    if n == 3: return (op & 0xf) not in (1, 9)
    if n == 4:
        lo = op & 0xff
        return lo in (0x00,0x01,0x02,0x03,0x04,0x05,0x06,0x07,0x08,0x09,0x0a,0x0b,0x0e,0x0f,
                      0x10,0x11,0x12,0x13,0x15,0x16,0x17,0x18,0x19,0x1a,0x1b,0x1e,
                      0x20,0x21,0x22,0x23,0x24,0x25,0x26,0x27,0x28,0x29,0x2a,0x2b,0x2e) or (lo & 0xf) == 0xf
    if n == 6 or n == 2: return not (n == 2 and (op & 0xf) == 3)
    if n == 8: return ((op >> 8) & 0xf) in (0, 1, 4, 5, 8, 9, 0xb, 0xd, 0xf)
    if n == 0xc: return True
    if n == 0xf: return False
    return True

def analyse(data, seeds, end=None, known=None, code=None, lit=None, barrier=None, ddata=None):
    """data: bytes seen by instruction fetches; ddata: seen by data reads
    (literals, switch tables), the same by default."""
    if ddata is None: ddata = data
    end = end or len(data)
    if code is None: code = np.zeros(end // 2, bool)
    if lit is None: lit = np.zeros(end // 2, bool)
    mova = set()
    work = list(seeds)
    bad = []
    rd = lambda a: (data[a - BASE] << 8) | data[a - BASE + 1]
    rdd = lambda a: (ddata[a - BASE] << 8) | ddata[a - BASE + 1]
    while work:
        pc = work.pop()
        regs = {}
        while True:
            off = pc - BASE
            if off < 0 or off >= end or pc & 1:
                bad.append(pc); break
            i = off >> 1
            if code[i]: break
            op = rd(pc)
            if not valid(op) or lit[i] or (barrier is not None and barrier[i]):
                bad.append(pc); break
            code[i] = True
            if off >= 2 and (code[i - 1] or (known is not None and known[i - 1])):
                pop = rd(pc - 2)
                if pop >> 12 == 0xa or pop & 0xf0ff in (0x402b, 0x0023) or pop in (0x000b, 0x002b):
                    break   # delay slot of an unconditional jump
            n = op >> 12
            rn = (op >> 8) & 0xf
            nxt = pc + 2
            stop = False
            delay = False
            if n == 0x9:
                a = pc + 4 + (op & 0xff) * 2
                if a - BASE < end: lit[(a - BASE) >> 1] = True
                regs.pop(rn, None)
            elif n == 0xd:
                a = (pc & ~3) + 4 + (op & 0xff) * 4
                if 0 <= a - BASE < end - 2:
                    lit[(a - BASE) >> 1] = lit[(a - BASE + 2) >> 1] = True
                    v = int.from_bytes(ddata[a - BASE:a - BASE + 4], 'big')
                    regs[rn] = v
            elif op & 0xff00 == 0xc700:
                regs['mova'] = (pc & ~3) + 4 + (op & 0xff) * 4
                mova.add(regs['mova'])
                regs.pop(0, None)
            elif n == 0xa:
                work.append(pc + 4 + s12(op & 0xfff) * 2); delay = stop = True
            elif n == 0xb:
                work.append(pc + 4 + s12(op & 0xfff) * 2); delay = True
            elif op & 0xf900 == 0x8900:   # bt / bf / bt.s / bf.s
                work.append(pc + 4 + s8(op & 0xff) * 2)
                delay = bool(op & 0x0400)
            elif op & 0xf0ff == 0x402b and rn == 0 and 'wjmp' in regs:
                # old GCC switch: mov.l #tab,rm ; mov.w @(r0,rm),r0 ; add rm,r0 ; jmp @r0
                t = regs['wjmp']; cnt = regs.get('bound', 256)
                for k in range(t, t + 2 * cnt, 2):
                    if not (0 <= k - BASE < end - 1): break
                    e = rdd(k); e = e - 0x10000 if e & 0x8000 else e
                    tg = t + e
                    if tg & 1 or not (0 <= tg - BASE < end) or (t <= tg < k + 2): break
                    lit[(k - BASE) >> 1] = True
                    work.append(tg)
                delay = stop = True
            elif n == 0xe:
                regs[rn] = s8(op & 0xff) & 0xffffffff
            elif op & 0xf00f == 0x3002 and rn == 0:   # cmp/hs rm,r0: switch bound
                rm = (op >> 4) & 0xf
                if rm in regs and regs[rm] <= 1024: regs['bound'] = regs[rm]
            elif op & 0xff0f == 0x000d:   # mov.w @(r0,rm),r0
                rm = (op >> 4) & 0xf
                if rm in regs: regs['wtab'] = (regs[rm], rm)
                regs.pop(0, None)
            elif op & 0xff0f == 0x300c and 'wtab' in regs and regs['wtab'][1] == (op >> 4) & 0xf:
                regs['wjmp'] = regs['wtab'][0]; regs.pop(0, None)
            elif op & 0xf0ff == 0x402b:   # jmp @Rn
                if rn in regs and 0 <= regs[rn] - BASE < end and not regs[rn] & 1: work.append(regs[rn])
                delay = stop = True
            elif op & 0xf0ff == 0x400b:   # jsr @Rn
                if rn in regs and 0 <= regs[rn] - BASE < end and not regs[rn] & 1: work.append(regs[rn])
                delay = True
            elif op in (0x000b, 0x002b):  # rts / rte
                delay = stop = True
            elif op & 0xf0ff in (0x0023, 0x0003):  # braf / bsrf: GCC 'switch' jump table
                delay = True; stop = (op & 0xff) == 0x23
                t = regs.get('mova')
                if t is not None and 0 <= t - BASE < end:
                    lim = min(t + 512, end + BASE); k = t
                    while k < lim:
                        e = rdd(k); e = e - 0x10000 if e & 0x8000 else e
                        tg = pc + 4 + e
                        if tg & 1 or not (0 <= tg - BASE < end): break
                        lit[(k - BASE) >> 1] = True
                        work.append(tg)
                        if tg > t: lim = min(lim, tg)
                        k += 2
            elif n in (3, 4, 5, 6, 7, 0xe) or (n == 0 and (op & 0xf) in (2, 9, 0xa, 0xc, 0xd, 0xe)):
                regs.pop(rn, None)
            elif n in (0x8, 0xc):
                regs.pop(0, None)
            if delay:
                ds = pc + 2
                if 0 <= ds - BASE < end and not code[(ds - BASE) >> 1]:
                    dop = rd(ds)
                    if valid(dop): code[(ds - BASE) >> 1] = True
                nxt = pc + 4
            if stop: break
            # call: registers no longer reliable
            if n == 0xb or op & 0xf0ff == 0x400b: regs = {}
            pc = nxt
    return code, lit, mova, bad
