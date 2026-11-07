#!/usr/bin/env python3
"""Reads the files of an original CPS3 CD image (ISO 9660), and extracts the
plain program (files 10 and 20 = SIMM 1 and 2) for the map tools.

The image is a .cue with its .bin (MODE1/2352, e.g. from
"chdman extractcd -i x.chd -o x.cue -ob x.bin") or with a 2048-byte-sector
.iso (cue line "FILE "x.iso" BINARY" / "TRACK 01 MODE1/2048").

Usage: cdimage.py image.cue key1 key2 out.bin
  key1/key2 in hex; 0 0 for 2nd Impact (CD already in dead-cart format).
Output: 16 MB, SIMM1 then SIMM2, big-endian 32-bit words, as seen by the CPU
of the original cart (CD data ^ game mask).
"""
import sys, os, re, struct
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cps3crypt as c

def bin_of(cue):
    """Data file named in the .cue (relative to the .cue)."""
    m = re.search(r'FILE\s+"([^"]+)"', open(cue).read())
    return os.path.join(os.path.dirname(os.path.abspath(cue)), m.group(1))

def iso_files(binp, cue):
    raw = 'MODE1/2352' in open(cue).read()
    sec, off = (2352, 16) if raw else (2048, 0)
    f = open(binp, 'rb')
    def sector(n):
        f.seek(n * sec + off); return f.read(2048)
    def read(lba, size):
        return b''.join(sector(lba + i) for i in range((size + 2047) // 2048))[:size]
    pvd = sector(16)
    assert pvd[1:6] == b'CD001'
    root = pvd[156:190]
    files = {}
    def walk(lba, size, path):
        data = read(lba, size); i = 0
        while i < len(data):
            l = data[i]
            if l == 0:
                i = (i // 2048 + 1) * 2048; continue
            rec = data[i:i + l]
            ext = struct.unpack('<I', rec[2:6])[0]; sz = struct.unpack('<I', rec[10:14])[0]
            name = rec[33:33 + rec[32]]
            if name not in (b'\x00', b'\x01'):
                nm = name.decode(errors='replace').split(';')[0]
                if rec[25] & 2: walk(ext, sz, path + nm + '/')
                else: files[path + nm] = (ext, sz)
            i += l
    walk(struct.unpack('<I', root[2:6])[0], struct.unpack('<I', root[10:14])[0], '')
    return pvd[40:72].decode(errors='replace').strip(), files, read

if __name__ == '__main__':
    cue, k1, k2, out = sys.argv[1], int(sys.argv[2], 16), int(sys.argv[3], 16), sys.argv[4]
    vol, files, read = iso_files(bin_of(cue), cue)
    prog = np.full(0x400000, 0xffffffff, np.uint32)
    for n, name in enumerate(('10', '20')):
        if name in files:
            lba, sz = files[name]
            w = np.frombuffer(read(lba, sz), '>u4').astype(np.uint32)
            prog[n * 0x200000:n * 0x200000 + len(w)] = w
    prog ^= c.mask_array(0x06000000, 0x1000000, k1, k2) if (k1 or k2) else np.uint32(0)
    open(out, 'wb').write(prog.astype('>u4').tobytes())
    print(vol, sorted(files), '->', out)
