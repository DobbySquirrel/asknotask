"""Motivating example: Always-Ask vs. selective clarification.

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
LX, LW = M, 74.0
RX = LX + LW + 9
RW = W - M - RX
SEPX = LX + LW + 4.5
T(LX + LW / 2, B2Y + 6, "Always-Ask", 7.5, "middle", bold=True)
T(RX + RW / 2, B2Y + 6, "Selective clarification (ours)", 7.5, "middle", bold=True, maxw=RW)

FB = 6.3          # card body font size
BLEAD = 7.4
HDR = 13.0
asks = [["Q1: How is", "'1959/2/18'", "written in SQL?"],
        ["Q2: How is", "'decrease rate'", "computed?"],
        ["Q3: What should", "'total cholesterol'", "return?"]]

# Each card: (n, type, outcome, body).  Body rows are (kind, payload).
cards = [
    (1, "Value", "Settled by the data", [
        ("code", ("`Birthday = '1959/2/18'`", "0 rows", True)),
        ("code", ("`Birthday = '1959-02-18'`", "1 patient", False)),
        ("code", ("`date(Birthday) = '1959-02-18'`", "1 patient", False)),
        ("note", "First form fails, the other two agree"),
    ]),
    (2, "Aggregate", "Resolved automatically", [
        ("note", "Several `T-CHO` tests per month"),
        ("bar", (27, BLUE, "(Nov − Dec) / Nov, monthly sums")),
        ("bar", (3, GRAY, "(Nov − Dec) / Dec, monthly sums")),
        ("bar", (2, GRAY, "(Nov − Dec) / Nov, monthly averages")),
    ]),
    (3, "Project", "Ask the user", [
        ("note", "Output columns not stated"),
        ("bar", (16, ORANGE, "The rate only")),
        ("bar", (14.5, ORANGE, "The rate and both monthly sums")),
    ]),
]
OUT_COL = {1: BLUE_L, 2: BLUE, 3: ORANGE}
OUT_TXT = {1: INK, 2: WHITE, 3: INK}

ROW_GAP = 5.0
y = B2Y + 12
row_spans = []
for (n, typ, outcome, body), ask in zip(cards, asks):
    h = HDR + len(body) * BLEAD + 3.5
    # right: card
    rbox(RX, y, RW, h)
    num(RX + 7.5, y + 7.5, n)
    tw_ = c.tw(typ, FS)
    rbox(RX + 14, y + 2.8, tw_ + 6, 9.4, fill=BG, stroke=GRAY, rx=2)
    T(RX + 17, y + 10, typ, FS)
    pw_ = c.tw(outcome, 6.5, bold=True) + 9
    px = RX + RW - pw_ - 3
    c.rect(px, y + 2.8, pw_, 9.4, rx=4.7, fill=OUT_COL[n])
    T(px + pw_ / 2, y + 9.6, outcome, 6.5, "middle", bold=True, color=OUT_TXT[n])
    by = y + HDR + 5.6
    for kind, p in body:
        if kind == "code":
            sql, res, bad = p
            T(RX + 5, by, sql, FB, color=GRAY if bad else INK, maxw=RW - 44)
            T(RX + RW - 5, by, res, FB, "end", bold=not bad, color=GRAY if bad else INK)
            if bad:
                sw_ = c.tw(sql, FB)
                c.line([(RX + 5, by - 2.0), (RX + 5 + sw_, by - 2.0)], GRAY, 0.6, cap="butt")
        elif kind == "note":
            T(RX + 5, by, p, FB, italic=True, maxw=RW - 10)
        else:
            ln, col, lab = p
            c.rect(RX + 5, by - 4.3, ln, 4.0, rx=0.8, fill=col)
            T(RX + 36, by, lab, FB, maxw=RW - 40)
        by += BLEAD
    if n != 1:
        c.line([(RX + 4.4, y + HDR + 1.4 + BLEAD), (RX + 4.4, y + h - 2.5)], INK, 0.6)

    # left: Always-Ask speech bubble, vertically centred on the card
    bh = len(ask) * LEAD + 7
    bub_y = y + (h - bh) / 2 - 1.5
    rbox(LX, bub_y, LW, bh, fill=ORANGE_FILL, stroke=ORANGE)
    tx0 = LX + 11
    c.path(f"M{tx0},{bub_y + bh - 0.4} L{tx0 - 2},{bub_y + bh + 4} L{tx0 + 5},{bub_y + bh - 0.4}",
           ORANGE, SW, fill=ORANGE_FILL)
    c.line([(tx0 + 0.6, bub_y + bh), (tx0 + 4.4, bub_y + bh)], ORANGE_FILL, 1.2, cap="butt")
    qmark(LX + 8, bub_y + bh / 2)
    lines_at(LX + 15, bub_y + 3.5 + 5.6, ask, maxw=LW - 17)
    row_spans.append((y, h))
    y += h + ROW_GAP

ROWS_END = y - ROW_GAP
BADGE_Y, BADGE_H = ROWS_END + 6, 12.0
badges = {}
for (x0, w0), lab in [((LX, LW), "3 questions"), ((RX, RW), "1 question to the user")]:
    bw = c.tw(lab, FS) + 18
    bx = x0 + (w0 - bw) / 2
    rbox(bx, BADGE_Y, bw, BADGE_H, rx=BADGE_H / 2, stroke=ORANGE)
    bubble_icon(bx + 7.5, BADGE_Y + BADGE_H / 2 - 0.3, ORANGE)
    T(bx + 13, BADGE_Y + 8.5, lab, FS)
    badges[lab[0]] = bx + bw / 2
c.line([(SEPX, B2Y - 1), (SEPX, BADGE_Y + BADGE_H)], GRAY, 0.75, dash="2.5,2")

# ====================================================================== band 3
B3Y = BADGE_Y + BADGE_H
PBY = B3Y + 14
PBW, PBH = 124.0, 15.0
PBX = M + (W - 2 * M - PBW) / 2
for key in ("3", "1"):
    bx_ = badges[key]
    ent = PBX + 12 if key == "3" else PBX + PBW - 12
    c.arrow([(bx_, BADGE_Y + BADGE_H), (bx_, B3Y + 7), (ent, B3Y + 7), (ent, PBY)], hs=3.2, r=2.5)
rbox(PBX, PBY, PBW, PBH)
T(PBX + PBW / 2, PBY + 10, "Clarified question → NL2SQL parser", FS, "middle", maxw=PBW - 4)

sq_lines = ["`SELECT (SUM(…) - SUM(…)) / SUM(…)`",
            "`FROM Patient JOIN Laboratory …`",
            "`WHERE Birthday = '1959-02-18'`"]
SQW = max(c.tw(s, FB) for s in sq_lines) + 10
SQH = len(sq_lines) * BLEAD + 5
SQX = M + (W - 2 * M - SQW) / 2
SQY = PBY + PBH + 15
c.arrow([(W / 2, PBY + PBH), (W / 2, SQY)], hs=3.2)
rbox(SQX, SQY, SQW, SQH, stroke=GREEN)
for j, s in enumerate(sq_lines):
    T(SQX + 5, SQY + 7.6 + j * BLEAD, s, FB)
check(SQX + SQW - 1, SQY)
T(SQX + SQW - 7, SQY - 3, "Correct SQL", FS, "end", bold=True)

H = SQY + SQH + M
c.h = H
for w_ in c.warn:
    print("WARN", w_)
c.save("figure/motivation", W_IN, round(H / 72, 4))
print(f"wrote figure/motivation.{{svg,pdf,png}}  ({W_IN} in x {H / 72:.2f} in)")
