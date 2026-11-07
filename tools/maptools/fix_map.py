#!/usr/bin/env python3
"""Corrects a map with a MAME coverage log (coverage.lua): executed half-words
become code, half-words read as data become data (unless also executed).
Usage: fix_map.py map.npz log out.npz
  log = prefix of the files log.code / log.data (several prefixes may be given,
  comma-separated)."""
import sys, numpy as np
B = 0x06000000

def load(f, n):
    a = np.array([int(x, 16) for x in open(f)], dtype=np.int64)
    a = (a - B) // 2
    a = a[(a >= 0) & (a < n - 1)]
    return a

z = np.load(sys.argv[1]); m = np.unpackbits(z['bits'])[:int(z['n'])].astype(bool); n = len(m)
ex = np.zeros(n, bool); rd = np.zeros(n, bool)
for p in sys.argv[2].split(','):
    ex[load(p + '.code', n)] = True
    rd[load(p + '.data', n)] = True
a = int((ex & ~m).sum()); b = int((rd & ~ex & m).sum()); c = int((rd & ex).sum())
m |= ex
m &= ~(rd & ~ex)
np.savez_compressed(sys.argv[3], bits=np.packbits(m), n=np.array(n))
print('code added %d, data removed from code %d, read AND executed %d (left as code)' % (a, b, c))
