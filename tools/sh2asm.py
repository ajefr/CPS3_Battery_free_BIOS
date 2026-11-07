# Minimal SH-2 assembler (the subset used by the CPS3 BIOS patches).
import re, struct

def R(s):
    s = s.strip().lower()
    assert s[0] == 'r', s
    return int(s[1:])

def assemble(src, base):
    """src: asm text; base: load address. Returns (bytes, labels)."""
    lines = []
    for raw in src.splitlines():
        line = raw.split(';')[0].strip()
        if not line:
            continue
        lines.append(line)
    # pass 1: label addresses
    labels, pc = {}, base
    for l in lines:
        if l.endswith(':'):
            labels[l[:-1]] = pc
        elif l.startswith('.align'):
            pc = (pc + 3) & ~3
        elif l.startswith('.long'):
            pc += 4
        else:
            pc += 2
    out, pc = bytearray(), base

    def emit16(v):
        out.extend(struct.pack('>H', v & 0xffff))

    for l in lines:
        if l.endswith(':'):
            continue
        if l.startswith('.align'):
            while pc & 3:
                emit16(0x0009); pc += 2
            continue
        if l.startswith('.long'):
            v = l.split(None, 1)[1].strip()
            out.extend(struct.pack('>I', (labels[v] if v in labels else int(v, 0)) & 0xffffffff)); pc += 4
            continue
        m = l.split(None, 1)
        op, args = m[0].lower(), (m[1] if len(m) > 1 else '')
        a = [x.strip() for x in args.split(',')] if args else []
        if op == 'nop': emit16(0x0009)
        elif op == 'rts': emit16(0x000b)
        elif op == 'sts.l' and a == ['pr', '@-r15']: emit16(0x4f22)
        elif op == 'lds.l' and a == ['@r15+', 'pr']: emit16(0x4f26)
        elif op == 'jsr': emit16(0x400b | R(a[0][1:]) << 8)
        elif op == 'bsr':
            d = (labels[a[0]] - (pc + 4)) // 2
            assert -2048 <= d < 2048; emit16(0xb000 | (d & 0xfff))
        elif op in ('bt', 'bf'):
            d = (labels[a[0]] - (pc + 4)) // 2
            assert -128 <= d < 128; emit16((0x8900 if op == 'bt' else 0x8b00) | (d & 0xff))
        elif op == 'mov.l' and a[0] in labels:          # mov.l label,rn (PC-relative pool)
            t = labels[a[0]]; d = (t - ((pc & ~3) + 4)) // 4
            assert t % 4 == 0 and 0 <= d < 256, (l, hex(t)); emit16(0xd000 | R(a[1]) << 8 | d)
        elif op == 'mov.l' and a[1].startswith('@-r'):              # push
            emit16(0x2006 | R(a[1][2:]) << 8 | R(a[0]) << 4)
        elif op == 'mov.b' and a[0].startswith('@r') and a[0].endswith('+'):
            emit16(0x6004 | R(a[1]) << 8 | R(a[0][1:-1]) << 4)
        elif op == 'mov.b' and a[0].startswith('@r'):               # mov.b @rm,rn
            emit16(0x6000 | R(a[1]) << 8 | R(a[0][1:]) << 4)
        elif op == 'mov.b' and a[1].startswith('@r'):               # mov.b rm,@rn
            emit16(0x2000 | R(a[1][1:]) << 8 | R(a[0]) << 4)
        elif op == 'extu.b': emit16(0x600c | R(a[1]) << 8 | R(a[0]) << 4)
        elif op == 'mov.l' and a[0].startswith('@(') and not a[0].lower().startswith('@(r0'):   # mov.l @(disp,rm),rn
            disp = int(a[0][2:], 0); rm = R(a[1].rstrip(')'))
            assert disp % 4 == 0 and 0 <= disp < 64; emit16(0x5000 | R(a[2]) << 8 | rm << 4 | disp // 4)
        elif op == 'dt': emit16(0x4010 | R(a[0]) << 8)
        elif op == 'jmp': emit16(0x402b | R(a[0][1:]) << 8)
        elif op == 'mov.l' and a[0].startswith('@r') and a[0].endswith('+'):   # pop
            emit16(0x6006 | R(a[1]) << 8 | R(a[0][1:-1]) << 4)
        elif op == 'mov.l' and a[0].lower().startswith('@(r0'):     # mov.l @(r0,rm),rn
            emit16(0x000e | R(a[2]) << 8 | R(a[1].rstrip(')')) << 4)
        elif op == 'mov.l' and a[0].startswith('@r') and not a[0].endswith('+'):
            emit16(0x6002 | R(a[1]) << 8 | R(a[0][1:]) << 4)
        elif op == 'mov.l' and a[1].startswith('@r'):
            emit16(0x2002 | R(a[1][1:]) << 8 | R(a[0]) << 4)
        elif op == 'mov.l' and a[1].startswith('@('):              # mov.l rm,@(disp,rn)
            disp = int(a[1][2:], 0); rn = R(a[2].rstrip(')'))
            assert disp % 4 == 0 and 0 <= disp < 64; emit16(0x1000 | rn << 8 | R(a[0]) << 4 | disp // 4)
        elif op == 'mov.w' and a[0].startswith('@r') and not a[0].endswith('+'):   # mov.w @rm,rn
            emit16(0x6001 | R(a[1]) << 8 | R(a[0][1:]) << 4)
        elif op == 'mov' and a[0].startswith('#'):
            v = int(a[0][1:], 0); assert -128 <= v < 128; emit16(0xe000 | R(a[1]) << 8 | (v & 0xff))
        elif op == 'mov': emit16(0x6003 | R(a[1]) << 8 | R(a[0]) << 4)
        elif op == 'bra':
            d = (labels[a[0]] - (pc + 4)) // 2
            assert -2048 <= d < 2048; emit16(0xa000 | (d & 0xfff))
        elif op == 'sub': emit16(0x3008 | R(a[1]) << 8 | R(a[0]) << 4)
        elif op in ('cmp/hs', 'cmp/hi', 'cmp/eq'):
            code = {'cmp/eq': 0, 'cmp/hs': 2, 'cmp/hi': 6}[op]
            emit16(0x3000 | R(a[1]) << 8 | R(a[0]) << 4 | code)
        elif op == 'shlr': emit16(0x4001 | R(a[0]) << 8)
        elif op == 'and' and a[0].startswith('#'):
            assert a[1] == 'r0'; emit16(0xc900 | (int(a[0][1:], 0) & 0xff))
        elif op == 'add' and a[0].startswith('#'):
            v = int(a[0][1:], 0); assert -128 <= v < 128; emit16(0x7000 | R(a[1]) << 8 | (v & 0xff))
        elif op == 'extu.w': emit16(0x600d | R(a[1]) << 8 | R(a[0]) << 4)
        elif op in ('and', 'xor', 'or', 'tst'):
            code = {'and': 9, 'xor': 0xa, 'or': 0xb, 'tst': 8}[op]
            emit16(0x2000 | R(a[1]) << 8 | R(a[0]) << 4 | code)
        elif op == 'add': emit16(0x300c | R(a[1]) << 8 | R(a[0]) << 4)
        elif op in ('shll2', 'shlr2', 'shll8', 'shlr8', 'shll16', 'shlr16'):
            code = {'shll2': 0x08, 'shlr2': 0x09, 'shll8': 0x18, 'shlr8': 0x19, 'shll16': 0x28, 'shlr16': 0x29}[op]
            emit16(0x4000 | R(a[0]) << 8 | code)
        else:
            raise ValueError('unsupported instruction: ' + l)
        pc += 2
    return bytes(out), labels
