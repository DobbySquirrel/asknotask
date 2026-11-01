"""Offline training of the listwise scorer and online comparison with the
verbal scorer (7.16 in x 3.5 in).

Two swim lanes; flow is left to right and only downward between lanes.
Charts are schematic (no ticks, no values).  The only numbers are the
illustrative verbal scores in online panel (a).
"""

import math

from figlib import Canvas

BLUE = "#0072B2"
BLUE_L = "#56B4E9"
ORANGE = "#E69F00"
GRAY = "#BBBBBB"
MID = "#8C8C8C"
BG = "#F4F4F4"
INK = "#333333"
WHITE = "#FFFFFF"

W_IN, H_IN = 7.16, 3.5
W, H = W_IN * 72, H_IN * 72
SW = 0.7
R = 3
FS = 6.0
THICK = 1.8

c = Canvas(W, H, stroke=SW, ink=INK)
T = c.text


def box(x, y, w, h, fill=WHITE, stroke=INK, rx=R, sw=None, dash=None):
    c.rect(x, y, w, h, rx=rx, fill=fill, stroke=stroke, sw=sw, dash=dash)


def centered(cx, cy, rows, size=FS, lead=None, **kw):
    lead = lead or size * 1.17
    y0 = cy - (len(rows) - 1) * lead / 2 + 0.35 * size
    for j, r_ in enumerate(rows):
        T(cx, y0 + j * lead, r_, size, "middle", **kw)


def label_box(x, y, w, h, rows, fill=WHITE, stroke=INK, size=FS, sw=None, lead=None, **kw):
    box(x, y, w, h, fill=fill, stroke=stroke, sw=sw)
    for r_ in rows:
        if c.tw(r_, size, kw.get("bold", False)) > w - 3:
            c.warn.append(f"overflow in box {w:.1f}: {r_!r}")
    centered(x + w / 2, y + h / 2, rows, size, lead, **kw)


def harrow(x0, x1, y, color=INK):
    c.arrow([(x0, y), (x1, y)], color, SW, hs=2.8)


def card_icon(x, y, w=11, h=8, color=BLUE_L, sw=0.55):
    c.rect(x, y, w, h, rx=1.2, fill=WHITE, stroke=INK, sw=sw)
    hh = h * 0.31
    c.path(f"M{x},{y + hh} V{y + 1.2} Q{x},{y} {x + 1.2},{y} H{x + w - 1.2} "
           f"Q{x + w},{y} {x + w},{y + 1.2} V{y + hh} Z", INK, sw, fill=color)
    for k in (0, 1):
        yy = y + hh + (h - hh) * (0.35 + 0.33 * k)
        c.line([(x + w * 0.16, yy), (x + w * (0.8 - 0.22 * k), yy)], INK, 0.4)


def fan(cx, top):
    for k, rot in enumerate((-10, -3, 5)):
        c.items.append(f'<g transform="rotate({rot} {cx} {top + 9})">')
        card_icon(cx - 5.5 + k * 0.6, top + k * 1.4)
        c.items.append("</g>")


def lock(cx, cy, color=INK):
    c.path(f"M{cx - 1.6},{cy - 0.6} V{cy - 2.2} A1.6,1.6 0 0 1 {cx + 1.6},{cy - 2.2} V{cy - 0.6}",
           color, 0.65)
    c.rect(cx - 2.4, cy - 0.8, 4.8, 3.6, rx=0.6, fill=color)


def cycle_icon(cx, cy, r=3.2, color=BLUE):
    c.path(f"M{cx + r},{cy} A{r},{r} 0 1 1 {cx},{cy - r}", color, 0.75)
    c.polygon([(cx - 0.4, cy - r - 1.8), (cx + 2.3, cy - r), (cx - 0.4, cy - r + 1.8)], color)


def star(cx, cy, ro=4.4, ri=1.85, fill=BLUE):
    pts = []
    for k in range(10):
        a = -math.pi / 2 + k * math.pi / 5
        rr = ro if k % 2 == 0 else ri
        pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
    c.polygon(pts, fill)


def pill(x, cy, label, stroke, text_color, fill=WHITE, size=FS, h=9.0, bold=False):
    w = c.tw(label, size, bold) + 7
    box(x, cy - h / 2, w, h, fill=fill, stroke=stroke, rx=h / 2)
    T(x + 3.5, cy + 0.35 * size, label, size, bold=bold, color=text_color)
    return w


def target(x, y, cells, color):
    cw = 8.5
    for j, v in enumerate(cells):
        filled = color == GRAY or j == 0
        c.rect(x + j * cw, y, cw, 7.2, rx=1, fill=color if filled else WHITE, stroke=color, sw=0.7)
        T(x + j * cw + cw / 2, y + 5.5, v, FS, "middle", bold=True)


# ====================================================================== lanes
M = 3.0
L1Y0, L1Y1 = M, 131.0
L2Y0, L2Y1 = 135.0, H - M
box(M, L1Y0, W - 2 * M, L1Y1 - L1Y0, fill=BG, stroke=None)
box(M, L2Y0, W - 2 * M, L2Y1 - L2Y0, fill=WHITE, stroke=GRAY, sw=0.6)
T(M + 5, L1Y0 + 9.5, "Offline · training databases", 8, bold=True)
T(M + 5, L2Y0 + 9.5, "Online · any question", 8, bold=True)

# ====================================================================== top lane
CH_X0, CH_X1 = 370.0, W - M - 4          # validation chart box (right third)
COLS = [(97.0, 47.0), (150.0, 30.0), (186.0, 74.0), (265.0, 40.0), (311.0, 53.0)]
R1Y, R1H = 19.5, 45.0
R2Y, R2H = 79.0, 45.0
r1m, r2m = R1Y + R1H / 2, R2Y + R2H / 2
BAND_Y = (R1Y + R1H + R2Y) / 2


def cx(k):
    return COLS[k][0] + COLS[k][1] / 2


def right(k):
    return COLS[k][0] + COLS[k][1]


# source + fork
SRC_CX = 28.0
for k in range(3):
    c.cylinder(SRC_CX - 13 + k * 3.2, 38 + k * 4.5, 16, 15)
CYL_BOT = 38 + 2 * 4.5 + 15
centered(SRC_CX, 82, ["Training", "databases"], 6.5, 7.4, bold=True)
centered(SRC_CX, 100, ["disjoint from", "all benchmarks"], FS, 6.8, italic=True,
         color=INK)
FKX = 57.0
c.line([(SRC_CX + 3, CYL_BOT - 0.5), (SRC_CX + 3, BAND_Y), (FKX, BAND_Y)], INK, SW)
c.line([(FKX, r1m), (FKX, r2m)], INK, SW)
c.circle(FKX, BAND_Y, 1.3, fill=INK)
harrow(FKX, COLS[0][0], r1m)
harrow(FKX, COLS[0][0], r2m)
T(FKX + 2.5, r1m - 2.2, "train split", FS)
T(FKX + 2.5, r2m - 2.2, "validation", FS)
T(FKX + 3, BAND_Y + 2.2, "/{split by database}", FS)

DET1 = ["Detection", "+ existence &", "difference"]
DET2 = ["Detection", "+ all three", "checks"]

# ---- upper row: training
x, w = COLS[0]
label_box(x, R1Y + 2.5, w, R1H - 5, DET1, lead=6.6)
harrow(right(0), COLS[1][0], r1m)
fan(cx(1), r1m - 12.5)
T(cx(1), r1m + 13.5, "ambiguities $φ$", FS, "middle")
harrow(right(1), COLS[2][0], r1m)

x, w = COLS[2]
box(x, R1Y, w, R1H, fill=ORANGE, stroke=ORANGE)
T(x + 4, R1Y + 15, "Simulated user", 6.5, bold=True)
for j, s in enumerate(["picks the option", "matching the gold", "query, or Others"]):
    T(x + 4, R1Y + 23.5 + j * 6.8, s, FS, maxw=w - 6)
tgl = "only step with gold SQL"
tgw = c.tw(tgl, FS) + 15
tgx = x + w / 2 - tgw / 2
box(tgx, R1Y - 4.6, tgw, 9.6, fill=WHITE, stroke=INK, rx=4.8)
lock(tgx + 5.6, R1Y + 0.5)
T(tgx + 10, R1Y + 2.3, tgl, FS)
harrow(right(2), COLS[3][0], r1m)

x, w = COLS[3]
tx0 = x + 1
target(tx0, R1Y + 1.5, ["1", "0"], ORANGE)
T(tx0, R1Y + 15, "option chosen", FS, maxw=w - 1)
T(tx0, R1Y + 21.4, "→ one-hot", FS)
target(tx0, R1Y + 25.5, ["½", "½"], GRAY)
T(tx0, R1Y + 39, "Others →", FS)
T(tx0, R1Y + 45.4, "uniform", FS)
harrow(right(3), COLS[4][0], r1m)

x, w = COLS[4]
TRAIN_CX = cx(4)
box(x, R1Y, w, R1H, stroke=BLUE, sw=1.1)
centered(TRAIN_CX, R1Y + 9.5, ["Train", "scorer"], 6.5, 7.2, bold=True, color=BLUE)
T(TRAIN_CX, R1Y + 27.5, "$L$ = − $Σ_{j}$ $q_{j}$ log $w_{j}$", 6.5, "middle", maxw=w - 3)
T(TRAIN_CX, R1Y + 35.5, "options permuted", FS, "middle", maxw=w - 3)
ew = c.tw("each epoch", FS)
T(TRAIN_CX + 4.5, R1Y + 41.8, "each epoch", FS, "middle")
cycle_icon(TRAIN_CX + 4.5 - ew / 2 - 4.5, R1Y + 39.9, r=2.6)

# ---- lower row: threshold selection
x, w = COLS[0]
label_box(x, R2Y + 4, w, R2H - 8, DET2, lead=6.9)
harrow(right(0), COLS[1][0] - 2, r2m)
x, w = COLS[1]
label_box(x - 2, R2Y + 4, w + 4, R2H - 8, ["ambiguities", "+ simulated", "user", "choices"], lead=6.9)
SC_X0, SC_X1 = COLS[2][0], right(4)
harrow(right(1) + 2, SC_X0, r2m)

# hand-off 1 (trained JEV): straight down through the scoring box
JEV_TOP = 166.0
c.line([(TRAIN_CX, R1Y + R1H), (TRAIN_CX, JEV_TOP - 6)], INK, THICK)
c.polygon([(TRAIN_CX, JEV_TOP), (TRAIN_CX - 2.7, JEV_TOP - 6.3), (TRAIN_CX + 2.7, JEV_TOP - 6.3)],
          INK)
T(TRAIN_CX - 4, BAND_Y + 2.3, "trained scorer", 6.5, "end", bold=True)

SC_Y, SC_H = R2Y + 7, R2H - 14
box(SC_X0, SC_Y, SC_X1 - SC_X0, SC_H, stroke=BLUE, sw=1.1)
scx = (SC_X0 + TRAIN_CX - 6) / 2
T(scx, SC_Y + 11.5, "Apply trained scorer", 6.5, "middle", bold=True, color=BLUE)
T(scx, SC_Y + 21.5, "per ambiguity: $H_{norm}(φ)$, top option", FS, "middle")
harrow(SC_X1, CH_X0, r2m)

# ---- validation chart (visual focus of the top lane)
CY0, CY1 = R1Y - 3, L1Y1 - 4
box(CH_X0, CY0, CH_X1 - CH_X0, CY1 - CY0, stroke=BLUE, sw=1.1)
chm = (CH_X0 + CH_X1) / 2
T(chm, CY0 + 9.5, "Select θ* on the validation split", 7, "middle", bold=True, maxw=CH_X1 - CH_X0 - 4)
T(chm, CY0 + 17, "/{never tuned on benchmark data}", FS, "middle", color=MID)
AX0, AY0, AX1, AY1 = CH_X0 + 9, CY0 + 23, CH_X1 - 13, CY0 + 71
c.arrow([(AX0, AY1), (AX0, AY0)], INK, 0.65, hs=2.6)
c.arrow([(AX0, AY1), (AX1 + 3, AY1)], INK, 0.65, hs=2.6)
T(AX0 + 3, AY0 + 2.5, "agreement", FS)
T(AX1 + 5, AY1 + 2.3, "$θ$", 7.5)
T(AX0, AY1 + 7.5, "← fewer automatic", FS, color=MID)
T(AX1 + 3, AY1 + 7.5, "more →", FS, "end", color=MID)
p0, p1, p2, p3 = (AX0 + 3, AY0 + 9), (AX0 + 62, AY0 + 6), (AX0 + 70, AY1 - 3), (AX1 - 1, AY1 - 4)


def bez(t):
    u = 1 - t
    return tuple(u ** 3 * a + 3 * u * u * t * b + 3 * u * t * t * q + t ** 3 * d
                 for a, b, q, d in zip(p0, p1, p2, p3))


ALY = AY0 + 22
c.line([(AX0, ALY), (AX1, ALY)], INK, 0.65, dash="2,1.4", cap="butt")
T(AX1 + 2.5, ALY + 2.5, "$α$", 7.5)
c.path(f"M{p0[0]:.2f},{p0[1]:.2f} C{p1[0]:.2f},{p1[1]:.2f} {p2[0]:.2f},{p2[1]:.2f} "
       f"{p3[0]:.2f},{p3[1]:.2f}", BLUE, 1.2)
lo, hi = 0.0, 1.0
for _ in range(50):
    mid = (lo + hi) / 2
    lo, hi = (mid, hi) if bez(mid)[1] < ALY else (lo, mid)
ix, iy = bez(lo)
c.line([(ix, iy), (ix, AY1)], BLUE, 0.6)
star(ix, iy)
slw = c.tw("selected here", 6.5, True)
T(ix - 3, ALY + 10, "selected here", 6.5, "end", bold=True)
T(ix - 3 - slw - 1.5, ALY + 10, "$θ^{*}$", 7, "end", bold=True)
T(chm, AY1 + 17, "`θ* = max { θ : agreement(θ) ≥ α }`", FS, "middle", maxw=CH_X1 - CH_X0 - 4)
T(chm, AY1 + 25, "/{agreement: top option = user's choice}", FS, "middle", color=MID)

# ====================================================================== bottom lane
DIV_X = M + (W - 2 * M) * 0.36
c.line([(DIV_X, L2Y0 + 4), (DIV_X, L2Y1 - 50)], MID, 0.6, dash="2.5,1.8", cap="butt")
PT_Y = L2Y0 + 19.5
T(M + 5, PT_Y, "(a) Verbal scores", 7, bold=True, color=MID)
RX0 = DIV_X + 6
T(RX0, PT_Y, "(b) Our scorer", 7, bold=True, color=BLUE)
MR0, MR1 = PT_Y + 5, PT_Y + 43
mm = (MR0 + MR1) / 2

# ---- (a) training-free (gray)
AX = M + 6
pw = c.tw("`Rate how likely each option`", FS) + 8
box(AX, MR0 + 2, pw, MR1 - MR0 - 4, stroke=GRAY)
c.path(f"M{AX},{MR0 + 10} V{MR0 + 2 + R} Q{AX},{MR0 + 2} {AX + R},{MR0 + 2} H{AX + pw - R} "
       f"Q{AX + pw},{MR0 + 2} {AX + pw},{MR0 + 2 + R} V{MR0 + 10} Z", GRAY, SW, fill=BG)
T(AX + 3.5, MR0 + 8.3, "Prompt (abridged)", FS, color=MID)
for j, s in enumerate(["Rate how likely each option", "is intended (0–1).", "A. <d₁>   B. <d₂>"]):
    T(AX + 4, MR0 + 17 + j * 6.5, f"`{s}`", FS, color=MID)
OX0 = AX + pw + 9
OX1 = DIV_X - 6
harrow(AX + pw, OX0, mm + 2, MID)
T((OX0 + OX1) / 2, mm - 6, "verbal scores", FS, "middle", color=MID)
box(OX0, mm - 2.5, OX1 - OX0, 10, fill=BG, stroke=GRAY)
T((OX0 + OX1) / 2, mm + 4.6, "A: 0.95    B: 0.05", 6.5, "middle", italic=True, color=MID,
  maxw=OX1 - OX0 - 3)


# ---- weakness (a) -> remedy (b): one row of three cards across the lane
def pict_coarse(x, y):
    heights = [0.6, 0.4, 10, 0.4, 0.5, 0.4, 0.6, 0.4, 7.5, 0.5]
    for k, hgt in enumerate(heights):
        c.rect(x + 2 + k * 4.2, y + 5 - hgt, 3.2, max(hgt, 0.6), rx=0,
               fill=MID if hgt > 2 else GRAY)
    c.line([(x, y + 5.3), (x + 46, y + 5.3)], MID, 0.5)


def pict_position(x, y):
    for k, (a_, b_) in enumerate((("d₁", "d₂"), ("d₂", "d₁"))):
        lx = x + 1 + k * 33
        c.rect(lx, y - 7, 28, 6.6, rx=1, fill=GRAY, stroke=None)
        T(lx + 1.5, y - 1.8, f"`A. <{a_}>`", FS, color=INK)
        T(lx + 1.5, y + 4.8, f"`B. <{b_}>`", FS, color=MID)
    c.rect(x, y - 8, 62, 14.5, rx=2, fill="none", stroke=GRAY, sw=0.5)


def pict_overconf(x, y):
    for k, hgt in enumerate((10.5, 1.2)):
        c.rect(x + 2 + k * 6, y + 5 - hgt, 4.6, hgt, rx=0, fill=MID if k == 0 else GRAY)
    c.line([(x, y + 5.3), (x + 15, y + 5.3)], MID, 0.5)
    pill(x + 18, y + 0.5, "no option fits", GRAY, MID, fill=BG)


weak = [("coarse", pict_coarse), ("position-sensitive", pict_position),
        ("overconfident", pict_overconf)]
remedy = [["continuous softmax", "over logits"], ["options permuted", "during training"],
          ["uniform target", "for Others"]]
ST_Y0, ST_Y1 = L2Y1 - 40, L2Y1 - 4
ST_X0, ST_X1 = M + 5, W - M - 4
T(ST_X0, ST_Y0 - 3.2, "/{weakness of (a)}  ⋯→  /{remedy in (b)}", FS, color=MID)
CG = 6.0
CWD = (ST_X1 - ST_X0 - 2 * CG) / 3
for k, ((wl, pict), rl) in enumerate(zip(weak, remedy)):
    x0 = ST_X0 + k * (CWD + CG)
    box(x0, ST_Y0, CWD, ST_Y1 - ST_Y0, stroke=GRAY, sw=0.6)
    lw_ = 64.0
    tw_ = max(c.tw(r_, FS) for r_ in rl) + 8
    gx = x0 + (CWD - (lw_ + 22 + tw_)) / 2
    pict(gx, ST_Y0 + 12)
    T(gx, ST_Y0 + 29.5, wl, 6.5, bold=True, color=MID)
    tx = gx + lw_ + 22
    ty = (ST_Y0 + ST_Y1) / 2
    box(tx, ty - 9, tw_, 18, stroke=BLUE, sw=0.9, rx=4)
    centered(tx + tw_ / 2, ty, rl, FS, 6.8, color=BLUE)
    c.arrow([(gx + lw_ + 4, ty), (tx - 1.5, ty)], MID, 0.7, dash="0.1,1.7", hs=2.8)

# ---- (b) JEV (blue)
CD = RX0 + 1.5
card_icon(CD, mm - 11, 19, 14, sw=SW)
centered(CD + 9.5, mm + 11, ["ambiguity $φ$", "= ⟨$h$, $P$⟩"], FS, 7)
PX0 = CD + 24
JW = 28.0
JX0 = TRAIN_CX - JW / 2
PX1 = JX0 - 7
harrow(CD + 19, PX0, mm - 4)
box(PX0, MR0, PX1 - PX0, MR1 - MR0)
c.path(f"M{PX0},{MR0 + 8.5} V{MR0 + R} Q{PX0},{MR0} {PX0 + R},{MR0} H{PX1 - R} Q{PX1},{MR0} "
       f"{PX1},{MR0 + R} V{MR0 + 8.5} Z", INK, SW, fill=BG)
T(PX0 + 2.5, MR0 + 6.4, "All options in one prompt (abridged)", FS, maxw=PX1 - PX0 - 3)
for j, s in enumerate(["Question: ...", "Evidence: ...", "Span h: '...'"]):
    T(PX0 + 3, MR0 + 15.5 + j * 6.4, f"`{s}`", FS)
pc2 = PX0 + 57
for j, s in enumerate(["Options:", "A. <d₁>", "B. <d₂>", "Answer:"]):
    T(pc2, MR0 + 15.5 + j * 6.4, f"`{s}`", FS)
if c.tw("`Span h: '...'`", FS) + PX0 + 4 > pc2:
    c.warn.append("prompt columns collide")

harrow(PX1, JX0, mm)
label_box(JX0, JEV_TOP, JW, (mm - JEV_TOP) * 2, ["Trained", "scorer"], stroke=BLUE, sw=1.1, size=6.0, bold=True,
          color=BLUE)

GAP = 5.5
SX0 = JX0 + JW + GAP
cell, ncell, ia, ib = 3.3, 8, 2, 5
SX1 = SX0 + ncell * cell
harrow(JX0 + JW, SX0, mm)
for k in range(ncell):
    on = k in (ia, ib)
    c.rect(SX0 + k * cell, mm - 2.5, cell, 5, rx=0, fill=BLUE if on else WHITE,
           stroke=BLUE if on else GRAY, sw=0.35)
for k, ch in ((ia, "A"), (ib, "B")):
    T(SX0 + (k + 0.5) * cell, mm - 4.3, ch, FS, "middle", bold=True, color=BLUE)
centered((SX0 + SX1) / 2, mm + 9.5, ["option-letter", "logits"], FS, 6.6, italic=True)

SMX, SMW = SX1 + GAP, 25.0
harrow(SX1, SMX, mm)
label_box(SMX, mm - 9, SMW, 18, ["softmax", "→ $w$"])

DW, DHH = 46.0, 16.0
DCX = W - M - 4 - DW / 2
HX = SMX + SMW + GAP
HX1 = DCX - DW / 2 - GAP
harrow(SMX + SMW, HX, mm)
box(HX, mm - 13, HX1 - HX, 26)
for j, s in enumerate(["$H_{norm}(φ)$ =", "−$Σ_{j}$ $w_{j}$ log $w_{j}$", "/ log |$P$|"]):
    T((HX + HX1) / 2, mm - 5.2 + j * 7.4, s, 6.2, "middle", maxw=HX1 - HX - 2)

harrow(HX1, DCX - DW / 2, mm)
c.path(f"M{DCX},{mm - DHH} L{DCX + DW / 2},{mm} L{DCX},{mm + DHH} L{DCX - DW / 2},{mm} Z",
       BLUE, 1.0, fill=WHITE)
T(DCX, mm - 1.6, "$H_{norm}$", 6.2, "middle")
T(DCX, mm + 7.0, "≤ $θ^{*}$ ?", 6.2, "middle")
T(W - M - 4, mm + DHH + 8, "→ Auto or Ask", FS, "end")

# hand-off 2 (θ*): from the bottom of the validation box
c.line([(DCX, CY1), (DCX, mm - DHH - 6)], INK, THICK)
c.polygon([(DCX, mm - DHH), (DCX - 2.7, mm - DHH - 6.3), (DCX + 2.7, mm - DHH - 6.3)], INK)
T(DCX + 4.5, L2Y0 + 10, "$θ^{*}$", 8.5, bold=True)
T(TRAIN_CX + 4.5, L2Y0 + 10, "trained scorer", 6.5, bold=True)

c.save("figure/pipeline_compare", W_IN, H_IN)
for wmsg in c.warn:
    print("WARN", wmsg)
print("wrote figure/pipeline_compare.{svg,pdf,png}")
