"""Building the scorer offline and using it online (7.16 in x 2.5 in).

Two swim lanes; flow is left to right and only downward between lanes.
Offline, one construction (detection, all three checks, simulated user)
yields both the training and the validation set.  Charts are schematic.
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

W_IN, H_IN = 7.16, 2.55
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
L1Y0, L1Y1 = M, 116.0
L2Y0, L2Y1 = 120.0, H - M
box(M, L1Y0, W - 2 * M, L1Y1 - L1Y0, fill=BG, stroke=None)
box(M, L2Y0, W - 2 * M, L2Y1 - L2Y0, fill=WHITE, stroke=GRAY, sw=0.6)
T(M + 5, L1Y0 + 9.5, "Offline · training databases", 8, bold=True)
T(M + 5, L2Y0 + 9.5, "Online · any question", 8, bold=True)

# ====================================================================== top lane
R1Y, R1H = 18.0, 42.0
R2Y, R2H = 70.0, 38.0
r1m, r2m = R1Y + R1H / 2, R2Y + R2H / 2
CM = (r1m + r2m) / 2
CH_X0, CH_X1 = 340.0, W - M - 4

# source
SRC_CX = 24.0
for k in range(3):
    c.cylinder(SRC_CX - 13 + k * 3.2, CM - 24 + k * 4.5, 16, 15)
centered(SRC_CX, CM + 12, ["Training", "databases"], 6.5, 7.4, bold=True)
centered(SRC_CX, CM + 29, ["disjoint from", "all benchmarks"], FS, 6.8, italic=True)

# shared construction
DX0, DW = 50.0, 40.0
harrow(44.0, DX0, CM - 8)
label_box(DX0, CM - 20, DW, 40, ["Detection", "+ all three", "checks"], lead=6.9)
FAN_CX = 105.0
harrow(DX0 + DW, FAN_CX - 8, CM)
fan(FAN_CX, CM - 12.5)
T(FAN_CX, CM + 14, "ambiguities", FS, "middle")
SUX0, SUW = 123.0, 63.0
harrow(FAN_CX + 8, SUX0, CM)
box(SUX0, CM - 23, SUW, 46, fill=ORANGE, stroke=ORANGE)
T(SUX0 + 4, CM - 8, "Simulated user", 6.5, bold=True)
for j, s in enumerate(["picks the option", "matching the gold", "query, or Others"]):
    T(SUX0 + 4, CM + 0.5 + j * 6.8, s, FS, maxw=SUW - 6)
tgl = "only step with gold SQL"
tgw = c.tw(tgl, FS) + 15
tgx = SUX0 + SUW / 2 - tgw / 2
box(tgx, CM - 27.6, tgw, 9.6, fill=WHITE, stroke=INK, rx=4.8)
lock(tgx + 5.6, CM - 22.5)
T(tgx + 10, CM - 20.7, tgl, FS)

# split
FKX = 192.0
BR = 236.0
c.line([(SUX0 + SUW, CM), (FKX, CM)], INK, SW)
c.line([(FKX, r1m), (FKX, r2m)], INK, SW)
c.circle(FKX, CM, 1.3, fill=INK)
harrow(FKX, BR, r1m)
harrow(FKX, BR, r2m)
T(FKX + 3, r1m - 2.2, "training set", FS)
T(FKX + 3, r2m - 2.2, "validation set", FS)
T(FKX + 3, CM - 1.2, "/{split by}", FS)
T(FKX + 3, CM + 5.6, "/{database}", FS)

# upper row: targets + training
tx0 = BR + 1
target(tx0, R1Y + 1.5, ["1", "0"], ORANGE)
T(tx0, R1Y + 15, "option chosen", FS, maxw=40)
T(tx0, R1Y + 21.4, "→ one-hot", FS)
target(tx0, R1Y + 25.5, ["½", "½"], GRAY)
T(tx0, R1Y + 39, "Others →", FS)
T(tx0, R1Y + 45.4, "uniform", FS)
TX, TW = 278.0, 56.0
TRAIN_CX = TX + TW / 2
harrow(274.0, TX, r1m)
box(TX, R1Y, TW, R1H, stroke=BLUE, sw=1.1)
centered(TRAIN_CX, R1Y + 8.5, ["Train", "scorer"], 6.5, 7.2, bold=True, color=BLUE)
T(TRAIN_CX, R1Y + 26.5, "$L$ = − $Σ_{j}$ $q_{j}$ log $w_{j}$", 6.2, "middle", maxw=TW - 2)
T(TRAIN_CX, R1Y + 33.5, "options permuted", FS, "middle", maxw=TW - 2)
ew = c.tw("each epoch", FS)
T(TRAIN_CX + 4, R1Y + 39.5, "each epoch", FS, "middle")
cycle_icon(TRAIN_CX + 4 - ew / 2 - 4.3, R1Y + 37.6, r=2.4)

# online hand-off line (drawn before the boxes it passes)
JW = 28.0
mm = L2Y0 + 33
JEV_TOP = mm - 14
c.line([(TRAIN_CX, R1Y + R1H), (TRAIN_CX, JEV_TOP - 6)], INK, THICK)
c.polygon([(TRAIN_CX, JEV_TOP), (TRAIN_CX - 2.7, JEV_TOP - 6.3), (TRAIN_CX + 2.7, JEV_TOP - 6.3)],
          INK)

# lower row: apply scorer
SC_X0, SC_X1 = BR, TX + TW
SC_Y, SC_H = R2Y + 4, R2H - 8
box(SC_X0, SC_Y, SC_X1 - SC_X0, SC_H, stroke=BLUE, sw=1.1)
scx = (SC_X0 + TRAIN_CX - 4) / 2
T(scx, SC_Y + 10, "Apply trained", 6.5, "middle", bold=True, color=BLUE)
T(scx, SC_Y + 17.5, "scorer", 6.5, "middle", bold=True, color=BLUE)
T(scx, SC_Y + 25.5, "$H_{norm}$, top option", FS, "middle")
harrow(SC_X1, CH_X0, r2m)

# validation chart
CY0, CY1 = R1Y - 3, L1Y1 - 4
box(CH_X0, CY0, CH_X1 - CH_X0, CY1 - CY0, stroke=BLUE, sw=1.1)
chm = (CH_X0 + CH_X1) / 2
T(chm, CY0 + 9.5, "Select θ* on the validation set", 7, "middle", bold=True, maxw=CH_X1 - CH_X0 - 4)
AX0, AY0, AX1, AY1 = CH_X0 + 9, CY0 + 15, CH_X1 - 13, CY1 - 24
c.arrow([(AX0, AY1), (AX0, AY0)], INK, 0.65, hs=2.6)
c.arrow([(AX0, AY1), (AX1 + 3, AY1)], INK, 0.65, hs=2.6)
T(AX0 + 3, AY0 + 2.5, "agreement", FS)
T(AX1 + 5, AY1 + 2.3, "$θ$", 7.5)
T(AX0, AY1 + 7.5, "← fewer automatic", FS, color=MID)
T(AX1 + 3, AY1 + 7.5, "more →", FS, "end", color=MID)
p0, p1, p2, p3 = (AX0 + 3, AY0 + 8), (AX0 + 100, AY0 + 4), (AX0 + 70, AY1 - 3), (AX1 - 1, AY1 - 4)


def bez(t):
    u = 1 - t
    return tuple(u ** 3 * a + 3 * u * u * t * b + 3 * u * t * t * q + t ** 3 * d
                 for a, b, q, d in zip(p0, p1, p2, p3))


ALY = AY0 + 19
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
T(chm, AY1 + 15, "`θ* = max { θ : agreement(θ) ≥ α }`", FS, "middle", maxw=CH_X1 - CH_X0 - 4)
T(chm, AY1 + 22, "/{agreement: top option = user's choice}", FS, "middle", color=MID)

# ====================================================================== bottom lane
MR0, MR1 = mm - 18, mm + 20
CD = M + 6
card_icon(CD, mm - 11, 19, 14, sw=SW)
centered(CD + 9.5, mm + 11, ["ambiguity", "$φ$ ∈ $Φ$"], FS, 7)
PX0 = CD + 27
JX0 = TRAIN_CX - JW / 2
PX1 = JX0 - 7
harrow(CD + 19, PX0, mm - 4)
box(PX0, MR0, PX1 - PX0, MR1 - MR0)
c.path(f"M{PX0},{MR0 + 8.5} V{MR0 + R} Q{PX0},{MR0} {PX0 + R},{MR0} H{PX1 - R} Q{PX1},{MR0} "
       f"{PX1},{MR0 + R} V{MR0 + 8.5} Z", INK, SW, fill=BG)
T(PX0 + 2.5, MR0 + 6.4, "All options in one prompt (abridged)", FS, maxw=PX1 - PX0 - 3)
pcols = [(3, ["Question: ...", "Evidence: ...", "Schema: ..."]),
         (68, ["Span h: '...'", "Type τ: ..."]),
         (128, ["Options:", "A. <option text>", "B. <option text>", "Answer:"])]
for dx, rows in pcols:
    for j, s in enumerate(rows):
        T(PX0 + dx, MR0 + 15.5 + j * 6.4, f"`{s}`", FS)
if PX0 + 128 + c.tw("`B. <option text>`", FS) > PX1 - 2:
    c.warn.append("prompt columns overflow")

harrow(PX1, JX0, mm)
label_box(JX0, JEV_TOP, JW, (mm - JEV_TOP) * 2, ["Trained", "scorer"], stroke=BLUE, sw=1.1,
          size=6.0, bold=True, color=BLUE)

GAP = 5.5
SX0 = JX0 + JW + GAP
cell, ncell, ia, ib = 4.4, 7, 0, 1
SX1 = SX0 + ncell * cell
harrow(JX0 + JW, SX0, mm)
for k in range(ncell):
    on = k in (ia, ib)
    c.rect(SX0 + k * cell, mm - 2.5, cell, 5, rx=0, fill=BLUE if on else WHITE,
           stroke=BLUE if on else GRAY, sw=0.35)
for k, ch in ((ia, "A"), (ib, "B")):
    T(SX0 + (k + 0.5) * cell, mm - 4.3, ch, FS, "middle", bold=True, color=BLUE)
T(SX0 + 4 * cell, mm - 4.3, "…", FS, "middle", color=MID)
T(SX0 + (ncell - 0.5) * cell, mm - 4.3, "Z", FS, "middle", color=MID)
centered((SX0 + SX1) / 2, mm + 9.5, ["letter", "logits"], FS, 6.6, italic=True)

DW2, DHH = 44.0, 16.0
DCX = 434.0
HX = SX1 + GAP
HX1 = DCX - DW2 / 2 - GAP
harrow(SX1, HX, mm)
box(HX, mm - 11, HX1 - HX, 22)
T((HX + HX1) / 2, mm - 2, "softmax → $w$", 6.2, "middle", maxw=HX1 - HX - 2)
T((HX + HX1) / 2, mm + 6.2, "$H_{norm}(φ)$", 6.2, "middle", maxw=HX1 - HX - 2)

harrow(HX1, DCX - DW2 / 2, mm)
c.path(f"M{DCX},{mm - DHH} L{DCX + DW2 / 2},{mm} L{DCX},{mm + DHH} L{DCX - DW2 / 2},{mm} Z",
       BLUE, 1.0, fill=WHITE)
T(DCX, mm - 1.6, "$H_{norm}$", 6.2, "middle")
T(DCX, mm + 7.0, "≤ $θ^{*}$ ?", 6.2, "middle")

OX = DCX + DW2 / 2
BX = OX + 5
PLX = BX + 6
c.line([(OX, mm), (BX, mm)], INK, SW)
c.arrow([(BX, mm), (BX, mm - 10), (PLX, mm - 10)], INK, SW, hs=2.6, r=1.5)
c.arrow([(BX, mm), (BX, mm + 10), (PLX, mm + 10)], INK, SW, hs=2.6, r=1.5)
PLW = W - M - 4 - PLX
box(PLX, mm - 15.5, PLW, 11, fill=BLUE, stroke=BLUE, rx=5.5)
T(PLX + PLW / 2, mm - 7.8, "Auto($p_{j}^{*}$)", 6.5, "middle", bold=True, color=WHITE)
box(PLX, mm + 4.5, PLW, 11, fill=ORANGE, stroke=ORANGE, rx=5.5)
T(PLX + PLW / 2, mm + 12.2, "Ask the user", 6.5, "middle", bold=True)
T(BX + 1.5, mm - 17.5, "/{yes}", FS)
T(BX + 1.5, mm + 23, "/{no}", FS)

# θ* hand-off
c.line([(DCX, CY1), (DCX, mm - DHH - 6)], INK, THICK)
c.polygon([(DCX, mm - DHH), (DCX - 2.7, mm - DHH - 6.3), (DCX + 2.7, mm - DHH - 6.3)], INK)
T(DCX + 4.5, L2Y0 + 9.5, "$θ^{*}$", 8.5, bold=True)
T(TRAIN_CX + 4.5, L2Y0 + 9.5, "trained scorer", 6.5, bold=True)

c.save("figure/pipeline_compare", W_IN, H_IN)
for wmsg in c.warn:
    print("WARN", wmsg)
print("wrote figure/pipeline_compare.{svg,pdf,png}")
