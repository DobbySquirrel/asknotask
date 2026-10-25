"""How the candidate scorer is built, trained and thresholded (7.16 in x 2.5 in).

Four panels (a)-(d).  Every chart is schematic: no ticks, statistics or
results; the only illustrative number is the verbal-score output in (a).
"""

from figlib import Canvas

BLUE = "#0072B2"
BLUE_L = "#56B4E9"
ORANGE = "#E69F00"
GREEN = "#009E73"
GRAY = "#BBBBBB"
BG = "#F4F4F4"
INK = "#333333"
WHITE = "#FFFFFF"

W_IN, H_IN = 7.16, 2.5
W, H = W_IN * 72, H_IN * 72
SW = 0.7
R = 3
FS = 6.0
LEAD = 6.6

c = Canvas(W, H, stroke=SW, ink=INK)
T = c.text


def box(x, y, w, h, fill=WHITE, stroke=INK, rx=R, dash=None, sw=None):
    c.rect(x, y, w, h, rx=rx, fill=fill, stroke=stroke, dash=dash, sw=sw)


def centered(cx, cy, rows, size=FS, lead=None, **kw):
    lead = lead or size * 1.2
    y0 = cy - (len(rows) - 1) * lead / 2 + 0.35 * size
    for j, r_ in enumerate(rows):
        T(cx, y0 + j * lead, r_, size, "middle", **kw)


def code_box(x, y, w, title, rows, title_bold=True):
    h = 10.5 + len(rows) * LEAD + 2.5
    box(x, y, w, h)
    c.path(f"M{x},{y + 9} V{y + R} Q{x},{y} {x + R},{y} H{x + w - R} Q{x + w},{y} {x + w},{y + R} "
           f"V{y + 9} Z", INK, SW, fill=BG)
    T(x + 3, y + 6.6, title, FS, bold=title_bold, maxw=w - 5)
    base = []
    for j, r_ in enumerate(rows):
        by = y + 10.5 + 5.0 + j * LEAD
        T(x + 3.5, by, f"`{r_}`", FS, maxw=w - 6)
        base.append(by)
    return h, base


def tag(x, y, label):
    w = c.tw(label, FS) + 7
    box(x, y, w, 9.5, fill=BG, stroke=GRAY, rx=4.75)
    T(x + 3.5, y + 6.8, label, FS)
    return w


def cycle_icon(cx, cy, r=4.2, color=INK):
    c.path(f"M{cx + r},{cy} A{r},{r} 0 1 1 {cx},{cy - r}", color, 0.8)
    c.polygon([(cx - 0.4, cy - r - 2.1), (cx + 2.6, cy - r), (cx - 0.4, cy - r + 2.1)], color)


TOP, BOT = 18.0, H - 4.0
fr = [0.20, 0.30, 0.28, 0.22]
xs = [4.0]
for f in fr:
    xs.append(xs[-1] + f * (W - 8))
P = [(xs[k], xs[k + 1] - xs[k]) for k in range(4)]

for k, ((x, w), t) in enumerate(zip(P, ["(a) Training-free scorer", "(b) Joint evaluator: inference",
                                         "(c) Joint evaluator: training", "(d) Threshold selection"])):
    if k in (1, 2):
        box(x + 3, 4, w - 6, BOT - 4, fill=BG, stroke=None)
    T(x + 7 if k in (1, 2) else x + 3, 12.5, t, 7.5, bold=True, maxw=w - 8)
for x in xs[1:-1]:
    c.line([(x, 6), (x, BOT - 2)], GRAY, 0.6)

# ---------------------------------------------------------------- (a)
x0, pw = P[0]
AX, AW = x0 + 2, pw - 6
ah, _ = code_box(AX, TOP + 4, AW, "Prompt (abridged)",
                 ["Rate how likely each", "option is intended", "(0–1).", "A. <reading 1>", "B. <reading 2>"])
OY = TOP + 4 + ah + 12
c.arrow([(AX + AW / 2, TOP + 4 + ah), (AX + AW / 2, OY)], hs=3)
cw = (AW - 6) / 2
for j, s in enumerate(["A: 0.95", "B: 0.05"]):
    bx = AX + j * (cw + 6)
    box(bx, OY, cw, 13, stroke=GRAY)
    T(bx + cw / 2, OY + 8.8, f"/{{`{s}`}}", FS, "middle", color="#8C8C8C")
T(AX + AW / 2, OY + 21.5, "verbal scores, one call per option", FS, "middle", italic=True, maxw=AW)
TY = OY + 40
w1 = tag(AX, TY, "coarse")
tag(AX + w1 + 4, TY, "position-sensitive")
tag(AX, TY + 13, "overconfident")

# ---------------------------------------------------------------- (b)
x0, pw = P[1]
IX, IY, IW = x0 + 7, TOP + 2, 104.0
ih, ib = code_box(IX, IY, IW, "All options in one prompt (abridged)",
                  ["Question: ...", "Evidence: ...", "Span h: 'total cholesterol'",
                   "Options:", "A. <d₁>", "B. <d₂>", "Answer:"], title_bold=False)
OPT_Y = (ib[4] + ib[5]) / 2 - 2.2

LY = IY + ih + 12
LW_, LH = 38.0, 18.0
c.arrow([(IX + LW_ / 2, IY + ih), (IX + LW_ / 2, LY)], hs=3)
box(IX, LY, LW_, LH, stroke=BLUE)
centered(IX + LW_ / 2, LY + LH / 2, ["Fine-tuned", "LLM scorer"], FS, 6.8, bold=True)

SX0, SX1 = IX + LW_ + 10, x0 + pw - 7
SY = LY + 6.5
cell = 3.6
ncell = int((SX1 - SX0) // cell)
SX1 = SX0 + ncell * cell
ia, ibb = 4, 10
c.arrow([(IX + LW_, LY + LH / 2), (SX0, LY + LH / 2)], hs=3)
for k in range(ncell):
    col = BLUE if k in (ia, ibb) else WHITE
    c.rect(SX0 + k * cell, SY, cell, 5, rx=0, fill=col, stroke=GRAY if col == WHITE else BLUE, sw=0.35)
T(SX0 + (ia + 0.5) * cell, SY - 1.8, "A", FS, "middle", bold=True, color=BLUE)
T(SX0 + (ibb + 0.5) * cell, SY - 1.8, "B", FS, "middle", bold=True, color=BLUE)
T(SX1, SY + 14.5, "next-token distribution", FS, "end", italic=True)

RY = SY + 33
SMW, SMH = 70.0, 20.0
SMX = SX1 - SMW
ABX = SMX + 12
c.line([(SX0 + (ia + 0.5) * cell, SY + 5), (SX0 + (ia + 0.5) * cell, SY + 9),
        (SX0 + (ibb + 0.5) * cell, SY + 9), (SX0 + (ibb + 0.5) * cell, SY + 5)], BLUE, 0.8)
BMX = SX0 + (ia + ibb + 1) / 2 * cell
c.arrow([(BMX, SY + 9), (BMX, RY)], BLUE, 0.8, hs=3)
box(SMX, RY, SMW, SMH)
centered(SMX + SMW / 2, RY + SMH / 2, ["softmax over", "option letters → $π$"], 6.5, 7.4)
HX, HW = IX + 6, 36.0
c.arrow([(SMX, RY + SMH / 2), (HX + HW, RY + SMH / 2)], hs=3)
box(HX, RY + 2, HW, SMH - 4, stroke=BLUE)
T(HX + HW / 2, RY + SMH / 2 + 2.4, "$H_{norm}(φ)$", 7, "middle")
GY = BOT - 6
c.arrow([(HX + HW / 2, RY + SMH - 2), (HX + HW / 2, GY)], INK, 0.75, dash="2,1.4", hs=3, cap="butt")
T(HX + HW / 2 + 4, GY - 2, "to the gate (Fig. 2 ③)", FS)
PI_Y = RY + SMH / 2

# ---------------------------------------------------------------- (c)
x0, pw = P[2]
FY0, FH = TOP + 9, 25.0
B1X, B1W = x0 + 7, 31.0
B2X, B2W = B1X + B1W + 6, 45.0
TX = B2X + B2W + 7
TW = x0 + pw - 7 - TX
box(B1X, FY0, B1W, FH)
centered(B1X + B1W / 2, FY0 + FH / 2, ["Cards on", "training", "databases"], FS, 6.8)
c.arrow([(B1X + B1W, FY0 + FH / 2), (B2X, FY0 + FH / 2)], hs=3)
box(B2X, FY0, B2W, FH)
centered(B2X + B2W / 2, FY0 + FH / 2, ["Simulated user:", "one option,", "or Others"], FS, 6.8)

targets = [("1", "0", BLUE, WHITE, ["option chosen", "→ one-hot"]),
           ("½", "½", GRAY, INK, ["Others", "→ uniform"])]
ty = TOP + 1.5
t_mid = []
for v1, v2, col, txt, lab in targets:
    cwid = 13.0
    bx = TX + TW / 2 - cwid
    for j, v in enumerate((v1, v2)):
        filled = col == GRAY or j == 0
        c.rect(bx + j * cwid, ty, cwid, 9, rx=1.2 if j else 1.2,
               fill=col if filled else WHITE, stroke=col, sw=0.7)
        T(bx + j * cwid + cwid / 2, ty + 6.6, v, FS, "middle", bold=True,
          color=(WHITE if col == BLUE else INK) if filled else BLUE)
    for j, s in enumerate(lab):
        T(TX + TW / 2, ty + 16 + j * 6.8, s, FS, "middle", maxw=TW)
    t_mid.append(ty + 4.5)
    ty += 29
c.line([(TX - 3, t_mid[0]), (TX - 3, t_mid[1])], INK, SW)
for m in t_mid:
    c.arrow([(TX - 3, m), (TX + TW / 2 - 14.5, m)], hs=2.6)
c.line([(B2X + B2W, FY0 + FH / 2), (TX - 3, FY0 + FH / 2)], INK, SW)

# option permutation back to (b)
CYX = x0 + 12
cycle_icon(CYX, OPT_Y)
T(CYX + 7, OPT_Y - 0.6, "options permuted", FS, maxw=TX - CYX - 9)
T(CYX + 7, OPT_Y + 6.2, "each epoch", FS)
c.arrow([(CYX - 5.5, OPT_Y), (IX + IW, OPT_Y)], INK, 0.75, hs=3)

# loss
LBX, LBW = x0 + 7, pw - 14
LBY, LBH = RY - 2, SMH + 4
box(LBX, LBY, LBW, LBH, stroke=BLUE)
T(LBX + LBW / 2, LBY + 10, "$L$ = − $Σ_{j}$ $y_{j}$ log $π_{j}$", 7, "middle")
T(LBX + LBW / 2, LBY + 18.6, "(soft-label cross-entropy)", FS, "middle")
YX = TX + TW / 2
c.arrow([(YX, ty - 29 + 23.5), (YX, LBY)], hs=3)
T(YX + 3, (ty - 5.5 + LBY) / 2 + 2, "targets $y$", FS)
c.arrow([(SX1, PI_Y), (LBX, PI_Y)], hs=3)
T((SX1 + LBX) / 2 + 1, PI_Y - 2.6, "$π$", 7, "middle")

# ---------------------------------------------------------------- (d)
x0, pw = P[3]
AX0, AY0, AX1, AY1 = x0 + 10, TOP + 12, x0 + pw - 10, TOP + 68
T(x0 + 5, TOP + 5, "agreement on held-out cards", FS)
c.arrow([(AX0, AY1), (AX0, AY0)], INK, 0.75, hs=3)
c.arrow([(AX0, AY1), (AX1, AY1)], INK, 0.75, hs=3)
T(AX1 + 2.5, AY1 + 2.3, "$θ$", 7)

p0, p1, p2, p3 = (AX0 + 4, AY0 + 5), (AX0 + 40, AY0 + 4), (AX0 + 52, AY1 - 4), (AX1 - 6, AY1 - 6)


def bez(t):
    u = 1 - t
    return tuple(u ** 3 * a + 3 * u * u * t * b + 3 * u * t * t * cc + t ** 3 * d
                 for a, b, cc, d in zip(p0, p1, p2, p3))


c.path(f"M{p0[0]:.2f},{p0[1]:.2f} C{p1[0]:.2f},{p1[1]:.2f} {p2[0]:.2f},{p2[1]:.2f} "
       f"{p3[0]:.2f},{p3[1]:.2f}", BLUE, 1.2)
ALPHA_Y = AY0 + 26
lo, hi = 0.0, 1.0
for _ in range(50):
    mid = (lo + hi) / 2
    lo, hi = (mid, hi) if bez(mid)[1] < ALPHA_Y else (lo, mid)
ix, iy = bez(lo)
c.line([(AX0, ALPHA_Y), (AX1 - 6, ALPHA_Y)], INK, 0.7, dash="2,1.4", cap="butt")
T(AX1 - 4, ALPHA_Y + 2.4, "$α$", 7)
c.line([(ix, iy), (ix, AY1)], ORANGE, 0.9)
c.circle(ix, iy, 1.6, fill=ORANGE)
T(ix, AY1 + 8, "$θ^{*}$", 7, "middle")

RBY = AY1 + 13
rule = ["agreement = share of", "auto-resolved cards whose", "top option equals the",
        "user's choice", "", "θ* = max { θ :", "      agreement(θ) ≥ α }"]
RBX, RBW = x0 + 4, pw - 7
RBH = len(rule) * LEAD + 5
box(RBX, RBY, RBW, RBH)
for j, r_ in enumerate(rule):
    if r_:
        T(RBX + 3.5, RBY + 7.5 + j * (LEAD - (0.9 if j > 4 else 0)), f"`{r_}`", FS, maxw=RBW - 5)
DY = BOT - 3
c.arrow([(RBX + RBW - 18, RBY + RBH), (RBX + RBW - 18, DY), (x0 + pw, DY)], INK, 0.75,
        dash="2,1.4", hs=3, r=2, cap="butt")
T(RBX + RBW - 21, DY + 0.3, "$θ^{*}$ → gate", FS, "end")

c.save("figure/scorer", W_IN, H_IN)
print("wrote figure/scorer.{svg,pdf,png}")
