"""Motivating example: ask-every-ambiguity vs. selective clarification.

Single-column figure, 3.5 in wide; height follows the content.  No math
symbols, Greek letters, variable names or numeric scores appear in it.
"""

from figlib import Canvas

BLUE_L = "#56B4E9"
BLUE = "#0072B2"
ORANGE = "#E69F00"
ORANGE_FILL = "#FBEED1"  # flat tint of #E69F00 (18 %) on white for the question bubbles
GREEN = "#009E73"
GRAY = "#BBBBBB"
BG = "#F4F4F4"
INK = "#333333"
WHITE = "#FFFFFF"

W_IN = 3.5
W = W_IN * 72
SW = 0.75
R = 3
FS = 7.0          # base font size
LEAD = 8.4

c = Canvas(W, 1000, stroke=SW, ink=INK)
T = c.text
COL = {1: BLUE_L, 2: BLUE, 3: ORANGE}
NUM_TXT = {1: INK, 2: WHITE, 3: INK}


def num(cx, cy, n, r=4.3):
    c.circle(cx, cy, r, fill=COL[n])
    T(cx, cy + 2.5, str(n), FS, "middle", bold=True, color=NUM_TXT[n])


def rbox(x, y, w, h, fill=WHITE, stroke=INK, rx=R, dash=None):
    c.rect(x, y, w, h, rx=rx, fill=fill, stroke=stroke, dash=dash)


def lines_at(x, y_top, rows, anchor="start", **kw):
    for j, r_ in enumerate(rows):
        T(x, y_top + j * LEAD, r_, FS, anchor, **kw)


def qmark(cx, cy, color=ORANGE):
    c.circle(cx, cy, 3.9, fill=WHITE, stroke=color, sw=0.75)
    T(cx, cy + 2.5, "?", FS, "middle", bold=True, color=color)


def cylinder_mag(x, y):
    c.cylinder(x, y, 9, 11)
    c.circle(x + 9.5, y + 9.5, 2.6, fill=WHITE, stroke=INK, sw=0.75)
    c.line([(x + 11.4, y + 11.4), (x + 13.4, y + 13.4)], INK, 1.0)


def bubble_icon(cx, cy, color=INK):
    c.rect(cx - 3.2, cy - 2.4, 6.4, 4.2, rx=1.4, fill="none", stroke=color, sw=0.65)
    c.path(f"M{cx - 1.6},{cy + 1.8} L{cx - 2.2},{cy + 3.3} L{cx},{cy + 1.8}", color, 0.65, fill=color)


def check(cx, cy, r=4.2):
    c.circle(cx, cy, r, fill=GREEN)
    c.line([(cx - 1.8, cy + 0.1), (cx - 0.5, cy + 1.4), (cx + 2.0, cy - 1.4)], WHITE, 1.0)


M = 4.0

# ====================================================================== band 1
B1Y = M
DBW = 30
QX0, QX1 = M + 6, W - M - DBW - 12
question = [("For the patient who was", None), ("born on 1959/2/18", 1),
            (", what is the", None), ("decrease rate", 2), ("for his/her", None),
            ("total cholesterol", 3), ("from November to December in 1981?", None)]
toks = []
for txt, n in question:
    if n:
        toks.append((txt, n))
    else:
        toks += [(w_, None) for w_ in txt.split(" ")]
toks[0] = ("“" + toks[0][0], None)
toks[-1] = (toks[-1][0] + "”", None)
SPACE = c.tw(" ", FS, italic=True)
NUMW = 10.5
layout, line, x = [], [], QX0
for txt, n in toks:
    w_ = c.tw(txt, FS, italic=True) + (NUMW if n else 0)
    glue = 0 if txt.startswith(",") or not line else SPACE
    if line and x + glue + w_ > QX1:
        layout.append(line)
        line, x, glue = [], QX0, 0
    line.append((x + glue, txt, n, w_))
    x += glue + w_
layout.append(line)
QY0 = B1Y + 12.5
QLEAD = 11.0
B1H = 12.5 + (len(layout) - 1) * QLEAD + 7.5
rbox(M, B1Y, W - 2 * M, B1H, fill=BG, stroke=None)
for k, ln in enumerate(layout):
    by = QY0 + k * QLEAD
    for x_, txt, n, w_ in ln:
        if n:
            num(x_ + 4.3, by - 2.4, n)
            tx = x_ + NUMW
            tw_ = w_ - NUMW
            c.line([(tx, by + 2.0), (tx + tw_, by + 2.0)], COL[n], 1.6, cap="butt")
            T(tx, by, txt, FS, italic=True)
        else:
            T(x_, by, txt, FS, italic=True)
DBX = W - M - DBW - 2
c.cylinder(DBX + 7, B1Y + B1H / 2 - 12, 16, 15)
T(DBX + 15, B1Y + B1H / 2 + 11, "Database", FS, "middle")

# ====================================================================== band 2
B2Y = B1Y + B1H + 9
LX, LW = M, 96.0
RX = LX + LW + 10
RW = W - M - RX
SEPX = LX + LW + 5
T(LX + LW / 2, B2Y + 6, "Ask every ambiguity", 7.5, "middle", bold=True)
T(RX + RW / 2, B2Y + 6, "Selective clarification (ours)", 7.5, "middle", bold=True, maxw=RW)

ROW_H, ROW_GAP = 36.0, 5.0
ROW0 = B2Y + 12
asks = [["Q1: Which value", "does '1959/2/18'", "mean?"],
        ["Q2: How should", "'decrease rate'", "be computed?"],
        ["Q3: What does", "'total cholesterol'", "refer to?"]]
cards = [
    (1, "Value", "Settled by|the data"),
    (2, "Aggregate", "Resolved|automatically"),
    (3, "Project", "Ask the|user"),
]
CW = 80.0
PW = RW - CW - 8
for k in range(3):
    y = ROW0 + k * (ROW_H + ROW_GAP)
    # left: speech bubble
    bh = len(asks[k]) * LEAD + 7
    by = y + (ROW_H - bh) / 2 - 1.5
    rbox(LX, by, LW, bh, fill=ORANGE_FILL, stroke=ORANGE)
    tx0 = LX + 11
    c.path(f"M{tx0},{by + bh - 0.4} L{tx0 - 2},{by + bh + 4} L{tx0 + 5},{by + bh - 0.4}",
           ORANGE, SW, fill=ORANGE_FILL)
    c.line([(tx0 + 0.6, by + bh), (tx0 + 4.4, by + bh)], ORANGE_FILL, 1.2, cap="butt")
    qmark(LX + 8, by + bh / 2)
    lines_at(LX + 15, by + 3.5 + 5.6, asks[k], maxw=LW - 17)

    # right: ambiguity card + outcome
    n, typ, outcome = cards[k]
    rbox(RX, y, CW, ROW_H)
    num(RX + 7.5, y + 7.5, n)
    tw_ = c.tw(typ, FS)
    rbox(RX + 14, y + 2.8, tw_ + 6, 9.4, fill=BG, stroke=GRAY, rx=2)
    T(RX + 17, y + 10, typ, FS)
    cy = y + 15.5
    if n == 1:
        cylinder_mag(RX + 4.5, cy + 1.5)
        lines_at(RX + 21, cy + 6.8, ["`stored as`", "`'1959-02-18'`"], maxw=CW - 23)
    else:
        bars = [(26, BLUE), (2.5, GRAY)] if n == 2 else [(24, ORANGE), (22.5, ORANGE)]
        for j, (ln, col) in enumerate(bars):
            c.rect(RX + 5, cy + 3 + j * 5.6, ln, 4, rx=0.8, fill=col)
        c.line([(RX + 4.4, cy + 1.5), (RX + 4.4, cy + 15)], INK, 0.6)
        lab = "confident" if n == 2 else "uncertain"
        lines_at(RX + 35, cy + 6.8, ["Model is", lab], maxw=CW - 37)
    px = RX + CW + 8
    ph = 2 * LEAD + 5
    pyy = y + (ROW_H - ph) / 2
    c.arrow([(RX + CW, y + ROW_H / 2), (px, y + ROW_H / 2)], hs=3.2)
    c.rect(px, pyy, PW, ph, rx=ph / 2, fill=COL[n])
    for j, s in enumerate(outcome.split("|")):
        T(px + PW / 2, pyy + 7.6 + j * LEAD, s, FS, "middle", bold=True,
          color=WHITE if n == 2 else INK, maxw=PW - 3)

ROWS_END = ROW0 + 3 * ROW_H + 2 * ROW_GAP
BADGE_Y, BADGE_H = ROWS_END + 6, 12.0
badges = {}
for (x0, w0), lab in [((LX, LW), "3 questions to the user"), ((RX, RW), "1 question to the user")]:
    bw = c.tw(lab, FS) + 18
    bx = x0 + (w0 - bw) / 2
    rbox(bx, BADGE_Y, bw, BADGE_H, rx=BADGE_H / 2, stroke=ORANGE)
    bubble_icon(bx + 7.5, BADGE_Y + BADGE_H / 2 - 0.3, ORANGE)
    T(bx + 13, BADGE_Y + 8.5, lab, FS)
    badges[lab[0]] = bx + bw / 2
c.line([(SEPX, B2Y - 1), (SEPX, BADGE_Y + BADGE_H)], GRAY, 0.75, dash="2.5,2")

# ====================================================================== band 3
B3Y = BADGE_Y + BADGE_H
PBY = B3Y + 22
PBW, PBH = 124.0, 15.0
PBX = M
sq_lines = ["`SELECT …`", "`FROM Patient`", "`JOIN Laboratory …`"]
SQW = max(c.tw(s, FS) for s in sq_lines) + 8
SQX = W - M - SQW
lx_ = badges["3"]
c.arrow([(lx_, BADGE_Y + BADGE_H), (lx_, PBY)], hs=3.2)
T(lx_ + 3, B3Y + 9.6, "3 questions", FS)
rx_ = badges["1"]
ent = PBX + PBW - 14
c.arrow([(rx_, BADGE_Y + BADGE_H), (rx_, B3Y + 12), (ent, B3Y + 12), (ent, PBY)], hs=3.2, r=2.5)
T(rx_ - 4, B3Y + 9.6, "1 question", FS, "end")
rbox(PBX, PBY, PBW, PBH)
T(PBX + PBW / 2, PBY + 10, "Clarified question → NL2SQL parser", FS, "middle", maxw=PBW - 4)

SQH = len(sq_lines) * LEAD + 6
SQY = PBY + PBH / 2 - SQH / 2 + 6
c.arrow([(PBX + PBW, PBY + PBH / 2), (SQX, PBY + PBH / 2)], hs=3.2)
rbox(SQX, SQY, SQW, SQH, stroke=GREEN)
for j, s in enumerate(sq_lines):
    T(SQX + 4, SQY + 8.2 + j * LEAD, s, FS)
check(SQX + SQW - 1, SQY)
T(SQX + SQW - 7, SQY - 3, "Correct SQL", FS, "end", bold=True)

H = SQY + SQH + M
c.h = H
c.save("figure/motivation", W_IN, round(H / 72, 4))
print(f"wrote figure/motivation.{{svg,pdf,png}}  ({W_IN} in x {H / 72:.2f} in)")
