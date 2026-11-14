"""Motivating example: asking every ambiguity vs. selective clarification.

Single-column figure, 3.5 in wide; height follows the content.  No math
symbols, Greek letters, variable names or numeric scores appear in it.
"""

from pathlib import Path
from figlib import Canvas

# Soft ICDE-friendly palette (warmer, less chalky)
BLUE_L = "#6CB6E3"
BLUE = "#2F7FB8"
ORANGE = "#E8922A"
ORANGE_FILL = "#FFE6C2"
ORANGE_SOFT = "#FFD9A0"
GREEN = "#3BAF9F"
GREEN_SOFT = "#E6F6F2"
GRAY = "#C9CED4"
BG = "#F3F6F9"
BG_LEFT = "#FFF9F1"
BG_RIGHT = "#F2F7FB"
INK = "#2A3138"
MUTED = "#6B7580"
WHITE = "#FFFFFF"

W_IN = 3.5
W = W_IN * 72
SW = 0.7
R = 5.5
FS = 7.0
LEAD = 8.4

c = Canvas(W, 1000, stroke=SW, ink=INK)
T = c.text
COL = {1: BLUE_L, 2: BLUE, 3: ORANGE}
NUM_TXT = {1: INK, 2: WHITE, 3: WHITE}


def num(cx, cy, n, r=4.8):
    # single solid disc
    c.circle(cx, cy, r, fill=COL[n])
    T(cx, cy + 2.55, str(n), FS, "middle", bold=True, color=NUM_TXT[n])


def rbox(x, y, w, h, fill=WHITE, stroke=INK, rx=R, dash=None, shadow=False):
    c.rect(x, y, w, h, rx=rx, fill=fill, stroke=stroke, dash=dash)


def lines_at(x, y_top, rows, anchor="start", **kw):
    for j, r_ in enumerate(rows):
        T(x, y_top + j * LEAD, r_, FS, anchor, **kw)


def qmark(cx, cy, color=ORANGE):
    c.circle(cx, cy, 4.4, fill=ORANGE_SOFT, stroke=color, sw=0.85)
    T(cx, cy + 2.7, "?", FS + 0.6, "middle", bold=True, color=color)


def bubble_icon(cx, cy, color=INK):
    c.rect(cx - 3.5, cy - 2.7, 7.0, 4.6, rx=2.2, fill="#FFF7EA", stroke=color, sw=0.7)
    # cute dots inside
    for dx in (-1.6, 0.0, 1.6):
        c.circle(cx + dx, cy - 0.4, 0.55, fill=color)
    c.path(f"M{cx - 1.4},{cy + 1.85} L{cx - 2.4},{cy + 3.55} L{cx + 0.35},{cy + 1.85}",
           color, 0.55, fill=color)


def check(cx, cy, r=4.6):
    c.circle(cx, cy, r + 0.8, fill=GREEN_SOFT, stroke=None)
    c.circle(cx, cy, r, fill=GREEN, stroke=WHITE, sw=0.75)
    c.line([(cx - 1.95, cy + 0.2), (cx - 0.35, cy + 1.6), (cx + 2.15, cy - 1.4)], WHITE, 1.15)


def spark(cx, cy, color=ORANGE):
    """Tiny decorative spark near badges."""
    c.path(f"M{cx},{cy - 2.2} L{cx + 0.55},{cy - 0.55} L{cx + 2.2},{cy} "
           f"L{cx + 0.55},{cy + 0.55} L{cx},{cy + 2.2} L{cx - 0.55},{cy + 0.55} "
           f"L{cx - 2.2},{cy} L{cx - 0.55},{cy - 0.55} Z", color, 0.4, fill=color)


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
rbox(M, B1Y, W - 2 * M, B1H, fill=BG, stroke=None, rx=7)
# soft accent strip on left of query band
c.rect(M, B1Y, 3.2, B1H, rx=1.6, fill=BLUE_L, stroke=None)
for k, ln in enumerate(layout):
    by = QY0 + k * QLEAD
    for x_, txt, n, w_ in ln:
        if n:
            num(x_ + 4.3, by - 2.4, n)
            tx = x_ + NUMW
            tw_ = w_ - NUMW
            # soft highlight under span
            c.rect(tx - 1.0, by - 6.0, tw_ + 2.0, 9.2, rx=2.2, fill=WHITE, stroke=None)
            c.line([(tx, by + 2.0), (tx + tw_, by + 2.0)], COL[n], 1.7, cap="butt")
            T(tx, by, txt, FS, italic=True)
        else:
            T(x_, by, txt, FS, italic=True)
DBX = W - M - DBW - 2
# cute database: soft fill + tiny magnifier
c.cylinder(DBX + 7, B1Y + B1H / 2 - 12, 16, 15, fill="#EAF4FB", stroke=BLUE)
c.circle(DBX + 24.5, B1Y + B1H / 2 + 2.5, 3.0, fill="#EEF6FB", stroke=BLUE, sw=0.7)
c.circle(DBX + 24.5, B1Y + B1H / 2 + 2.5, 1.15, fill="none", stroke=BLUE, sw=0.45)
c.line([(DBX + 26.7, B1Y + B1H / 2 + 4.7), (DBX + 28.6, B1Y + B1H / 2 + 6.6)], BLUE, 1.1)
T(DBX + 15, B1Y + B1H / 2 + 11, "Database", FS, "middle", color=MUTED)

# ====================================================================== band 2
B2Y = B1Y + B1H + 10
LX, LW = M, 74.0
RX = LX + LW + 9
RW = W - M - RX
SEPX = LX + LW + 4.5

# column title pills
def title_pill(cx, y, text, fill, fg=INK):
    tw = c.tw(text, 7.3, bold=True) + 14
    x0 = cx - tw / 2
    c.rect(x0, y, tw, 12.5, rx=6.5, fill=fill, stroke=None)
    T(cx, y + 9.0, text, 7.3, "middle", bold=True, color=fg)

title_pill(LX + LW / 2, B2Y, "Ask every ambiguity", ORANGE_SOFT, INK)
title_pill(RX + RW / 2, B2Y, "Selective clarification (ours)", "#DCEAF5", BLUE)

FB = 6.3
BLEAD = 7.4
HDR = 13.5
asks = [["Q1: How is", "'1959/2/18'", "written in SQL?"],
        ["Q2: How is", "'decrease rate'", "computed?"],
        ["Q3: What should", "'total cholesterol'", "return?"]]

cards = [
    (1, "Value", "Settled by the data", [
        ("code", ("`Birthday = '1959/2/18'`", "0 rows", True)),
        ("code", ("`Birthday = '1959-02-18'`", "1 patient", False)),
        ("code", ("`date(Birthday) = '1959-02-18'`", "same patient", False)),
        ("note", "No match: removed. Equal results: one kept"),
    ]),
    (2, "Aggregate", "Resolved automatically", [
        ("note", "Base month, and sum or average of the monthly tests"),
        ("bar", (27, BLUE, "(Nov − Dec) / Nov, monthly sums")),
        ("bar", (3, GRAY, "(Nov − Dec) / Dec, monthly sums")),
        ("bar", (2, GRAY, "(Nov − Dec) / Nov, monthly averages")),
        ("bar", (1.5, GRAY, "(Nov − Dec) / Dec, monthly averages")),
    ]),
    (3, "Project", "Ask the user", [
        ("note", "Output columns not stated"),
        ("bar", (16, ORANGE, "The rate only")),
        ("bar", (14.5, ORANGE, "The rate and both monthly values")),
    ]),
]
OUT_COL = {1: BLUE_L, 2: BLUE, 3: ORANGE}
OUT_TXT = {1: INK, 2: WHITE, 3: WHITE}
CARD_TINT = {1: "#F3F9FD", 2: "#F2F7FB", 3: "#FFEFD6"}

ROW_GAP = 6.0
y = B2Y + 16
row_spans = []
for (n, typ, outcome, body), ask in zip(cards, asks):
    h = HDR + len(body) * BLEAD + 4.0
    # right: soft tinted card with shadow
    rbox(RX, y, RW, h, fill=CARD_TINT[n], stroke="#D7DEE6", shadow=False)
    # left accent rail
    c.rect(RX, y + 3, 2.4, h - 6, rx=1.2, fill=OUT_COL[n], stroke=None)
    num(RX + 9.0, y + 8.0, n)
    tw_ = c.tw(typ, FS)
    c.rect(RX + 15.5, y + 3.2, tw_ + 7, 9.6, rx=4.8, fill=WHITE, stroke="#D7DEE6", sw=0.55)
    T(RX + 19, y + 10.2, typ, FS, color=MUTED)
    pw_ = c.tw(outcome, 6.5, bold=True) + 10
    px = RX + RW - pw_ - 3.5
    c.rect(px, y + 3.2, pw_, 9.6, rx=4.8, fill=OUT_COL[n])
    T(px + pw_ / 2, y + 10.0, outcome, 6.5, "middle", bold=True, color=OUT_TXT[n])
    by = y + HDR + 5.8
    for kind, p in body:
        if kind == "code":
            sql, res, bad = p
            T(RX + 7, by, sql, FB, color=GRAY if bad else INK, maxw=RW - 46)
            T(RX + RW - 5, by, res, FB, "end", bold=not bad, color=GRAY if bad else INK)
            if bad:
                sw_ = c.tw(sql, FB)
                c.line([(RX + 7, by - 2.0), (RX + 7 + sw_, by - 2.0)], GRAY, 0.6, cap="butt")
        elif kind == "note":
            T(RX + 7, by, p, FB, italic=True, color=MUTED, maxw=RW - 10)
        else:
            ln, col, lab = p
            c.rect(RX + 7, by - 4.4, ln, 4.2, rx=1.4, fill=col)
            T(RX + 38, by, lab, FB, maxw=RW - 42)
        by += BLEAD
    if n != 1:
        c.line([(RX + 6.2, y + HDR + 1.6 + BLEAD), (RX + 6.2, y + h - 3.0)], "#B8C2CC", 0.7)

    # left: Always-Ask speech bubble, vertically centred
    bh = len(ask) * LEAD + 8
    bub_y = y + (h - bh) / 2 - 1.5
    rbox(LX, bub_y, LW, bh, fill=ORANGE_FILL, stroke=ORANGE, rx=8)
    tx0 = LX + 12
    # soft bubble tail
    c.path(f"M{tx0},{bub_y + bh - 0.5} L{tx0 - 2.2},{bub_y + bh + 4.2} L{tx0 + 5.5},{bub_y + bh - 0.5}",
           ORANGE, SW, fill=ORANGE_FILL)
    c.line([(tx0 + 0.7, bub_y + bh), (tx0 + 4.8, bub_y + bh)], ORANGE_FILL, 1.3, cap="butt")
    qmark(LX + 9, bub_y + bh / 2)
    lines_at(LX + 16, bub_y + 4.0 + 5.6, ask, maxw=LW - 19)
    row_spans.append((y, h))
    y += h + ROW_GAP

ROWS_END = y - ROW_GAP
BADGE_Y, BADGE_H = ROWS_END + 7, 13.0
badges = {}
for (x0, w0), lab, fill in [((LX, LW), "3 questions", ORANGE_SOFT),
                            ((RX, RW), "1 question to the user", "#DCEAF5")]:
    bw = c.tw(lab, FS) + 22
    bx = x0 + (w0 - bw) / 2
    rbox(bx, BADGE_Y, bw, BADGE_H, rx=BADGE_H / 2, fill=fill, stroke=ORANGE if lab.startswith("3") else BLUE)
    bubble_icon(bx + 8.5, BADGE_Y + BADGE_H / 2 - 0.2, ORANGE if lab.startswith("3") else BLUE)
    T(bx + 15, BADGE_Y + 9.0, lab, FS)
    badges[lab[0]] = bx + bw / 2
# dashed divider with tiny beads
c.line([(SEPX, B2Y + 14), (SEPX, BADGE_Y + BADGE_H)], GRAY, 0.7, dash="1.8,2.2")
for yy in (B2Y + 28, (B2Y + BADGE_Y) / 2 + 20, BADGE_Y - 8):
    c.circle(SEPX, yy, 1.35, fill=WHITE, stroke=GRAY, sw=0.6)

# ====================================================================== band 3
B3Y = BADGE_Y + BADGE_H
PBY = B3Y + 15
PBW, PBH = 128.0, 16.0
PBX = M + (W - 2 * M - PBW) / 2
for key in ("3", "1"):
    bx_ = badges[key]
    ent = PBX + 14 if key == "3" else PBX + PBW - 14
    c.arrow([(bx_, BADGE_Y + BADGE_H), (bx_, B3Y + 8), (ent, B3Y + 8), (ent, PBY)],
            hs=3.2, r=3.0, color="#8A949E")
rbox(PBX, PBY, PBW, PBH, rx=8, fill=WHITE, stroke="#D0D7DE")
T(PBX + PBW / 2, PBY + 10.8, "Clarified question → NL2SQL parser", FS, "middle", maxw=PBW - 6)

sq_lines = ["`SELECT (SUM(...Nov...) - SUM(...Dec...)) / SUM(...Nov...)`",
            "`FROM Patient JOIN Laboratory ...`",
            "`WHERE Birthday = '1959-02-18'`"]
SQW = max(c.tw(s, FB) for s in sq_lines) + 12
SQH = len(sq_lines) * BLEAD + 6
SQX = M + (W - 2 * M - SQW) / 2
SQY = PBY + PBH + 16
c.arrow([(W / 2, PBY + PBH), (W / 2, SQY)], hs=3.2, color="#8A949E")
rbox(SQX, SQY, SQW, SQH, stroke=GREEN, fill=GREEN_SOFT, rx=7)
for j, s in enumerate(sq_lines):
    T(SQX + 6, SQY + 8.2 + j * BLEAD, s, FB)
check(SQX + SQW - 1, SQY)
lab = "Correct SQL"
lw = c.tw(lab, FS, bold=True)
# label left of check; spark left of the label so it never hits the L
T(SQX + SQW - 10, SQY - 3.2, lab, FS, "end", bold=True, color=GREEN)
spark(SQX + SQW - 10 - lw - 5.5, SQY - 5.0, GREEN)

H = SQY + SQH + M + 2
c.h = H
for w_ in c.warn:
    print("WARN", w_)
c.save(str(Path(__file__).resolve().parent / "motivation"), W_IN, round(H / 72, 4))
print(f"wrote {Path(__file__).resolve().parent / 'motivation'}.{{svg,pdf,png}}  ({W_IN} in x {H / 72:.2f} in)")
