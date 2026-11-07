# Battery-free CPS3 BIOS: SH-2 code added to the sfiii3_euro BIOS.
#
# 1. At start-up (literal 0x490), after the original boot code, the header of
#    the game found in the SIMMs (default: entry 0 of the game table) is copied
#    to RAM (HDR) with its parameters (CUR).
# 2. Every read of the 0x1FEC0 header by the BIOS is redirected to HDR.
# 3. Before the BIOS copies the header to compare it:
#      - at start-up (sel_simm, call at 0x2ACC): the game is chosen from the ID
#        written at the end of SIMM 1 (0x067FFFE0);
#      - with a CD (sel_cd, call at 0x3328): the game is chosen from the CD ID.
#    The original BIOS then runs its usual checks with this header.
#    pre2 (state 2 of the BIOS state machine, table 0x18A20) also chooses the
#    game from the SIMMs before the SIMM presence test; after a choice made from
#    the CD, the table of files to read (state 3, 0x2B0E) is rebuilt.
# 4. While SIMM 1/2 are rewritten (loop at 0xB7BE), each word is converted with
#    the key and the code/data map of the chosen game.
# 5. State 11 (after "Rewrite the game"): region menu, then CD / No CD menu,
#    then check that the SIMMs the game needs are installed.
#
# Game table entry (ENTRY bytes):
#   +0x00 ID (12 bytes, zero-terminated; compared with the start of the CD /
#         SIMM ID, which tells CAP-33S-1 from CAP-33S-2)
#   +0x0C header (48 bytes, same format as 0x1FEC0 in the sfiii3 BIOS)
#   +0x3C key1, key2, map address, number of boundaries, map end, flags,
#         address of a patch list (0 = none), header copy address in SIMM,
#         Asia region code, "No CD" region code
#         (flag 1 = SIMMs written as is: CD already in dead-cart format)
#   Patch list: pairs (aligned 0x06xxxxxx address, final word), sorted,
#   terminated by 0.
HOOK_ADDR = 0x20100
HDR = 0x02038E00
CUR = HDR + 0x30
NPARAM = 10
ENTRY = 12 + 48 + 4 * NPARAM
IDLEN = 12
NCOPY = 12 + NPARAM            # words copied to HDR (header + parameters)
MENUVAR = CUR + 4 * NPARAM     # menus: page (1 region, 2 CD), choice, No CD, forced rewrite
MCOL, MROW = 8, 16             # menu position (column, text row)
REGIONS = ['Japan', 'Asia', 'Europe', 'USA', 'Hispanic', 'Brazil', 'Oceania']

def menu_tables(base):
    """Menu text tables (format of the BIOS print routine 0xF524: dx, dy, colour,
    0, string; '\\n' goes on to the next entry). Returns (bytes, title address,
    values address)."""
    import struct
    strs = bytearray(); ents = []
    def s_(t):
        a = base + 0x200 + len(strs); strs.extend(t.encode() + b'\0')
        while len(strs) % 4: strs.append(0)
        return a
    title = [(0, 0, 2, s_('Select the region  (Up/Down, Shot 1):\n')),
             (6, 2, 1, s_('                 '))]
    title2 = [(0, 0, 2, s_('Select the version (Up/Down, Shot 1):'))]
    vals = [(6, 2, 1, s_('< %-8s >    ' % r)) for r in REGIONS]
    vals2 = [(6, 2, 1, s_('< %-8s >    ' % r)) for r in ('CD', 'No CD')]
    out = bytearray()
    for dx, dy, col, a in title + title2 + vals + vals2:
        out += struct.pack('>HHHHI', dx, dy, col, 0, a)
    assert len(out) <= 0x200
    out = out.ljust(0x200, b'\0') + strs
    # title (region), title (version); values (region), values (version)
    return bytes(out), base, base + 12 * (len(title) + len(title2))

ASM = """
hook:
    sts.l pr,@-r15
    mov.l r9,@-r15
    mov.l r11,@-r15
    mov.l r12,@-r15
    mov.l r13,@-r15
    mov.l @r10,r8
    mov.l L0fff,r13
    and r14,r13
    mov.l Lcur,r0
    mov.l @(20,r0),r1
    tst r1,r1
    bf final
    mov r13,r4
    mov.l @(4,r0),r2
    mov.l @r0,r1
    bsr mask
    nop
    mov r5,r0
    shll16 r0
    or r0,r5
    xor r5,r8
    mov.l Lbase,r0
    mov r13,r9
    sub r0,r9
    shlr r9
    mov.l Lcur,r0
    mov.l @(12,r0),r12
    tst r12,r12
    bt final
    mov.l @(16,r0),r1
    cmp/hs r1,r9
    bt final
    mov.l @(8,r0),r11
    bsr cls
    nop
    mov.l r0,@-r15
    add #1,r9
    bsr cls
    nop
    mov.l @r15+,r1
    mov r0,r3
    or r1,r0
    tst r0,r0
    bt final
    mov.l r1,@-r15
    mov.l r3,@-r15
    mov r13,r4
    mov #0,r1
    mov #0,r2
    bsr mask
    nop
    mov.l @r15+,r3
    mov.l @r15+,r1
    mov #0,r0
    tst r3,r3
    bt nolo
    mov r5,r0
nolo:
    tst r1,r1
    bt nohi
    mov r5,r2
    shll16 r2
    or r2,r0
nohi:
    xor r0,r8
final:
    ; patches: final value written to the SIMM (sorted list, ends with 0)
    mov.l Lcur,r0
    mov.l @(24,r0),r1
    tst r1,r1
    bt nopatch
ploop:
    mov.l @r1+,r0
    tst r0,r0
    bt nopatch
    cmp/hi r13,r0
    bt nopatch
    cmp/eq r0,r13
    mov.l @r1+,r0
    bf ploop
    mov r0,r8
nopatch:
    ; copy of the BIOS header 0x1FEC0-0x1FEFF (64 bytes) at SIMM address
    ; CUR+28, with the chosen region (HDR+0xB) at 0x1FECB
    mov.l Lcur,r0
    mov.l @(28,r0),r1
    tst r1,r1
    bt done
    mov r13,r0
    sub r1,r0
    mov #68,r2
    cmp/hs r2,r0
    bt done
    ; word 64: mark of the BIOS that flashed (dead cart / standard SH-2)
    mov #64,r2
    cmp/eq r2,r0
    bf nomark
    mov.l Lmark,r8
    bra done
    nop
nomark:
    mov.l L1fec0,r1
    mov.l @(r0,r1),r8
    mov #12,r2
    cmp/eq r2,r0
    bf noncd
    ; 0x1FECC: bit 0 of the first byte = No CD (menu choice)
    mov.l Lfeff,r0
    and r0,r8
    mov.l Lnocd,r1
    mov.l @r1,r2
    shll8 r2
    shll16 r2
    or r2,r8
    bra done
    nop
noncd:
    mov #8,r2
    cmp/eq r2,r0
    bf done
    mov.l Lhdr,r1
    add #11,r1
    mov.b @r1,r2
    extu.b r2,r2
    mov.l Lff00,r0
    and r0,r8
    or r2,r8
done:
    mov.l r8,@r10
    mov.l L8080,r2
    and r8,r2
    mov.l @r15+,r13
    mov.l @r15+,r12
    mov.l @r15+,r11
    mov.l @r15+,r9
    lds.l @r15+,pr
    rts
    nop
cls:
    mov #0,r6
    mov r12,r7
clsl:
    cmp/hs r7,r6
    bt clse
    mov r6,r3
    add r7,r3
    shlr r3
    mov r3,r0
    shll2 r0
    mov.l @(r0,r11),r1
    cmp/hi r9,r1
    bt clsh
    mov r3,r6
    bra clsl
    add #1,r6
clsh:
    bra clsl
    mov r3,r7
clse:
    mov r6,r0
    rts
    and #1,r0
mask:
    sts.l pr,@-r15
    xor r1,r4
    mov.l Lffff,r6
    extu.w r4,r5
    xor r6,r5
    extu.w r2,r7
    bsr rot
    nop
    mov r4,r0
    shlr16 r0
    xor r6,r0
    xor r0,r5
    extu.w r5,r5
    mov r2,r7
    shlr16 r7
    bsr rot
    nop
    extu.w r4,r0
    xor r0,r5
    extu.w r2,r0
    xor r0,r5
    extu.w r5,r5
    lds.l @r15+,pr
    rts
    nop
rot:
    mov r5,r0
    shll2 r0
    mov r5,r1
    shlr8 r1
    shlr2 r1
    shlr2 r1
    shlr2 r1
    or r1,r0
    extu.w r0,r0
    mov r5,r3
    add r0,r3
    extu.w r3,r3
    mov r3,r0
    shll2 r0
    shll2 r0
    mov r3,r1
    shlr8 r1
    shlr2 r1
    shlr2 r1
    or r1,r0
    extu.w r0,r0
    mov r5,r1
    xor r7,r1
    and r3,r1
    xor r1,r0
    rts
    extu.w r0,r5
init:
    ; Start-up (after the original boot code, no stack yet): choose the game
    ; in the SIMMs (default: entry 0), then return through 0x498.
    mov.l Lsimmid,r5
    bsr find
    nop
    tst r4,r4
    bf initsel
    mov.l Lgames,r4
initsel:
    bsr select
    nop
    mov.l L498,r0
    jmp @r0
    nop
select:
    mov r4,r1
    add #12,r1
    mov.l Lhdr,r2
    mov #NCOPY,r3
sell:
    mov.l @r1+,r0
    mov.l r0,@r2
    add #4,r2
    dt r3
    bf sell
    ; region and No CD already chosen: read from the header copy in the SIMM
    ; if it is valid (first 8 bytes = those of 0x1FEC0)
    mov.l L1fec0,r3
    mov.l @(12,r3),r0
    shlr8 r0
    shlr16 r0
    mov.l Lnocd,r2
    mov #1,r1
    and r1,r0
    mov.l r0,@r2
    mov.l Lcur,r0
    mov.l @(28,r0),r1
    tst r1,r1
    bt selend
    mov.l @r1,r2
    mov.l @r3,r0
    cmp/eq r0,r2
    bf selend
    mov.l @(4,r1),r2
    mov.l @(4,r3),r0
    cmp/eq r0,r2
    bf selend
    mov.l @(12,r1),r0
    shlr8 r0
    shlr16 r0
    mov #1,r2
    and r2,r0
    mov.l Lnocd,r2
    mov.l r0,@r2
    mov.l @(8,r1),r2
    mov.l Lhdr,r3
    add #11,r3
    mov.b r2,@r3
selend:
    ; BIOS NOCD flag (HDR+0xC bit 0, read by BIOS state 0: no CD drive check)
    ; = No CD choice, except while P1 Start is held (to reach the CD again)
    mov.l Lnocd,r2
    mov.l @r2,r3
    mov.l Linputs,r1
    mov.l @r1,r1
    mov.l Lstart1,r2
    tst r2,r1
    bf selcd
    mov #0,r3
selcd:
    mov.l Lhdr,r1
    add #12,r1
    mov.b @r1,r0
    and #0xfe,r0
    or r3,r0
    mov.b r0,@r1
    rts
    nop
find:
    mov.l Lgames,r4
    mov.l Lngames,r6
fgame:
    mov r4,r1
    mov r5,r2
    mov #12,r3
fchar:
    mov.b @r1+,r0
    tst r0,r0
    bt ffound
    mov.b @r2+,r7
    cmp/eq r0,r7
    bf fnext
    dt r3
    bf fchar
ffound:
    rts
    nop
fnext:
    mov #ENTRY,r0
    add r0,r4
    dt r6
    bf fgame
    rts
    mov #0,r4
sel_simm:
    mov.l Lhdr,r0
    cmp/eq r0,r5
    bf tomemcpy
    sts.l pr,@-r15
    mov.l r4,@-r15
    mov.l r5,@-r15
    mov.l r6,@-r15
    mov.l Lsimmid,r5
    bra selcommon
    nop
sel_cd:
    mov.l Lsimmid,r0
    cmp/eq r0,r5
    bt simmid
    mov.l Lhdr,r0
    cmp/eq r0,r5
    bf tomemcpy
    mov.l Lforce,r0
    mov #0,r1
    mov.l r1,@r0
    sts.l pr,@-r15
    mov.l r4,@-r15
    mov.l r5,@-r15
    mov.l r6,@-r15
    mov.l Lcdptr,r5
    mov.l @r5,r5
    add #7,r5
    bsr find
    nop
    tst r4,r4
    bt nosel
    bsr select
    nop
    bsr chkforce
    nop
    mov.l Ltable,r0
    jsr @r0
    nop
    bra nosel
    nop
selcommon:
    bsr find
    nop
    tst r4,r4
    bt nosel
    bsr select
    nop
nosel:
    mov.l @r15+,r6
    mov.l @r15+,r5
    mov.l @r15+,r4
    lds.l @r15+,pr
tomemcpy:
    mov.l Lmemcpy,r0
    jmp @r0
    nop
; State 10, copy of the SIMM ID (0x067FFFE0), compared next with the CD ID:
; if the rewrite is forced, the copied ID is spoiled -> the BIOS offers
; "Rewrite the game".
simmid:
    mov.l Lforce,r0
    mov.l @r0,r0
    tst r0,r0
    bt tomemcpy
    sts.l pr,@-r15
    mov.l r4,@-r15
    mov.l Lmemcpy,r0
    jsr @r0
    nop
    mov.l @r15+,r4
    mov #0,r0
    mov.b r0,@r4
    lds.l @r15+,pr
    rts
    nop
; Rewrite forced if P1 Start is held, or if the header copy in the SIMMs was
; not written by this BIOS (SIMMs from a battery cart, or flashed by the other
; version: dead cart / standard SH-2).
chkforce:
    mov #1,r3
    mov.l Linputs,r1
    mov.l @r1,r0
    mov.l Lstart1,r2
    tst r2,r0
    bt cfend
    mov.l Lcur,r0
    mov.l @(28,r0),r1
    tst r1,r1
    bt cfok
    mov.l L1fec0,r2
    mov.l @r1,r0
    mov.l @r2,r7
    cmp/eq r0,r7
    bf cfend
    mov.l @(4,r1),r0
    mov.l @(4,r2),r7
    cmp/eq r0,r7
    bf cfend
    add #64,r1
    mov.l @r1,r0
    mov.l Lmark,r7
    cmp/eq r0,r7
    bf cfend
cfok:
    mov #0,r3
cfend:
    mov.l Lforce,r0
    rts
    mov.l r3,@r0
pre2:
    sts.l pr,@-r15
    mov.l r4,@-r15
    mov.l r5,@-r15
    mov.l r6,@-r15
    mov.l r7,@-r15
    mov.l Lsimmid,r5
    bsr find
    nop
    tst r4,r4
    bt pre2n
    bsr select
    nop
pre2n:
    mov.l @r15+,r7
    mov.l @r15+,r6
    mov.l @r15+,r5
    mov.l @r15+,r4
    lds.l @r15+,pr
    mov.l Lstate2,r0
    jmp @r0
    nop
.align
Lmark:
    .long MARK
Lforce:
    .long FORCEVAR
Linputs:
    .long 0x05000000
Lstart1:
    .long 0x10000000
Lcur:
    .long CUR
Lhdr:
    .long HDR
L0fff:
    .long 0x0fffffff
Lffff:
    .long 0x0000ffff
L8080:
    .long 0x80808080
Lbase:
    .long 0x06000000
Lgames:
    .long GAMES
Lngames:
    .long NGAMES
L498:
    .long 0x00000498
Lsimmid:
    .long 0x067fffe0
Lcdptr:
    .long 0x0201ef40
Lmemcpy:
    .long 0x00007750
Ltable:
    .long 0x00002b0e
Lstate2:
    .long 0x00002a36
L1fec0:
    .long 0x0001fec0
Lff00:
    .long 0xffffff00
Lfeff:
    .long 0xfeffffff
Lnocd:
    .long NOCDVAR
; ---------------------------------------------------------------------------
; BIOS state 11 (table 0x18A44, after the "Rewrite the game / Cancel" menu):
; if "Rewrite" (index 0x0201B140 = 0), region menu then CD / No CD menu before
; the rewrite. Up/down change, button 1 confirms -> HDR+0xB, state 5.
; Called every frame while the state is 11.
st11:
    mov.l Lidx,r0
    mov.l @r0,r0
    tst r0,r0
    bt st11go
    mov.l L3b0a,r0
    jmp @r0
    nop
st11go:
    sts.l pr,@-r15
    mov.l r8,@-r15
    mov.l r9,@-r15
    mov.l r10,@-r15
    mov.l Lmenu,r8
    mov.l @r8,r0
    tst r0,r0
    bf mrun
    ; first frame: erase the cursor, current choice, title
    mov.l Lmode,r0
    mov.b @r0,r0
    extu.b r0,r0
    mov.l Lcpos,r1
    mov.l @r1,r4
    mov.l @(4,r1),r5
    mov #1,r6
    mov #1,r2
    cmp/eq r2,r0
    bf curchr
    mov #1,r7
    mov.l Lcurspr,r0
    jsr @r0
    nop
    bra curok
    nop
curchr:
    add r5,r5
    mov #32,r7
    mov.l Lcurtxt,r0
    jsr @r0
    nop
curok:
    mov.l Lhdr2,r1
    add #11,r1
    mov.b @r1,r1
    extu.b r1,r1
    mov r1,r0
    add #-1,r0
    mov #7,r2
    cmp/hs r2,r0
    bf selidx
    mov #2,r0
    mov #8,r2
    cmp/eq r2,r1
    bf selidx
    mov #1,r0
selidx:
    mov.l r0,@(4,r8)
    mov #1,r0
    mov.l r0,@r8
    mov.l Ltitle,r7
    mov.l Lffff2,r6
    mov #MCOL,r4
    mov #MROW,r5
    mov.l Lprint,r0
    jsr @r0
    nop
    bra mdraw
    nop
mrun:
    mov #7,r10
    mov.l @r8,r0
    mov #1,r1
    cmp/eq r1,r0
    bt mrn
    mov #2,r10
mrn:
    mov.l Lin,r1
    mov.w @r1,r9
    extu.w r9,r9
    mov.l @(4,r8),r2
    mov #1,r1
    tst r1,r9
    bt notup
    tst r2,r2
    bf up1
    mov r10,r2
up1:
    add #-1,r2
    mov.l r2,@(4,r8)
    bra mdraw
    nop
notup:
    mov #2,r1
    tst r1,r9
    bt notdn
    add #1,r2
    cmp/eq r10,r2
    bf dn1
    mov #0,r2
dn1:
    mov.l r2,@(4,r8)
    bra mdraw
    nop
notdn:
    mov #16,r1
    tst r1,r9
    bt mend
    mov.l @r8,r0
    mov #1,r1
    cmp/eq r1,r0
    bt valreg
    ; version confirmed: No CD (1); for games whose No CD version is a region
    ; (CUR+36: Asia without CD), that region replaces the chosen one
    mov.l Lnocd2,r1
    mov.l r2,@r1
    tst r2,r2
    bt vgo
    mov.l Lcur2,r1
    mov.l @(36,r1),r0
    tst r0,r0
    bt vgo
    mov.l Lhdr2,r1
    add #11,r1
    mov.b r0,@r1
vgo:
    mov #0,r0
    mov.l r0,@r8
    ; SIMMs required by the header of the CD's game (like BIOS state 2,
    ; 0x2A8C): non-zero flag = SIMM present (0xA578), flag 1 = not a 32 Mbit
    ; SIMM. Otherwise screen 0 "not enough memory" and state 13.
    mov #0,r9
    mov.l Lhdr2,r10
    add #16,r10
schk:
    mov.b @r10,r0
    extu.b r0,r0
    tst r0,r0
    bt snext
    mov r9,r4
    mov.l Ldetect,r1
    jsr @r1
    nop
    tst r0,r0
    bt sfail
    mov r0,r2
    mov.b @r10,r0
    extu.b r0,r0
    mov #1,r1
    cmp/eq r1,r0
    bf snext
    mov.l Lm32,r1
    tst r1,r2
    bf sfail
snext:
    add #1,r9
    add #4,r10
    mov #8,r1
    cmp/hs r1,r9
    bf schk
    mov.l Lstate,r1
    mov #5,r0
    mov.l r0,@r1
    bra mend
    nop
sfail:
    mov #0,r4
    mov.l Ldraw,r0
    jsr @r0
    nop
    mov.l Lerrv,r1
    mov #-1,r0
    mov.l r0,@r1
    mov.l Lstate,r1
    mov #13,r0
    mov.l r0,@r1
    bra mend
    nop
valreg:
    ; region confirmed: region code (Asia: game-specific code, CUR+32)
    mov r2,r0
    add #1,r0
    mov #2,r1
    cmp/eq r1,r0
    bf setreg
    mov.l Lcur2,r1
    mov.l @(32,r1),r0
setreg:
    mov.l Lhdr2,r1
    add #11,r1
    mov.b r0,@r1
    ; page 2: CD / No CD version
    mov #2,r0
    mov.l r0,@r8
    mov.l Lnocd2,r1
    mov.l @r1,r0
    mov.l r0,@(4,r8)
    mov.l Ltitle,r7
    add #24,r7
    mov.l Lffff2,r6
    mov #MCOL,r4
    mov #MROW,r5
    mov.l Lprint,r0
    jsr @r0
    nop
mdraw:
    mov.l @(4,r8),r0
    shll2 r0
    mov r0,r1
    add r0,r0
    add r1,r0
    mov.l Lvals,r7
    add r0,r7
    mov.l @r8,r0
    mov #1,r1
    cmp/eq r1,r0
    bt mdr
    add #84,r7
mdr:
    mov.l Lffff2,r6
    mov #MCOL,r4
    mov #MROW,r5
    mov.l Lprint,r0
    jsr @r0
    nop
mend:
    mov.l @r15+,r10
    mov.l @r15+,r9
    mov.l @r15+,r8
    lds.l @r15+,pr
    rts
    nop
.align
Lidx:
    .long 0x0201b140
L3b0a:
    .long 0x00003b0a
Lmenu:
    .long MENUVAR
Lmode:
    .long 0x0201b12c
Lcpos:
    .long 0x0201b144
Lcurspr:
    .long 0x0001056c
Lcurtxt:
    .long 0x0000f446
Lhdr2:
    .long HDR
Lcur2:
    .long CUR
Ltitle:
    .long TITLE
Lvals:
    .long VALS
Lffff2:
    .long 0x0000ffff
Lprint:
    .long 0x0000f524
Lin:
    .long 0x020389ba
Lstate:
    .long 0x0201d2f4
Lnocd2:
    .long NOCDVAR
Ldetect:
    .long 0x0000a578
Lm32:
    .long 0x000000f0
Ldraw:
    .long 0x00002140
Lerrv:
    .long 0x0201b13c
"""

MARK_DEAD = 0x43505333   # 'CPS3'
MARK_SH2 = 0x53483220    # 'SH2 '

def source(games_addr, ngames, title=0, vals=0, sh2=False):
    return (ASM.replace('MARK', hex(MARK_SH2 if sh2 else MARK_DEAD)).replace('FORCEVAR', hex(MENUVAR + 12)).replace('ENTRY', str(ENTRY)).replace('NCOPY', str(NCOPY)).replace('NOCDVAR', hex(MENUVAR + 8)).replace('MENUVAR', hex(MENUVAR))
            .replace('MCOL', str(MCOL)).replace('MROW', str(MROW))
            .replace('TITLE', hex(title)).replace('VALS', hex(vals))
            .replace('CUR', hex(CUR)).replace('HDR', hex(HDR))
            .replace('NGAMES', str(ngames)).replace('GAMES', hex(games_addr)))
