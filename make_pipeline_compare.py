"""Building the scorer offline and using it online (7.16 in x 2.5 in).

Two swim lanes; flow is left to right and only downward between lanes.
Offline, one construction (detection, all three checks, simulated user)
yields both the training and the validation set.  Charts are schematic.
"""

import math

from figlib import Canvas

# Soft ICDE-friendly palette (warmer, less chalky) — match motivation
BLUE = "#2F7FB8"
BLUE_L = "#6CB6E3"
ORANGE = "#E8922A"
ORANGE_FILL = "#FFE6C2"
ORANGE_SOFT = "#FFD9A0"
GRAY = "#C9CED4"
MID = "#6B7580"
BG = "#F3F6F9"
INK = "#55606C"  # softer than motivation ink
MUTED = "#6B7580"
WHITE = "#FFFFFF"
SOFT_STROKE = "#D7DEE6"
BLUE_SOFT = "#DCEAF5"
GREEN = "#3BAF9F"

W_IN, H_IN = 7.16, 2.7
W, H = W_IN * 72, H_IN * 72
SW = 0.7
R = 5
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
box(M, L2Y0, W - 2 * M, L2Y1 - L2Y0, fill="#F8FBFD", stroke=None)
T(M + 5, L1Y0 + 9.5, "Offline · training databases", 8, bold=True)
T(M + 5, L2Y0 + 9.5, "Online · inference", 8, bold=True)

# ====================================================================== top lane
R1Y, R1H = 18.0, 42.0
R2Y, R2H = 70.0, 38.0
r1m, r2m = R1Y + R1H / 2, R2Y + R2H / 2
CM = (r1m + r2m) / 2
CH_X0, CH_X1 = 400.0, W - M - 4

# source
SRC_CX = 24.0
for k in range(3):
    c.cylinder(SRC_CX - 13 + k * 3.2, CM - 24 + k * 4.5, 16, 15)
centered(SRC_CX, CM + 12, ["Training", "databases"], 6.5, 7.4, bold=True)

# detection + three checks
DX0, DW = 48.0, 36.0
harrow(44.0, DX0, CM - 8)
box(DX0, CM - 23.5, DW, 47)
T(DX0 + DW / 2, CM - 15.5, "Detection", 6.2, "middle", bold=True)
for k, nm in enumerate(["forward", "backward"]):
    label_box(DX0 + 3, CM - 10 + k * 15, DW - 6, 11, [nm])
FX0, FX1 = 88.0, 134.0
harrow(DX0 + DW, FX0, CM)
box(FX0, CM - 23.5, FX1 - FX0, 47, fill="none", stroke=GRAY, sw=0.6)
CHK = ["Existence", "Difference", "Relevance"]
CBH, CBG = 11.0, 4.0
cb_y0 = CM - (3 * CBH + 2 * CBG) / 2
for k, nm in enumerate(CHK):
    yy = cb_y0 + k * (CBH + CBG)
    label_box(FX0 + 3, yy, FX1 - FX0 - 6, CBH, [nm])
    if k < 2:
        c.arrow([((FX0 + FX1) / 2, yy + CBH), ((FX0 + FX1) / 2, yy + CBH + CBG)], INK, 0.55, hs=1.8)
FAN_CX = 145.0
harrow(FX1, FAN_CX - 8, CM)
fan(FAN_CX, CM - 12.5)
T(FAN_CX, CM + 14, "$Φ$", 6.5, "middle")
SUX0, SUW = 158.0, 64.0
harrow(FAN_CX + 8, SUX0, CM)
box(SUX0, CM - 23, SUW, 46, fill=ORANGE_FILL, stroke=ORANGE)
T(SUX0 + 4, CM - 10, "Simulated user", 6.5, bold=True)
T(SUX0 + 4, CM - 2.5, "/{match gold SQL?}", FS)
for j, (fill_a, out) in enumerate(((INK, "pick A"), (None, "Others"))):
    yy = CM + 2 + j * 10
    for q, lt in enumerate("AB"):
        on = fill_a is not None and q == 0
        c.rect(SUX0 + 4 + q * 9, yy, 7.5, 7.5, rx=1.2, fill=INK if on else WHITE,
               stroke=INK, sw=0.5)
        T(SUX0 + 7.75 + q * 9, yy + 5.6, lt, FS, "middle", bold=True, color=WHITE if on else MID)
    c.arrow([(SUX0 + 24, yy + 3.75), (SUX0 + 31, yy + 3.75)], INK, 0.6, hs=2.2)
    T(SUX0 + 33, yy + 5.8, out, FS, bold=True)
tgl = "sees gold SQL"
tgw = c.tw(tgl, FS) + 15
tgx = SUX0 + SUW / 2 - tgw / 2
box(tgx, CM - 27.6, tgw, 9.6, fill=WHITE, stroke=INK, rx=4.8)
lock(tgx + 5.6, CM - 22.5)
T(tgx + 10, CM - 20.7, tgl, FS)

# split
FKX = 229.0
BR = 292.0
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
TX, TW = 334.0, 58.0
TRAIN_CX = TX + TW / 2
harrow(330.0, TX, r1m)
box(TX, R1Y, TW, R1H, stroke=BLUE, sw=1.1)
centered(TRAIN_CX, R1Y + 8.5, ["Train", "scorer"], 6.5, 7.2, bold=True, color=BLUE)
T(TRAIN_CX, R1Y + 24.5, "$L$ = − $Σ_{j}$ $q_{j}$ log $w_{j}$", 6.2, "middle", maxw=TW - 2)
SHY = R1Y + 27.5
for g, order in enumerate(("AB", "BA")):
    gx = TRAIN_CX - 21 + g * 27
    for q, lt in enumerate(order):
        c.rect(gx + q * 7.5, SHY, 6.5, 6.5, rx=1, fill=WHITE, stroke=BLUE, sw=0.5)
        T(gx + 3.25 + q * 7.5, SHY + 5.0, lt, 5.5 if False else FS, "middle", bold=True, color=BLUE)
cycle_icon(TRAIN_CX, SHY + 3.4, r=2.4)
T(TRAIN_CX, R1Y + 39.8, "/{shuffled per epoch}", FS, "middle", maxw=TW - 2)

# online hand-off line (drawn before the boxes it passes)
JW = 28.0
MR0, MR1 = L2Y0 + 14, L2Y0 + 66
mm = (MR0 + MR1) / 2
JEV_TOP = mm - 14
c.line([(TRAIN_CX, R1Y + R1H), (TRAIN_CX, R2Y + 4 - 5)], INK, THICK)
c.polygon([(TRAIN_CX, R2Y + 4), (TRAIN_CX - 2.7, R2Y + 4 - 5.3), (TRAIN_CX + 2.7, R2Y + 4 - 5.3)],
          INK)
c.line([(TRAIN_CX, R2Y + R2H - 4), (TRAIN_CX, JEV_TOP - 6)], INK, THICK)
c.polygon([(TRAIN_CX, JEV_TOP), (TRAIN_CX - 2.7, JEV_TOP - 6.3), (TRAIN_CX + 2.7, JEV_TOP - 6.3)],
          INK)

# lower row: apply scorer
SC_X0, SC_X1 = BR, TX + TW
SC_Y, SC_H = R2Y + 2, R2H - 4
box(SC_X0, SC_Y, SC_X1 - SC_X0, SC_H, stroke=BLUE, sw=1.1)
scx = (SC_X0 + SC_X1) / 2
T(scx, SC_Y + 8.5, "Apply trained scorer", 6.5, "middle", bold=True, color=BLUE)
BASE = SC_Y + 24.5
LBL = SC_Y + 31.0
bx = SC_X0 + 6
for lt, hgt in (("A", 10.0), ("B", 3.5), ("C", 1.5), ("…", None), ("Z", 0.6)):
    if hgt is not None:
        c.rect(bx, BASE - hgt, 3.8, hgt, rx=0.4, fill=BLUE if lt == "A" else GRAY)
    T(bx + 1.9, LBL, lt, FS, "middle", bold=(lt == "A"),
      color=BLUE if lt == "A" else MID)
    bx += 5.6
c.line([(SC_X0 + 5, BASE), (bx - 1, BASE)], MID, 0.4)
AR0 = bx + 1
harrow(AR0, AR0 + 6, BASE - 4)
TPX = AR0 + 8
c.rect(TPX, BASE - 8.5, 8, 8, rx=1.2, fill=BLUE)
T(TPX + 4, BASE - 2.6, "A", FS, "middle", bold=True, color=WHITE)
T(TPX + 4, LBL, "top", FS, "middle", color=MID)
T(TPX + 13, BASE - 2.4, "=", 7, "middle", bold=True)
USX = TPX + 18
c.rect(USX, BASE - 8.5, 8, 8, rx=1.2, fill=ORANGE_SOFT, stroke=ORANGE, sw=0.7)
T(USX + 4, BASE - 2.6, "A", FS, "middle", bold=True)
T(USX + 4, LBL, "user", FS, "middle", color=MID)
harrow(USX + 9, USX + 15, BASE - 4)
T(USX + 17, BASE - 2.4, "agr($θ$)", FS)
harrow(SC_X1, CH_X0, r2m)

# validation chart
CY0, CY1 = R1Y - 3, L1Y1 - 4
box(CH_X0, CY0, CH_X1 - CH_X0, CY1 - CY0, stroke=BLUE, sw=1.1)
chm = (CH_X0 + CH_X1) / 2
T(chm, CY0 + 9, "Select θ* on validation set", 6.5, "middle", bold=True, maxw=CH_X1 - CH_X0 - 4)
AX0, AY0, AX1, AY1 = CH_X0 + 8, CY0 + 14, CH_X1 - 10, CY1 - 37
c.arrow([(AX0, AY1), (AX0, AY0)], INK, 0.65, hs=2.4)
c.arrow([(AX0, AY1), (AX1 + 3, AY1)], INK, 0.65, hs=2.4)
T(AX0 + 3, AY0 + 2.5, "agreement", FS)
T(AX1 + 4, AY1 + 2.3, "$θ$", 7)
T(AX0, AY1 + 7.5, "← fewer automatic", FS, color=MID)
T(AX1 + 3, AY1 + 7.5, "more →", FS, "end", color=MID)
SPAN = AX1 - AX0
p0, p1, p2, p3 = (AX0 + 3, AY0 + 7), (AX0 + 0.8 * SPAN, AY0 + 4), (AX0 + 0.6 * SPAN, AY1 - 3), (AX1 - 1, AY1 - 4)


def bez(t):
    u = 1 - t
    return tuple(u ** 3 * a + 3 * u * u * t * b + 3 * u * t * t * q + t ** 3 * d
                 for a, b, q, d in zip(p0, p1, p2, p3))


ALY = AY0 + 16
c.line([(AX0, ALY), (AX1, ALY)], INK, 0.65, dash="2,1.4", cap="butt")
T(AX1 + 2, ALY + 2.5, "$α$", 7)
c.path(f"M{p0[0]:.2f},{p0[1]:.2f} C{p1[0]:.2f},{p1[1]:.2f} {p2[0]:.2f},{p2[1]:.2f} "
       f"{p3[0]:.2f},{p3[1]:.2f}", BLUE, 1.2)
lo, hi = 0.0, 1.0
for _ in range(50):
    mid = (lo + hi) / 2
    lo, hi = (mid, hi) if bez(mid)[1] < ALY else (lo, mid)
ix, iy = bez(lo)
c.line([(ix, iy), (ix, AY1)], BLUE, 0.6)
star(ix, iy, ro=3.8, ri=1.6)
T(ix - 4, ALY + 12, "$θ^{*}$", 7, "end", bold=True)
T(chm, AY1 + 15, "`θ* = max{θ : agr(θ) ≥ α}`", FS, "middle", maxw=CH_X1 - CH_X0 - 4)
for j, ln in enumerate(["agr: top option = user's choice",
                        "α: target agreement, set by the user",
                        "θ*: largest entropy threshold meeting α"]):
    T(chm, AY1 + 22 + j * 6.5, f"/{{{ln}}}", FS, "middle", color=INK if j == 2 else MID,
      maxw=CH_X1 - CH_X0 - 4)

# ====================================================================== bottom lane
CD, CDW = M + 5, 92.0
CDY, CDH = MR0 + 4, MR1 - MR0 - 8
box(CD, CDY, CDW, CDH)
c.path(f"M{CD},{CDY + 9} V{CDY + R} Q{CD},{CDY} {CD + R},{CDY} H{CD + CDW - R} "
       f"Q{CD + CDW},{CDY} {CD + CDW},{CDY + R} V{CDY + 9} Z", ORANGE, SW, fill=ORANGE_SOFT)
T(CD + 3, CDY + 6.6, "'total cholesterol' · Project", 6, bold=True, maxw=CDW - 5)
for j, (lt, ln) in enumerate([("A", "The rate only"), ("B", "The rate and both"), ("", "monthly values")]):
    T(CD + 3, CDY + 19 + j * 7.2, lt, FS, bold=True)
    T(CD + 9.5, CDY + 19 + j * 7.2, ln, FS, maxw=CDW - 11)
PX0 = CD + CDW + 7
JX0 = TRAIN_CX - JW / 2
PX1 = JX0 - 7
harrow(CD + CDW, PX0, mm)
box(PX0, MR0, PX1 - PX0, MR1 - MR0)
c.path(f"M{PX0},{MR0 + 8.5} V{MR0 + R} Q{PX0},{MR0} {PX0 + R},{MR0} H{PX1 - R} Q{PX1},{MR0} "
       f"{PX1},{MR0 + R} V{MR0 + 8.5} Z", INK, SW, fill=BG)
T(PX0 + 2.5, MR0 + 6.4, "Scorer input for the running example", FS, maxw=PX1 - PX0 - 3)
rows = ["Question: …the decrease rate for his/her total cholesterol…",
        "Evidence: …   Schema: Laboratory(ID, Date, T-CHO, …)",
        "Span h: 'total cholesterol'   Type: Project",
        "Options:  A. The rate only",
        "          B. The rate and both monthly values",
        "Answer:"]
for j, s in enumerate(rows):
    T(PX0 + 3, MR0 + 15.5 + j * 6.6, f"`{s}`", FS, maxw=PX1 - PX0 - 5)

harrow(PX1, JX0, mm)
label_box(JX0, JEV_TOP, JW, (mm - JEV_TOP) * 2, ["Trained", "scorer"], stroke=BLUE, sw=1.1,
          size=6.0, bold=True, color=BLUE)

GAP = 5.0
WX0 = JX0 + JW + GAP
DW2, DHH = 44.0, 16.0
DCX = 452.0
WX1 = DCX - DW2 / 2 - GAP
harrow(JX0 + JW, WX0, mm)
box(WX0, mm - 14, WX1 - WX0, 28)
for j, (lt, ln) in enumerate((("A", 15.0), ("B", 13.0))):
    yy = mm - 10.5 + j * 6.2
    T(WX0 + 2.5, yy + 4.0, lt, FS, bold=True)
    c.rect(WX0 + 8, yy, ln, 4.2, rx=0.6, fill=ORANGE)
T(WX0 + 8 + 17, mm - 4.5, "$w$", 6.5)
T((WX0 + WX1) / 2, mm + 9.5, "$H_{norm}$ = 0.99", 6.0, "middle", maxw=WX1 - WX0 - 2)

harrow(WX1, DCX - DW2 / 2, mm)
c.path(f"M{DCX},{mm - DHH} L{DCX + DW2 / 2},{mm} L{DCX},{mm + DHH} L{DCX - DW2 / 2},{mm} Z",
       BLUE, 1.0, fill=WHITE)
T(DCX, mm - 1.6, "$H_{norm}$", 6.2, "middle")
T(DCX, mm + 7.0, "≤ $θ^{*}$ ?", 6.2, "middle")

OX = DCX + DW2 / 2
BX = OX + 4
PLX = BX + 5
PLW = W - M - 4 - PLX
c.line([(OX, mm), (BX, mm)], ORANGE, 1.1)
c.arrow([(BX, mm), (BX, mm - 10), (PLX, mm - 10)], GRAY, SW, hs=2.4, r=1.5)
c.arrow([(BX, mm), (BX, mm + 10), (PLX, mm + 10)], ORANGE, 1.1, hs=2.6, r=1.5)
box(PLX, mm - 15.5, PLW, 11, fill=WHITE, stroke=SOFT_STROKE, rx=5.5)
T(PLX + PLW / 2, mm - 7.8, "Auto", 6.5, "middle", bold=True, color=MID)
box(PLX, mm + 4.5, PLW, 11, fill=ORANGE_FILL, stroke=ORANGE, rx=5.5)
T(PLX + PLW / 2, mm + 12.2, "Ask", 6.5, "middle", bold=True)
T(BX + 1, mm - 18, "/{yes}", FS, color=MID)
T(BX + 1, mm + 24, "/{no}", FS)

# θ* hand-off
c.line([(DCX, CY1), (DCX, mm - DHH - 6)], INK, THICK)
c.polygon([(DCX, mm - DHH), (DCX - 2.7, mm - DHH - 6.3), (DCX + 2.7, mm - DHH - 6.3)], INK)
T(DCX + 4.5, L2Y0 + 9.5, "$θ^{*}$", 8.5, bold=True)
T(TRAIN_CX + 4.5, L2Y0 + 9.5, "trained scorer", 6.5, bold=True)

c.save("figure/pipeline_compare", W_IN, H_IN)
for wmsg in c.warn:
    print("WARN", wmsg)
print("wrote figure/pipeline_compare.{svg,pdf,png}")
