"""Offline training / online use of the candidate scorer (7.16 in x 3.0 in).

Two swim lanes; information flows left to right and only downward between
lanes.  All charts are schematic (no ticks, no values).
"""

from figlib import Canvas

BLUE = "#0072B2"
BLUE_L = "#56B4E9"
ORANGE = "#E69F00"
GRAY = "#BBBBBB"
BG = "#F4F4F4"
INK = "#333333"
WHITE = "#FFFFFF"

W_IN, H_IN = 7.16, 3.0
W, H = W_IN * 72, H_IN * 72
SW = 0.7
R = 3
FS = 6.0
LEAD = 6.6
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


def label_box(x, y, w, h, rows, fill=WHITE, stroke=INK, size=FS, sw=None, **kw):
    box(x, y, w, h, fill=fill, stroke=stroke, sw=sw)
    centered(x + w / 2, y + h / 2, rows, size, **kw)


def mini_card(x, y, w=11, h=8, color=BLUE_L):
    c.rect(x, y, w, h, rx=1.2, fill=WHITE, stroke=INK, sw=0.55)
    c.path(f"M{x},{y + 2.5} V{y + 1.2} Q{x},{y} {x + 1.2},{y} H{x + w - 1.2} "
           f"Q{x + w},{y} {x + w},{y + 1.2} V{y + 2.5} Z", INK, 0.55, fill=color)
    for k in (0, 1):
        c.line([(x + 1.8, y + 4.3 + k * 2), (x + w - 2.2 - k * 2.2, y + 4.3 + k * 2)], INK, 0.4)


def fan(cx, top):
    for k, rot in enumerate((-10, -3, 5)):
        c.items.append(f'<g transform="rotate({rot} {cx} {top + 9})">')
        mini_card(cx - 5.5 + k * 0.6, top + k * 1.4)
        c.items.append("</g>")


def lock(cx, cy, color=INK):
    c.path(f"M{cx - 1.6},{cy - 0.6} V{cy - 2.2} A1.6,1.6 0 0 1 {cx + 1.6},{cy - 2.2} V{cy - 0.6}",
           color, 0.65)
    c.rect(cx - 2.4, cy - 0.8, 4.8, 3.6, rx=0.6, fill=color)


def cycle_icon(cx, cy, r=3.6, color=INK):
    c.path(f"M{cx + r},{cy} A{r},{r} 0 1 1 {cx},{cy - r}", color, 0.75)
    c.polygon([(cx - 0.4, cy - r - 1.9), (cx + 2.4, cy - r), (cx - 0.4, cy - r + 1.9)], color)


def tag(x, y, label, stroke=GRAY, fill=BG):
    w = c.tw(label, FS) + 7
    box(x, y, w, 9.5, fill=fill, stroke=stroke, rx=4.75)
    T(x + 3.5, y + 6.8, label, FS)
    return w


def target(x, y, cells, color, txt_color):
    cw = 9.0
    for j, v in enumerate(cells):
        filled = color == GRAY or j == 0
        c.rect(x + j * cw, y, cw, 7.5, rx=1, fill=color if filled else WHITE, stroke=color, sw=0.7)
        T(x + j * cw + cw / 2, y + 5.7, v, FS, "middle", bold=True,
          color=txt_color if filled else INK)
    return 2 * cw


# ====================================================================== lanes
M = 3.0
L1Y0, L1Y1 = M, 124.0
L2Y0, L2Y1 = 128.5, H - M
box(M, L1Y0, W - 2 * M, L1Y1 - L1Y0, fill=BG, stroke=None)
box(M, L2Y0, W - 2 * M, L2Y1 - L2Y0, fill=WHITE, stroke=GRAY, sw=0.6)
T(M + 5, L1Y0 + 9.5, "Offline · training databases only", 8, bold=True)
T(M + 5, L2Y0 + 9.5, "Online · any question", 8, bold=True)

# columns shared by both rows of the top lane
COLS = [(112.0, 62.0), (182.0, 42.0), (232.0, 90.0), (330.0, 60.0), (398.0, W - M - 4 - 398.0)]
R1Y, R1H = 20.0, 44.0       # upper row (training)
R2Y, R2H = 78.0, 43.0       # lower row (threshold selection)
r1m, r2m = R1Y + R1H / 2, R2Y + R2H / 2


def cx(k):
    return COLS[k][0] + COLS[k][1] / 2


# ---------------------------------------------------------------- source + fork
SRC_X = M + 6
for k in range(3):
    c.cylinder(SRC_X + 4 + k * 3.2, 38 + k * 4.5, 15, 15)
T(SRC_X + 26, 76.5, "Training databases", 6.5, "middle", bold=True)
for j, s in enumerate(["disjoint from all", "benchmark databases"]):
    T(SRC_X + 26, 84 + j * 6.8, s, FS, "middle", italic=True)
FKX = 70.0
c.line([(SRC_X + 26, 61.5), (SRC_X + 26, 66), (FKX, 66)], INK, SW)
c.line([(FKX, r1m), (FKX, r2m)], INK, SW)
c.circle(FKX, 66, 1.3, fill=INK)
c.arrow([(FKX, r1m), (COLS[0][0], r1m)], hs=3)
c.arrow([(FKX, r2m), (COLS[0][0], r2m)], hs=3)
T(FKX + 3, r1m - 2.2, "train split", FS)
T(FKX + 3, r2m - 2.2, "held-out split", FS)
T(FKX + 3, 68.3, "/{split by database}", FS)

# ---------------------------------------------------------------- upper row
DET = ["Staged detection +", "type detectors", "(Fig. 2 ①②)"]
x, w = COLS[0]
label_box(x, R1Y + 6, w, R1H - 12, DET)
c.arrow([(x + w, r1m), (COLS[1][0], r1m)], hs=3)
fan(cx(1), r1m - 13)
T(cx(1), r1m + 13, "cards $φ$", 6.5, "middle")
c.arrow([(COLS[1][0] + COLS[1][1], r1m), (COLS[2][0], r1m)], hs=3)

# simulated user (the only place gold SQL is touched)
x, w = COLS[2]
box(x, R1Y, w, R1H, fill=ORANGE, stroke=ORANGE)
T(x + 4, R1Y + 15.5, "Simulated user", 6.5, bold=True)
for j, s in enumerate(["picks the option consistent", "with the gold query, or Others"]):
    T(x + 4, R1Y + 25 + j * 7.0, s, FS, maxw=w - 6)
tw_ = c.tw("gold SQL used only here", FS)
tgw = tw_ + 16
tgx = x + w - tgw - 3
box(tgx, R1Y - 4.5, tgw, 10, fill=WHITE, stroke=INK, rx=5)
lock(tgx + 6.5, R1Y + 0.6)
T(tgx + 11, R1Y + 2.6, "gold SQL used only here", FS)
c.arrow([(x + w, r1m), (COLS[3][0], r1m)], hs=3)

# soft targets
x, w = COLS[3]
tx0 = x + 3
target(tx0, R1Y + 1, ["1", "0"], ORANGE, INK)
T(tx0, R1Y + 15, "option chosen", FS)
T(tx0, R1Y + 21.6, "→ one-hot", FS)
target(tx0, R1Y + 25.5, ["½", "½"], GRAY, INK)
T(tx0, R1Y + 39.5, "Others → uniform", FS, maxw=w - 3)
c.arrow([(x + w, r1m), (COLS[4][0], r1m)], hs=3)

# train JEV
x, w = COLS[4]
box(x, R1Y, w, R1H, stroke=BLUE, sw=1.1)
T(x + w / 2, R1Y + 9.5, "Train joint evaluator (JEV)", 6.5, "middle", bold=True, color=BLUE)
T(x + w / 2, R1Y + 22.5, "$L$ = − $Σ_{j}$ $y_{j}$ log $π_{j}$", 7.5, "middle")
cyw = c.tw("options permuted each epoch", FS)
cyx = x + (w - cyw - 10) / 2
cycle_icon(cyx + 3.6, R1Y + 35.5)
T(cyx + 10, R1Y + 37.7, "options permuted each epoch", FS)

# ---------------------------------------------------------------- lower row
x, w = COLS[0]
label_box(x, R2Y + 5.5, w, R2H - 11, DET)
c.arrow([(x + w, r2m), (COLS[1][0], r2m)], hs=3)
x, w = COLS[1]
label_box(x, R2Y + 5.5, w, R2H - 11, ["cards +", "simulated-", "user choices"])
c.arrow([(x + w, r2m), (COLS[2][0] + 12, r2m)], hs=3)

# hand-off 1: trained JEV, routed between the rows and through the scoring box
JX = cx(2)
BAND_Y = (R1Y + R1H + R2Y) / 2
x, w = COLS[2]
SCORE_Y, SCORE_H = R2Y + 7, R2H - 14
JEV_Y = 157.0
c.line([(cx(4), R1Y + R1H), (cx(4), BAND_Y), (JX, BAND_Y), (JX, JEV_Y - 6)], INK, THICK, r=4)
c.polygon([(JX, JEV_Y), (JX - 2.6, JEV_Y - 6.2), (JX + 2.6, JEV_Y - 6.2)], INK)
T(cx(3) + 10, BAND_Y - 2.3, "trained JEV", 6.5, "middle", bold=True)
label_box(x + 12, SCORE_Y, w - 24, SCORE_H, ["Score with", "trained JEV"], stroke=BLUE, sw=1.1,
          bold=True)
c.arrow([(x + w - 12, r2m), (COLS[3][0], r2m)], hs=3)

# schematic agreement-vs-threshold chart
x, w = COLS[3]
AX0, AY0, AX1, AY1 = x + 7, R2Y + 6, x + w - 6, R2Y + R2H - 6
c.arrow([(AX0, AY1), (AX0, AY0)], INK, 0.65, hs=2.6)
c.arrow([(AX0, AY1), (AX1, AY1)], INK, 0.65, hs=2.6)
T(AX0 + 2.5, AY0 + 3.2, "agreement", FS)
T(AX1 + 1.5, AY1 + 2.3, "$θ$", 7)
p0, p1, p2, p3 = (AX0 + 2, AY0 + 9), (AX0 + 22, AY0 + 8), (AX0 + 28, AY1 - 2), (AX1 - 3, AY1 - 3)


def bez(t):
    u = 1 - t
    return tuple(u ** 3 * a + 3 * u * u * t * b + 3 * u * t * t * q + t ** 3 * d
                 for a, b, q, d in zip(p0, p1, p2, p3))


c.path(f"M{p0[0]:.2f},{p0[1]:.2f} C{p1[0]:.2f},{p1[1]:.2f} {p2[0]:.2f},{p2[1]:.2f} "
       f"{p3[0]:.2f},{p3[1]:.2f}", BLUE, 1.1)
ALY = AY0 + 17
lo, hi = 0.0, 1.0
for _ in range(50):
    mid = (lo + hi) / 2
    lo, hi = (mid, hi) if bez(mid)[1] < ALY else (lo, mid)
ix, iy = bez(lo)
c.line([(AX0, ALY), (AX1 - 4, ALY)], INK, 0.6, dash="1.8,1.3", cap="butt")
T(AX1 - 3, ALY + 2.3, "$α$", 7)
c.line([(ix, iy), (ix, AY1)], ORANGE, 0.9)
c.circle(ix, iy, 1.5, fill=ORANGE)
T(ix, AY1 + 6.6, "$θ^{*}$", 7, "middle")
c.arrow([(x + w, r2m), (COLS[4][0], r2m)], hs=3)

# rule box
x, w = COLS[4]
rule = ["agreement(θ): share of cards", "with H_norm ≤ θ whose top", "option equals the user's",
        "choice", "θ* = max { θ :", "      agreement(θ) ≥ α }"]
box(x, R2Y, w, R2H)
for j, r_ in enumerate(rule):
    T(x + 4, R2Y + 8 + j * 6.4 + (1.8 if j >= 4 else 0), f"`{r_}`", FS, maxw=w - 6)

# ====================================================================== bottom lane
MR0, MR1 = 141.0, 183.0
mm = (MR0 + MR1) / 2
# card
CDX = M + 8
c.rect(CDX + 6, mm - 12, 26, 18, rx=2, fill=WHITE, stroke=INK)
c.path(f"M{CDX + 6},{mm - 6.5} V{mm - 10} Q{CDX + 6},{mm - 12} {CDX + 8},{mm - 12} H{CDX + 30} "
       f"Q{CDX + 32},{mm - 12} {CDX + 32},{mm - 10} V{mm - 6.5} Z", INK, SW, fill=BLUE_L)
for k in range(2):
    c.line([(CDX + 9, mm - 2.5 + k * 3.4), (CDX + 29 - k * 6, mm - 2.5 + k * 3.4)], INK, 0.5)
T(CDX + 19, mm + 14, "card $φ$ = ⟨$h$, $P$⟩", 6.5, "middle")
CARD_R = CDX + 32

# prompt (two columns of lines)
PX0 = 66.0
PX1 = JX - 23
c.arrow([(CARD_R, mm - 3), (PX0, mm - 3)], hs=3)
box(PX0, MR0, PX1 - PX0, MR1 - MR0)
c.path(f"M{PX0},{MR0 + 9} V{MR0 + R} Q{PX0},{MR0} {PX0 + R},{MR0} H{PX1 - R} Q{PX1},{MR0} "
       f"{PX1},{MR0 + R} V{MR0 + 9} Z", INK, SW, fill=BG)
T(PX0 + 3.5, MR0 + 6.6, "All options in one prompt (abridged)", FS)
left = ["Question: ...", "Evidence: ...", "Span h: '...'"]
right = ["Options:", "A. <d₁>", "B. <d₂>", "Answer:"]
for j, s in enumerate(left):
    T(PX0 + 4, MR0 + 17 + j * LEAD, f"`{s}`", FS)
col2 = PX0 + (PX1 - PX0) / 2 + 4
for j, s in enumerate(right):
    T(col2, MR0 + 17 + j * LEAD, f"`{s}`", FS)

# JEV
JW = 30.0
c.arrow([(PX1, mm), (JX - JW / 2, mm)], hs=3)
label_box(JX - JW / 2, JEV_Y, JW, MR1 - 6 - JEV_Y, ["JEV"], stroke=BLUE, sw=1.1, size=6.5,
          bold=True, color=BLUE)
JEVM = (JEV_Y + MR1 - 6) / 2

# logits strip
SX0 = JX + JW / 2 + 9
cell = 3.4
ncell = 17
SX1 = SX0 + ncell * cell
ia, ib = 4, 11
SY = JEVM - 2.5
c.arrow([(JX + JW / 2, JEVM), (SX0, JEVM)], hs=3)
for k in range(ncell):
    on = k in (ia, ib)
    c.rect(SX0 + k * cell, SY, cell, 5, rx=0, fill=BLUE if on else WHITE,
           stroke=BLUE if on else GRAY, sw=0.35)
for k, ch in ((ia, "A"), (ib, "B")):
    T(SX0 + (k + 0.5) * cell, SY - 1.8, ch, FS, "middle", bold=True, color=BLUE)
T((SX0 + SX1) / 2, SY + 12.5, "option-letter logits", FS, "middle", italic=True)

# softmax
SMX, SMW = SX1 + 8, 30.0
c.arrow([(SX1, JEVM), (SMX, JEVM)], hs=3)
label_box(SMX, JEVM - 10, SMW, 20, ["softmax", "→ $π$"])

# H_norm
HX = SMX + SMW + 8
DW = 52.0
HW = W - M - 5 - DW - 7 - HX
c.arrow([(SMX + SMW, JEVM), (HX, JEVM)], hs=3)
box(HX, JEVM - 14, HW, 28)
centered(HX + HW / 2, JEVM, ["$H_{norm}(φ)$ =", "−$Σ_{j}$ $π_{j}$ log $π_{j}$", "/ log |$P$|"], 6.5, 7.6)

# diamond (gate)
DCX = W - M - 5 - DW / 2
DHH = 14.0
c.arrow([(HX + HW, JEVM), (DCX - DW / 2, JEVM)], hs=3)
c.path(f"M{DCX},{JEVM - DHH} L{DCX + DW / 2},{JEVM} L{DCX},{JEVM + DHH} L{DCX - DW / 2},{JEVM} Z",
       INK, SW, fill=WHITE)
T(DCX, JEVM + 2.2, "$H_{norm}$ ≤ $θ^{*}$ ?", 6, "middle", maxw=DW - 6)
T(W - M - 5, JEVM + DHH + 8.5, "to the gate (Fig. 2 ③)", FS, "end")

# hand-off 2: theta*
c.line([(DCX, R2Y + R2H), (DCX, JEVM - DHH - 6)], INK, THICK)
c.polygon([(DCX, JEVM - DHH), (DCX - 2.6, JEVM - DHH - 6.2), (DCX + 2.6, JEVM - DHH - 6.2)], INK)
T(DCX + 4, L2Y0 + 9.5, "$θ^{*}$", 8, bold=True)
T(JX + 4, L2Y0 + 9.5, "trained JEV", 6.5, bold=True)

# training-free bypass
BYY = 192.0
bx0 = CDX + 19
c.arrow([(bx0, mm + 16.5), (bx0, BYY), (SMX + SMW / 2, BYY), (SMX + SMW / 2, JEVM + 10)],
        GRAY, 0.9, dash="2.4,1.6", hs=3, r=2.5, cap="butt")
lab = "/{Alternative: training-free scorer — one verbal score per option}"
lw = T(PX0, BYY + 8.6, lab, FS)
tx = PX0 + lw + 7
for t_ in ("coarse", "position-sensitive", "overconfident"):
    tx += tag(tx, BYY + 2.2, t_) + 4

c.save("figure/pipeline", W_IN, H_IN)
print("wrote figure/pipeline.{svg,pdf,png}")
