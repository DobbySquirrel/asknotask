"""System overview figure with running example (7.16 in x 3.4 in).

Row A: running example (question with three highlighted spans, schema).
Row B: four stage panels; each example ambiguity keeps its colour throughout.
"""

from figlib import Canvas

BLUE_L = "#6CB6E3"   # settled by data
BLUE = "#2F7FB8"     # auto-resolved
ORANGE = "#E8922A"   # asked
GRAY = "#C9CED4"     # removed / dropped
GREEN = "#3BAF9F"    # correct SQL
BG = "#F3F6F9"
INK = "#2A3138"
WHITE = "#FFFFFF"

W_IN, H_IN = 7.16, 3.4
W, H = W_IN * 72, H_IN * 72
SW = 0.7
THICK = 1.55
R = 4

c = Canvas(W, H, stroke=SW, ink=INK)
T = c.text

CARD = {1: BLUE_L, 2: BLUE, 3: ORANGE}
CARD_TXT = {1: INK, 2: WHITE, 3: WHITE}


def tag(cx, cy, n, r=3.6):
    c.circle(cx, cy, r, fill=CARD[n])
    T(cx, cy + 2.15, str(n), 6, "middle", bold=True, color=CARD_TXT[n])


def box(x, y, w, h, fill=WHITE, stroke=INK, rx=R, sw=None, dash=None):
    c.rect(x, y, w, h, rx=rx, fill=fill, stroke=stroke, sw=sw, dash=dash)


def pill(x, y, w, h, fill):
    c.rect(x, y, w, h, rx=h / 2, fill=fill)


def header(x, y, n, title, sub=None):
    c.circle(x + 9, y + 9, 5.6, fill=INK)
    T(x + 9, y + 11.7, str(n), 7.5, "middle", bold=True, color=WHITE)
    T(x + 17, y + 11.7, title, 7.5, bold=True)
    if sub:
        T(x + 17, y + 19.2, sub, 6, italic=True)


def magnifier(cx, cy, r=2.8, color=INK):
    # soft filled glass + round handle
    c.circle(cx, cy, r, fill="#EEF6FB", stroke=color, sw=0.7)
    c.circle(cx, cy, r * 0.45, fill="none", stroke=color, sw=0.45)
    c.line([(cx + r * 0.72, cy + r * 0.72), (cx + r * 0.72 + 2.4, cy + r * 0.72 + 2.4)], color, 1.15)


def table_icon(x, y, w, h, color=INK):
    c.rect(x, y, w, h, rx=1.4, fill="#F5F9FC", stroke=color, sw=0.6)
    c.line([(x, y + h * 0.32), (x + w, y + h * 0.32)], color, 0.55)
    c.line([(x, y + h * 0.66), (x + w, y + h * 0.66)], color, 0.4)
    for k in (1, 2):
        c.line([(x + w * k / 3, y + h * 0.32), (x + w * k / 3, y + h)], color, 0.4)


def bubble(cx, cy, color=INK):
    # filled soft speech bubble
    c.rect(cx - 3.3, cy - 2.6, 6.6, 4.4, rx=2.0, fill="#FFF6E8", stroke=color, sw=0.65)
    c.path(f"M{cx - 1.4},{cy + 1.7} L{cx - 2.2},{cy + 3.4} L{cx + 0.3},{cy + 1.7}",
           color, 0.55, fill=color)


def trash(cx, cy, color=INK):
    # rounded filled bin + soft lid
    c.rect(cx - 2.0, cy - 2.35, 4.0, 0.7, rx=0.35, fill=color, stroke=None)
    c.rect(cx - 0.9, cy - 3.15, 1.8, 0.9, rx=0.45, fill="none", stroke=color, sw=0.55)
    c.path(f"M{cx - 1.85},{cy - 1.45} L{cx - 1.35},{cy + 2.55} "
           f"Q{cx - 1.35},{cy + 2.95} {cx - 0.95},{cy + 2.95} "
           f"L{cx + 0.95},{cy + 2.95} Q{cx + 1.35},{cy + 2.95} {cx + 1.35},{cy + 2.55} "
           f"L{cx + 1.85},{cy - 1.45} Z", color, 0.55, fill="#EDEDED")
    for dx in (-0.7, 0.0, 0.7):
        c.line([(cx + dx, cy - 0.9), (cx + dx, cy + 2.1)], "#A8A8A8", 0.45)


def check(cx, cy, r=3.8):
    c.circle(cx, cy, r, fill=GREEN, stroke=WHITE, sw=0.7)
    c.line([(cx - 1.7, cy + 0.15), (cx - 0.35, cy + 1.45), (cx + 1.9, cy - 1.25)], WHITE, 1.05)


def dotted(pts, color, r=2):
    c.line(pts, color, 0.9, dash="0.01,1.7", r=r)


def mini_card(x, y, color, w=12.5, h=9):
    c.rect(x, y, w, h, rx=1.8, fill=WHITE, stroke=INK, sw=0.55)
    c.path(f"M{x},{y + 2.9} V{y + 1.8} Q{x},{y} {x + 1.8},{y} H{x + w - 1.8} "
           f"Q{x + w},{y} {x + w},{y + 1.8} V{y + 2.9} Z", INK, 0.55, fill=color)
    for k in (0, 1):
        c.line([(x + 2.2, y + 4.9 + k * 2.2), (x + w - 2.6 - k * 2.4, y + 4.9 + k * 2.2)], INK, 0.4)


# ====================================================================== grid
M = 4.0
AY0, AY1 = 4.0, 47.5          # row A
SHIFT = 11.0                  # row B is drawn in its own frame, lifted by SHIFT
PT, PB = 78.0, 241.5 + SHIFT  # row B (in its frame)
GAP = 8.0
widths = [140.0, 147.0, 110.0, W - 2 * M - 3 * GAP - 397.0]
xs = [M]
for w_ in widths[:-1]:
    xs.append(xs[-1] + w_ + GAP)
P = list(zip(xs, widths))

# ====================================================================== row A
box(M, AY0, W - 2 * M, AY1 - AY0, fill=BG, stroke=None)
T(M + 6, 14.5, "!{Input} $x$ = ($Q$, $S$, $D$, $E$)", 6.5)

# legend of card outcomes
lx = M + 92
for col, lab in [(BLUE_L, "settled by data"), (BLUE, "auto-resolved"), (ORANGE, "asked"),
                 (GRAY, "removed / dropped"), (GREEN, "correct SQL")]:
    c.rect(lx, 9.6, 8, 5, rx=1.2, fill=col)
    lx += 10.5 + T(lx + 10.5, 14.3, lab, 6) + 9

# database + schema snippet
DBX = 376.0
c.cylinder(DBX, 7.5, 13, 18)
T(DBX + 6.5, 20.6, "$D$", 7, "middle")
T(DBX + 18, 14.3, "`Patient(ID, Birthday, ...)`", 6)
T(DBX + 18, 22.8, "`Laboratory(ID, Date, T-CHO, ...)`", 6, maxw=W - M - DBX - 20)

# question with highlighted spans
QS = 7.0
QY = 39.0
segs = [("“For the patient who was ", None), ("born on 1959/2/18", 1),
        (", what is the ", None), ("decrease rate", 2), (" for his/her ", None),
        ("total cholesterol", 3), (" from November to December in 1981?”", None)]
qx = M + 6
span_x = {}
for txt, n in segs:
    w_ = c.tw(txt, QS, italic=True)
    if n:
        c.rect(qx - 1, QY - 6.3, w_ + 2, 8.6, rx=1.6, fill=CARD[n])
        span_x[n] = (qx, w_)
    T(qx, QY, txt, QS, italic=True, color=CARD_TXT[n] if n else INK)
    qx += w_
for n, (sx, sw_) in span_x.items():
    tag(sx + sw_ / 2, QY - 11.5, n)

# ====================================================================== panels
c.items.append(f'<g transform="translate(0,{-SHIFT})">')
titles = [("Detection", None), ("Ambiguity Checks", "— Q1–Q3 by execution"),
          ("Resolution Criterion", "— by estimated user choice"), ("Parsing", None)]
for k, ((x, w_), (t, s)) in enumerate(zip(P, titles)):
    box(x, PT, w_, PB - PT, fill=BG, stroke=None)
    header(x, PT, k + 1, t, s)

# ---------------------------------------------------------------- panel 1
x0, pw = P[0]
PAD_L, PAD_R = 10.0, 3.5
SX = x0 + PAD_L
SWD = pw - PAD_L - PAD_R
MX = x0 + pw / 2

# --- inputs: Q · S+/E · optional draft pool ---
IN_Y, IN_H = 99.0, 20.5
gaps = 2.5
# roughly equal chips; draft pool carries "optional"
avail = SWD - 2 * gaps
iw = [avail * 0.28, avail * 0.36, avail * 0.36]
ix = SX
in_mids = []
in_labels = [
    ("$Q$", "NL"),
    ("$S^{+}$ · $E$", "schema+evid."),
    ("SQL drafts", "diverse · opt."),
]
for k, ((title, sub), w) in enumerate(zip(in_labels, iw)):
    box(ix, IN_Y, w, IN_H, fill=WHITE, stroke=INK, rx=2.5,
        dash="2,1.4" if k == 2 else None)
    T(ix + w / 2, IN_Y + 8.0, title, 6.2, "middle", bold=True, maxw=w - 3)
    T(ix + w / 2, IN_Y + 16.0, sub, 6, "middle", italic=True, maxw=w - 3)
    in_mids.append(ix + w / 2)
    ix += w + gaps

# converge into shared spine
JOIN_Y = IN_Y + IN_H + 4.0
for cx in in_mids:
    c.line([(cx, IN_Y + IN_H), (cx, JOIN_Y - 1.2), (MX, JOIN_Y - 1.2)], r=1.2)
c.arrow([(MX, JOIN_Y - 1.2), (MX, JOIN_Y + 1.2)], hs=2.4)

# --- shared taxonomy stages (9 types) ---
def tax_box(sx, y, w, h, label, rows):
    box(sx, y, w, h)
    strip = 16.5
    c.path(f"M{sx + strip},{y} H{sx + R} Q{sx},{y} {sx},{y + R} V{y + h - R} "
           f"Q{sx},{y + h} {sx + R},{y + h} H{sx + strip} Z", INK, SW, fill=INK)
    T(sx + strip / 2, y + h / 2 + 2.1, label, 6.2, "middle", bold=True, color=WHITE)
    y0 = y + h / 2 - (len(rows) - 1) * 3.4 + 2.1
    for j, r_ in enumerate(rows):
        T(sx + strip + 2.2, y0 + j * 6.8, r_, 6, maxw=w - strip - 4)
    return y + h / 2

ST0 = JOIN_Y + 3.5
stages = [("$Φ$_{str}", ["Scope · Attachment"], 13.0),
          ("$Φ$_{row}", ["Column · Join · Value · NULL"], 13.0),
          ("$Φ$_{out}", ["Aggregate · Project · Tie"], 13.0)]
# Φ_row may need 2 lines if overflow — try one line first with full SWD
mids, sy = [], ST0
for lab, rows, h in stages:
    # bump height if multi-line
    h = 12.5 + (len(rows) - 1) * 7.0
    mids.append(tax_box(SX, sy, SWD, h, lab, rows))
    sy += h + 2.0
ST_BOT = sy - 2.5

# arrows between stages
yc = ST0
for i in range(len(stages) - 1):
    # recompute h same way
    h = 12.5 + (len(stages[i][1]) - 1) * 7.0
    y1 = yc + h
    c.arrow([(MX, y1), (MX, y1 + 2.0)], hs=2.4)
    yc = y1 + 2.0

# earlier-Φ rail
RAIL = x0 + 4.0
c.line([(SX, mids[0]), (RAIL, mids[0]), (RAIL, mids[2])], r=1.3)
c.arrow([(RAIL, mids[1]), (SX, mids[1])], hs=2.4)
c.arrow([(RAIL, mids[2]), (SX, mids[2])], hs=2.4)
T(SX + SWD - 2, (mids[0] + mids[1]) / 2 + 2.0, "earlier $Φ$", 6, "end", italic=True)

# --- merge + supplement ---
MS_Y = ST_BOT + 5.5
c.arrow([(MX, ST_BOT), (MX, MS_Y)], hs=2.6)
MS_H = 15.0
box(SX + 8, MS_Y, SWD - 16, MS_H, fill=WHITE, stroke=INK, rx=3)
T(MX, MS_Y + 6.0, "merge + supplement", 6.2, "middle", bold=True)
T(MX, MS_Y + 12.4, "cover missing groups", 6, "middle", italic=True)

# --- Φ_raw = final question list + example card ---
OUT_Y = MS_Y + MS_H + 5.5
c.arrow([(MX, MS_Y + MS_H), (MX, OUT_Y)], hs=2.6)

STX, STY = x0 + 3.5, OUT_Y + 1.0
for k, (n, rot) in enumerate([(3, -9), (1, -4), (2, 2)]):
    c.items.append(f'<g transform="rotate({rot} {STX + 6} {STY + 10})">')
    mini_card(STX + k * 0.6, STY + k * 1.6, CARD[n])
    c.items.append("</g>")
T(STX + 7, STY + 22.5, "$Φ_{raw}$", 6.5, "middle")

CX = x0 + 22.0
CY = OUT_Y
CW = pw - 26.0
CH = 38.5
c.line([(STX + 12.5, STY + 3), (CX, CY + 0.5)], GRAY, 0.6, dash="1.5,1.2")
c.line([(STX + 13.5, STY + 13), (CX, CY + min(CH - 0.5, 28))], GRAY, 0.6, dash="1.5,1.2")
box(CX, CY, CW, CH)
c.path(f"M{CX},{CY + 9.5} V{CY + R} Q{CX},{CY} {CX + R},{CY} H{CX + CW - R} "
       f"Q{CX + CW},{CY} {CX + CW},{CY + R} V{CY + 9.5} Z", INK, SW, fill=BLUE)
T(CX + CW / 2 - 1.4, CY + 7.0, "Aggregate · $h$ = 'decrease rate'", 6, "middle",
  color=WHITE, maxw=CW - 3.2)
tag(CX + CW, CY, 2)
T(CX + 2.5, CY + 17.5, "$p$₁: (Nov−Dec)/Nov, sums", 6, maxw=CW - 4)
c.line([(CX + 2, CY + 23.2), (CX + CW - 2, CY + 23.2)], GRAY, 0.5)
T(CX + 2.5, CY + 29.5, "$p$₂: other reading", 6, maxw=CW - 4)
T(CX + 2.5, CY + 35.8, "span · type · ≥2 readings", 6, italic=True, maxw=CW - 4)

# ---------------------------------------------------------------- panel 2
x0, pw = P[1]
GX, GY = x0 + 1.5, 100.0
cols = [
    (45.0, ["Q1 Existence"], ["Col · Join ·", "Val · NULL"],
     ["no match →", "drop"]),
    (48.0, ["Q2 Difference"], ["Scope · Attach ·", "Val · NULL"],
     ["same result", "→ Drop φ"]),
    (45.0, ["Q3 Relevance"], ["all nine types"],
     ["same output", "→ Drop φ"]),
]
CT, CODE_Y, CB = GY + 2, 153.0, 181.0
BAR = (GX + 2, 185.0, 0, 15.6)
cx_ = GX + 2
col_pos = []
for k, (cw, title, types, code) in enumerate(cols):
    box(cx_, CT, cw, CB - CT, stroke=INK)
    ic = cx_ + cw / 2
    if k == 0:
        c.cylinder(ic - 5.5, CT + 3.5, 10, 12)
        magnifier(ic + 4.6, CT + 12.2)
    elif k == 2:
        c.rect(ic - 11, CT + 4, 9, 11, rx=1, fill=INK)
        for dy in (5.5, 9.5, 13.5):
            c.line([(ic - 2, CT + dy), (ic + 3, CT + 9.5)], INK, 0.5)
        T(ic + 6.5, CT + 11.6, "=", 7, "middle", bold=True)
    else:
        for dx in (-9.5, 3.5):
            c.rect(ic + dx, CT + 3.2, 6, 5, rx=0.8, fill=WHITE, stroke=INK, sw=0.55)
            c.line([(ic + dx + 1.2, CT + 5.0), (ic + dx + 4.8, CT + 5.0)], INK, 0.4)
            c.line([(ic + dx + 1.2, CT + 6.5), (ic + dx + 3.6, CT + 6.5)], INK, 0.4)
        for dy in (4.5, 5.7, 6.9):
            c.line([(ic - 1.8, CT + dy), (ic + 1.8, CT + dy)], INK, 0.5)
        c.cylinder(ic - 4.5, CT + 9.6, 9, 7.6)
    ty = CT + 23.5
    for j, t_ in enumerate(title):
        T(ic, ty + j * 7.2, t_, 6.5, "middle", bold=True, maxw=cw - 2)
    ty += len(title) * 7.2
    for j, t_ in enumerate(types):
        T(ic, ty + j * 6.8, t_, 6, "middle", italic=True, maxw=cw - 0.8)
    box(cx_ + 1.2, CODE_Y, cw - 2.4, CB - CODE_Y - 1.5, fill=BG, rx=2)
    if k == 0:
        c.rect(cx_ + 1.2, CODE_Y, 2.2, CB - CODE_Y - 1.5, rx=0.8, fill=BLUE_L)
    for j, ln in enumerate(code):
        T(cx_ + 4.0 if k == 0 else cx_ + 2.6, CODE_Y + 6.7 + j * 6.8, f"`{ln}`", 6,
          maxw=cw - (5.2 if k == 0 else 3.8))
    col_pos.append((cx_, cw))
    cx_ += cw + 2
GW = cx_ - GX
box(GX, GY, GW, BAR[1] + BAR[3] + 2.5 - GY, fill="none", stroke=GRAY)
box(GX + 2, BAR[1], GW - 4, BAR[3], fill=WHITE, stroke=GRAY, rx=2)
T(GX + 5, BAR[1] + 10.0, "only on conclusive evidence; else keep", 6, italic=True, maxw=GW - 9)
GBOT = BAR[1] + BAR[3] + 2.5

# remove
RPX, RPY = GX + 4, 218.0
c.arrow([(RPX + 16, GBOT), (RPX + 16, RPY)], GRAY, 1.0)
pill(RPX, RPY, 36, 11, GRAY)
trash(RPX + 7.5, RPY + 5.6)
T(RPX + 13, RPY + 7.6, "Discard", 6.5, bold=True)
T(RPX + 44, RPY + 7.6, "inconclusive → keep", 6, italic=True)

# P1 -> P2
c.arrow([(P[0][0] + P[0][1] - 2, 210.0), (GX, 210.0)], INK, THICK)

# ---------------------------------------------------------------- panel 3
x0, pw = P[2]
SCX, SCY0, SCW, SCH = x0 + 19, 101.0, 30.0, 30.0
JY = SCY0 + SCH / 2
c.arrow([(GX + GW, JY), (SCX, JY)], INK, THICK)
for k, n in enumerate((2, 3)):
    tag(x0 + 3 + k * 8.2, JY, n, r=3.4)
T((P[1][0] + P[1][1] + x0) / 2, JY - 4.2, "$Φ$", 7, "middle")
box(SCX, SCY0, SCW, SCH, stroke=INK)
T(SCX + SCW / 2, JY - 1.3, "Trained", 6.5, "middle", bold=True)
T(SCX + SCW / 2, JY + 6.0, "scorer", 6.5, "middle", bold=True)

BX0 = x0 + 52
rows3 = [(2, SCY0 + 4.5, [(38, BLUE), (2.5, GRAY)], "$H_{norm}$ = 0.19", x0 + pw - 10),
         (3, SCY0 + 22.5, [(22, ORANGE), (20, ORANGE)], "$H_{norm}$ = 0.99", x0 + pw - 4)]
tag_pos = {}
for n, ry, bars, lab, tx in rows3:
    c.arrow([(SCX + SCW, ry + 1.8), (BX0 - 2, ry + 1.8)], hs=2.8)
    for j, (ln, col) in enumerate(bars):
        c.rect(BX0, ry + j * 4.7 - 0.0, ln, 3.6, rx=0.6, fill=col)
    T(BX0, ry + 14.4, lab, 6.5)
    tag(tx, ry + 2.5, n)
    tag_pos[n] = (tx, ry + 2.5)

FSY = 145.0
box(x0 + 3, FSY, pw - 6, 11.5, stroke=GRAY, rx=2)
T(x0 + pw / 2, FSY + 8.3, "$H_{norm}(φ) = −(1 / log m) Σ_{j} w_{j} log w_{j}$", 6.5, "middle",
  maxw=pw - 8)

DCX, DCY, DHW, DHH = x0 + 28, 175.0, 25.0, 12.0
c.arrow([(DCX, FSY + 11.5), (DCX, DCY - DHH)], hs=2.8)
c.path(f"M{DCX},{DCY - DHH} L{DCX + DHW},{DCY} L{DCX},{DCY + DHH} L{DCX - DHW},{DCY} Z",
       INK, SW, fill=WHITE)
T(DCX, DCY + 2.2, "$H_{norm}$ ≤ $θ$ ?", 6.5, "middle", maxw=2 * DHW - 10)

APX, APW = x0 + 64, 44.0
c.arrow([(DCX + DHW, DCY), (APX, DCY)], hs=3)
T(DCX + DHW + 2, DCY - 5.2, "yes", 6, italic=True)
tag((DCX + DHW + APX) / 2 + 0.5, DCY, 2, r=3.4)
pill(APX, DCY - 5.5, APW, 11, BLUE)
T(APX + APW / 2, DCY + 2.2, "Auto($p_{j}^{*}$)", 6.5, "middle", bold=True, color=WHITE)

NY1, NY2 = 201.0, 223.0
QX = x0 + 36
QW = pw - 36
c.line([(DCX, DCY + DHH), (DCX, NY1)], r=0)
T(DCX - 2, DCY + DHH + 7.2, "no", 6, "end", italic=True)
c.arrow([(DCX, NY1), (QX, NY1)], hs=3)
pill(QX, NY1 - 5.5, QW, 11, ORANGE)
bubble(QX + 6.4, NY1 - 0.3)
T(QX + 11.5, NY1 + 2.1, "Ask → $r(φ) ∈ P ∪ {⊥}$", 6, bold=True, maxw=QW - 13)
iw = T(QX + 2, NY1 + 12.4, "to the user", 6, italic=True)
tag(QX + 2 + iw + 5.5, NY1 + 10.2, 3, r=3.4)

TX = x0 + 10
ty_edge = DCY + DHH * (1 - (DCX - TX) / DHW)
c.arrow([(TX, PB), (TX, ty_edge)], INK, 0.75, dash="2.2,1.4", hs=3, cap="butt")
T(TX + 3, PB - 5.5, "$θ^{*}$ on validation ($agr ≥ α$)", 6)

# ---------------------------------------------------------------- panel 4
x0, pw = P[3]
WPX, WPW = x0 + 50, 34.0
pill(WPX, PT + 4, WPW, 10, BLUE_L)
T(WPX + WPW / 2, PT + 11.1, "Write to $E$", 6, "middle", bold=True)

EX, EY, EW = x0 + 3, 99.0, pw - 6
items = [
    (BLUE_L, ["Birthday is stored", "as '1959-02-18'."]),
    (BLUE, ["'decrease rate':", "<desc. of p₁>."]),
    (ORANGE, ["'total cholesterol':", "<desc. of the", "reading the user", "selects>."]),
]
LEAD = 6.6
y = EY + 22.0
item_mid = []
for col, lns in items:
    top = y - 5.0
    bot = y + (len(lns) - 1) * LEAD + 1.8
    item_mid.append((col, top, bot, y, lns))
    y = bot + 6.6
EH = item_mid[-1][2] + 2.5 - EY
box(EX, EY, EW, EH, stroke=INK)
for col, top, bot, y0, lns in item_mid:
    c.rect(EX + 3, top, 2.2, bot - top, rx=0.8, fill=col)
    for j, ln in enumerate(lns):
        T(EX + 7.2, y0 + j * LEAD, f"`{ln}`", 6, maxw=EW - 8.5)
T(EX + EW / 2, EY + 7.6, "!{$E′$ = $E$ ⊕}", 7, "middle")
T(EX + EW / 2, EY + 14.0, "clarification sentences", 6, "middle")
c.arrow([(WPX + WPW / 2, PT + 14), (WPX + WPW / 2, EY)], BLUE_L, 1.1, hs=3)

EB = EY + EH
PRY, PRH = EB + 8, 13.0
c.arrow([(EX + EW / 2, EB), (EX + EW / 2, PRY)], hs=3)
box(EX, PRY, EW, PRH, fill=INK, stroke=INK)
T(EX + EW / 2, PRY + 8.8, "!{Text-to-SQL parser}", 6.5, "middle", color=WHITE)
T(EX + 1, PRY + PRH + 8.0, "Parser($Q$, $S$, $E′$)", 6, italic=True)
T(EX + 1, PRY + PRH + 14.6, "", 6, italic=True)
SQX, SQY = x0 + 12, PRY + PRH + 19.5
SQW, SQH = x0 + pw - 2 - SQX, 23.5
c.arrow([(SQX + SQW - 8, PRY + PRH), (SQX + SQW - 8, SQY)], hs=3)
box(SQX, SQY, SQW, SQH, stroke=GREEN)
for j, ln in enumerate(["SELECT … T-CHO …", "FROM Patient JOIN …", "WHERE Birthday = …"]):
    T(SQX + 2.2, SQY + 7.3 + j * 6.8, f"`{ln}`", 6, maxw=SQW - 3)
check(SQX + SQW, SQY)
T(x0 + 6.5, SQY + 14, "$ŷ$", 8, "middle")
T(x0 + 3, PB - 2.8, "1 question to the user", 6, maxw=pw - 4)

# P3 -> P4 coloured hand-offs
G34 = (P[2][0] + P[2][1] + x0) / 2
mid2 = (item_mid[1][1] + item_mid[1][2]) / 2
mid3 = (item_mid[2][1] + item_mid[2][2]) / 2
c.arrow([(APX + APW, DCY), (G34 - 1.6, DCY), (G34 - 1.6, mid2), (EX, mid2)], BLUE, 1.1, r=2.5)
c.arrow([(QX + QW, NY1), (G34 + 1.6, NY1), (G34 + 1.6, mid3), (EX, mid3)], ORANGE, 1.1, r=2.5)

# ---------------------------------------------------------------- connectors
c.items.append("</g>")
C1L = col_pos[0][0]
Y1A, Y1B = CT + 8.0, CT + 19.0
LX1, LX2 = P[0][0] + P[0][1] + 1.6, P[0][0] + P[0][1] + 5.6
tag(C1L, Y1B - SHIFT, 1)
s1 = span_x[1][0] + span_x[1][1] / 2
s2 = span_x[2][0] + span_x[2][1] / 2
s3 = span_x[3][0] + span_x[3][1] / 2
J = AY1 + 4.5
dotted([(s1, QY + 2.6), (s1, J + 4), (LX1, J + 4), (LX1, Y1B - SHIFT), (C1L - 3.8, Y1B - SHIFT)], BLUE_L)
dotted([(s2, QY + 2.6), (s2, J + 2), (tag_pos[2][0], J + 2),
        (tag_pos[2][0], tag_pos[2][1] - 3.8 - SHIFT)], BLUE)
dotted([(s3, QY + 2.6), (s3, J), (tag_pos[3][0], J), (tag_pos[3][0], tag_pos[3][1] - 3.8 - SHIFT)], ORANGE)
c.items.append(f'<g transform="translate(0,{-SHIFT})">')

# write-to-E arc: from the Content check, over panel 3, into panel 4
ARC_Y = 72.5
c.arrow([(C1L, Y1A), (LX2, Y1A), (LX2, ARC_Y), (WPX + WPW / 2, ARC_Y), (WPX + WPW / 2, PT + 4)],
        BLUE_L, 1.1, r=3, halo=2.2)
tag(P[2][0] + 30, ARC_Y, 1, r=3.4)
c.items.append("</g>")

for w_ in c.warn:
    print("WARN", w_)
c.save("figure/overview", W_IN, H_IN)
print("wrote figure/overview.{svg,pdf,png}")


