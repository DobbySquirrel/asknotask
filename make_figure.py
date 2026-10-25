"""Generate the system-architecture figure (SVG, PDF, PNG).

All coordinates are in PostScript points; the canvas is 7.16 in x 2.754 in
(515.52 x 198.28 pt, aspect 2.6:1).  Text is positioned with explicit
per-run coordinates measured from Liberation Sans (metric-compatible with
Arial/Helvetica) so the layout is identical in every renderer.
"""

import math
import re
from pathlib import Path

from PIL import ImageFont

# ---------------------------------------------------------------- palette
BLUE = "#0072B2"
LBLUE = "#56B4E9"
ORANGE = "#E69F00"
GREEN = "#009E73"
GRAY = "#BBBBBB"
BG = "#F2F2F2"
INK = "#333333"
WHITE = "#FFFFFF"

W, H = 515.52, 198.28
SW = 0.75  # base stroke
THICK = 1.6

FONT_STACK = "Helvetica, Arial, 'Liberation Sans', sans-serif"
MATH_FONT = "'DejaVu Sans', 'Cambria Math', 'Segoe UI Symbol', sans-serif"
MATH_CHARS = set("⟨⟩⊕")

_FD = "/usr/share/fonts/truetype"
_FONTS = {
    (False, False): ImageFont.truetype(f"{_FD}/liberation/LiberationSans-Regular.ttf", 100),
    (True, False): ImageFont.truetype(f"{_FD}/liberation/LiberationSans-Bold.ttf", 100),
    (False, True): ImageFont.truetype(f"{_FD}/liberation/LiberationSans-Italic.ttf", 100),
    (True, True): ImageFont.truetype(f"{_FD}/liberation/LiberationSans-BoldItalic.ttf", 100),
}
_MATH = ImageFont.truetype(f"{_FD}/dejavu/DejaVuSans.ttf", 100)

out: list[str] = []
WARN: list[str] = []


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ---------------------------------------------------------------- rich text
def parse(markup, bold=False, italic=False):
    """Mini markup: $..$ italic, !{..} bold, _{..} subscript, ^{..} superscript."""
    runs = []
    i, buf = 0, ""
    state = dict(b=bold, i=italic, shift=0)

    def flush():
        nonlocal buf
        if buf:
            runs.append((buf, state["b"], state["i"], state["shift"]))
            buf = ""

    while i < len(markup):
        c = markup[i]
        if c == "$":
            flush()
            state["i"] = not state["i"]
            i += 1
        elif markup.startswith(("_{", "^{", "!{"), i):
            flush()
            j = markup.index("}", i)
            inner = markup[i + 2 : j]
            kind = markup[i]
            b = True if kind == "!" else state["b"]
            sh = state["shift"] if kind == "!" else (-1 if kind == "_" else 1)
            it = state["i"]
            for k, seg in enumerate(inner.split("$")):
                if seg:
                    runs.append((seg, b, it, sh))
                if k < inner.count("$"):
                    it = not it
            i = j + 1
        else:
            buf += c
            i += 1
    flush()
    # split out glyphs that need the math fallback font
    final = []
    for txt, b, it, sh in runs:
        for part in re.split(f"([{''.join(MATH_CHARS)}])", txt):
            if part:
                final.append((part, b, it, sh, part in MATH_CHARS))
    return final


def run_size(size, shift):
    return size * (0.68 if shift else 1.0)


def tw(markup, size, bold=False, italic=False):
    total = 0.0
    for txt, b, it, sh, m in parse(markup, bold, italic):
        f = _MATH if m else _FONTS[(b, it)]
        total += f.getlength(txt) / 100 * run_size(size, sh)
    return total


def text(x, y, markup, size=6, anchor="start", bold=False, italic=False,
         color=INK, maxw=None):
    """Draw one line; y is the baseline."""
    w = tw(markup, size, bold, italic)
    if maxw is not None and w > maxw + 0.05:
        WARN.append(f"overflow {w:.1f}>{maxw:.1f}: {markup!r}")
    if anchor == "middle":
        x -= w / 2
    elif anchor == "end":
        x -= w
    parts = [f'<text font-family="{FONT_STACK}" fill="{color}">']
    cx = x
    for txt, b, it, sh, m in parse(markup, bold, italic):
        s = run_size(size, sh)
        dy = {0: 0, -1: 0.22 * size, 1: -0.38 * size}[sh]
        attrs = f'x="{cx:.2f}" y="{y + dy:.2f}" font-size="{s:.2f}"'
        if b:
            attrs += ' font-weight="bold"'
        if it:
            attrs += ' font-style="italic"'
        if m:
            attrs += f' font-family="{MATH_FONT}"'
        parts.append(f"<tspan {attrs}>{esc(txt)}</tspan>")
        f = _MATH if m else _FONTS[(b, it)]
        cx += f.getlength(txt) / 100 * s
    parts.append("</text>")
    out.append("".join(parts))
    return w


def lines(cx, cy, rows, size=6, lead=1.2, anchor="middle", **kw):
    """Draw several lines vertically centred on cy."""
    n = len(rows)
    step = size * lead
    y0 = cy - (n - 1) * step / 2 + 0.35 * size
    for k, r in enumerate(rows):
        text(cx, y0 + k * step, r, size, anchor, **kw)


# ---------------------------------------------------------------- shapes
def rect(x, y, w, h, rx=2.5, fill=WHITE, stroke=INK, sw=SW, dash=None, extra=""):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    s = f'stroke="{stroke}" stroke-width="{sw}"' if stroke else 'stroke="none"'
    out.append(f'<rect x="{x:.2f}" y="{y:.2f}" width="{w:.2f}" height="{h:.2f}" '
               f'rx="{rx}" fill="{fill}" {s}{d}{extra}/>')


def pill(x, y, w, h, fill, stroke=None):
    rect(x, y, w, h, rx=h / 2, fill=fill, stroke=stroke or fill)


def line(pts, color=INK, sw=SW, dash=None):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    p = " ".join(f"{a:.2f},{b:.2f}" for a, b in pts)
    out.append(f'<polyline points="{p}" fill="none" stroke="{color}" stroke-width="{sw}" '
               f'stroke-linejoin="round" stroke-linecap="round"{d}/>')


def path(d, color=INK, sw=SW, fill="none", dash=None):
    da = f' stroke-dasharray="{dash}"' if dash else ""
    out.append(f'<path d="{d}" fill="{fill}" stroke="{color}" stroke-width="{sw}" '
               f'stroke-linejoin="round" stroke-linecap="round"{da}/>')


def head(tip, frm, color=INK, size=3.4):
    """Filled triangular arrowhead at tip, pointing away from frm."""
    (x1, y1), (x0, y0) = tip, frm
    a = math.atan2(y1 - y0, x1 - x0)
    w = size * 0.42
    bx, by = x1 - size * math.cos(a), y1 - size * math.sin(a)
    px, py = -math.sin(a) * w, math.cos(a) * w
    out.append(f'<polygon points="{x1:.2f},{y1:.2f} {bx + px:.2f},{by + py:.2f} '
               f'{bx - px:.2f},{by - py:.2f}" fill="{color}"/>')
    return bx, by


def arrow(pts, color=INK, sw=SW, dash=None, hs=None, r=0):
    """Polyline with arrowhead at the last point; optional rounded corners."""
    hs = hs or (5.2 if sw >= 1.4 else 3.4)
    tip, prev = pts[-1], pts[-2]
    seg = math.dist(tip, prev)
    bx = tip[0] - (tip[0] - prev[0]) * (hs * 0.8) / seg
    by = tip[1] - (tip[1] - prev[1]) * (hs * 0.8) / seg
    body = pts[:-1] + [(bx, by)]
    if r and len(body) > 2:
        path(rounded(body, r), color, sw, dash=dash)
    else:
        line(body, color, sw, dash)
    head(tip, prev, color, hs)


def rounded(pts, r):
    d = f"M{pts[0][0]:.2f},{pts[0][1]:.2f}"
    for i in range(1, len(pts) - 1):
        (x0, y0), (x1, y1), (x2, y2) = pts[i - 1], pts[i], pts[i + 1]
        l1, l2 = math.dist((x0, y0), (x1, y1)), math.dist((x1, y1), (x2, y2))
        rr = min(r, l1 / 2, l2 / 2)
        ax, ay = x1 + (x0 - x1) * rr / l1, y1 + (y0 - y1) * rr / l1
        bx, by = x1 + (x2 - x1) * rr / l2, y1 + (y2 - y1) * rr / l2
        d += f" L{ax:.2f},{ay:.2f} Q{x1:.2f},{y1:.2f} {bx:.2f},{by:.2f}"
    d += f" L{pts[-1][0]:.2f},{pts[-1][1]:.2f}"
    return d


def cylinder(x, y, w, h, fill=WHITE, stroke=INK, sw=SW):
    ry = min(h * 0.16, w * 0.22)
    path(f"M{x},{y + ry} A{w / 2},{ry} 0 0 1 {x + w},{y + ry} V{y + h - ry} "
         f"A{w / 2},{ry} 0 0 1 {x},{y + h - ry} Z", stroke, sw, fill=fill)
    path(f"M{x},{y + ry} A{w / 2},{ry} 0 0 0 {x + w},{y + ry}", stroke, sw)


def circle(cx, cy, r, fill=WHITE, stroke=INK, sw=SW):
    s = f'stroke="{stroke}" stroke-width="{sw}"' if stroke else 'stroke="none"'
    out.append(f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="{r}" fill="{fill}" {s}/>')


def magnifier(cx, cy, r=2.6, color=BLUE):
    circle(cx, cy, r, fill=WHITE, stroke=color, sw=SW)
    a = math.radians(45)
    line([(cx + r * math.cos(a), cy + r * math.sin(a)),
          (cx + (r + 2.6) * math.cos(a), cy + (r + 2.6) * math.sin(a))], color, 1.1)


def table_icon(x, y, w, h, color=BLUE):
    rect(x, y, w, h, rx=0.8, fill=WHITE, stroke=color)
    rect(x, y, w, h * 0.28, rx=0.8, fill=LBLUE, stroke=color)
    for k in (1, 2):
        line([(x + w * k / 3, y + h * 0.28), (x + w * k / 3, y + h)], color, 0.5)
    line([(x, y + h * 0.64), (x + w, y + h * 0.64)], color, 0.5)


def card_icon(x, y, w=13, h=9.5):
    rect(x, y, w, h, rx=1, fill=WHITE, stroke=INK, sw=0.6)
    rect(x, y, w, 2.6, rx=1, fill=LBLUE, stroke=INK, sw=0.6)
    for k in (0, 1):
        line([(x + 2, y + 4.6 + k * 2.4), (x + w - 2.5 - k * 2, y + 4.6 + k * 2.4)], INK, 0.45)


def trash_icon(cx, cy, color=INK):
    line([(cx - 2.4, cy - 2.2), (cx + 2.4, cy - 2.2)], color, 0.6)
    line([(cx - 0.8, cy - 2.2), (cx - 0.8, cy - 3), (cx + 0.8, cy - 3), (cx + 0.8, cy - 2.2)], color, 0.5)
    path(f"M{cx - 1.8},{cy - 1.6} L{cx - 1.4},{cy + 2.6} L{cx + 1.4},{cy + 2.6} L{cx + 1.8},{cy - 1.6}",
         color, 0.6)
    for dx in (-0.6, 0.6):
        line([(cx + dx, cy - 0.8), (cx + dx, cy + 1.8)], color, 0.4)


def bubble_icon(cx, cy, color=INK):
    rect(cx - 3, cy - 2.3, 6, 3.8, rx=1.2, fill="none", stroke=color, sw=0.6)
    path(f"M{cx - 1.4},{cy + 1.5} L{cx - 2},{cy + 3} L{cx},{cy + 1.5}", color, 0.6, fill=color)


def check_icon(cx, cy, r=3.6):
    circle(cx, cy, r, fill=GREEN, stroke=None)
    line([(cx - 1.6, cy + 0.1), (cx - 0.4, cy + 1.3), (cx + 1.8, cy - 1.2)], WHITE, 0.9)


def panel(x, y, w, h, num, title, subtitle=None):
    rect(x, y, w, h, rx=4, fill=BG, stroke=None)
    cx, cy = x + 9, y + 9
    circle(cx, cy, 5.2, fill=BLUE, stroke=None)
    text(cx, cy + 2.6, str(num), 7.5, "middle", bold=True, color=WHITE)
    text(x + 17, y + 11.6, title, 7.5, bold=True, maxw=w - 20)
    if subtitle:
        text(x + 17, y + 19, subtitle, 5.8, italic=True, maxw=w - 20)


def box(x, y, w, h, rows, size=6, fill=WHITE, stroke=INK, color=INK, bold_first=False, rx=2.2):
    rect(x, y, w, h, rx=rx, fill=fill, stroke=stroke)
    step = size * 1.2
    y0 = y + h / 2 - (len(rows) - 1) * step / 2 + 0.35 * size
    for k, r in enumerate(rows):
        text(x + w / 2, y0 + k * step, r, size, "middle", color=color,
             bold=bold_first and k == 0, maxw=w - 3)


# ================================================================ layout
PT, PB = 18.0, 152.0
PH = PB - PT
P1 = (68.0, 103.0)
P2 = (180.0, 125.0)
P3 = (314.0, 120.0)
P4 = (443.0, 70.0)
SY0, SY1 = 159.0, 195.0  # offline strip

out.append(f'<rect x="0" y="0" width="{W}" height="{H}" fill="{WHITE}"/>')

for (x, w), n, t, s in [
    (P1, 1, "Staged Detection", None),
    (P2, 2, "Type Detectors", "(data observability)"),
    (P3, 3, "Uncertainty Gate", "(model resolvability)"),
    (P4, 4, "Parsing", None),
]:
    panel(x, PT, w, PH, n, t, s)

# ---------------------------------------------------------------- inputs
IX, IW = 3.0, 52.0
text(IX + IW / 2, 29.5, "Input", 6.5, "middle", bold=True)
# Question
rect(IX, 34, IW, 12, rx=2)
circle(IX + 6.5, 40, 3, fill=WHITE, stroke=BLUE)
text(IX + 6.5, 42.1, "?", 5.2, "middle", bold=True, color=BLUE)
text(IX + 12, 42.1, "Question $Q$", 6, maxw=IW - 13)
# Schema
rect(IX, 50, IW, 25, rx=2)
table_icon(IX + 3, 53, 7, 6)
text(IX + 12, 58, "Schema $S$^{+}", 6, maxw=IW - 13)
text(IX + 12, 65.2, "(descriptions,", 5.5, maxw=IW - 13)
text(IX + 12, 71.4, "sample values)", 5.5, maxw=IW - 13)
# Evidence
rect(IX, 79, IW, 12, rx=2)
ex, ey = IX + 4, 81.2
path(f"M{ex},{ey} H{ex + 4} L{ex + 6},{ey + 2} V{ey + 7.6} H{ex} Z", BLUE, 0.6)
for k in range(3):
    line([(ex + 1.2, ey + 3.2 + k * 1.5), (ex + 4.8, ey + 3.2 + k * 1.5)], BLUE, 0.4)
text(IX + 12, 87.1, "Evidence $E$", 6, maxw=IW - 13)
# Database
cylinder(IX + 9, 96, 34, 26)
lines(IX + 26, 111, ["Database", "$D$"], 6)

BRX = 60.0
for yy in (40, 62.5, 85, 109):
    xe = IX + IW if yy != 109 else IX + 43
    line([(xe, yy), (BRX, yy)], INK, SW)
line([(BRX, 40), (BRX, 109)], INK, SW)
arrow([(BRX, 75), (P1[0] + 0.2, 75)], INK, THICK, hs=4.6)

# ---------------------------------------------------------------- panel 1
x0, pw = P1
FBX = x0 + 8.5               # feedback rail
SX, SW_ = x0 + 18, pw - 22   # sub-box x / width
stages = [
    ("S1", ["Scope · Attachment"], 37, 14),
    ("S2", ["Column · Join", "Value · NULL"], 57, 19),
    ("S3", ["Aggregate ·", "Project · Tie"], 82, 19),
]
mids = []
for tag, rows, y, h in stages:
    rect(SX, y, SW_, h, rx=2.2, fill=WHITE, stroke=INK)
    rect(SX, y, 13, h, rx=2.2, fill=BLUE, stroke=BLUE)
    rect(SX + 8, y, 5, h, rx=0, fill=BLUE, stroke=None)
    line([(SX + 13, y), (SX + 13, y + h)], INK, SW)
    rect(SX, y, SW_, h, rx=2.2, fill="none", stroke=INK)
    text(SX + 6.5, y + h / 2 + 2.2, tag, 6.2, "middle", bold=True, color=WHITE)
    step = 7.2
    y0 = y + h / 2 - (len(rows) - 1) * step / 2 + 2.1
    for k, r in enumerate(rows):
        text(SX + 16, y0 + k * step, r, 6, maxw=SW_ - 18)
    mids.append(y + h / 2)
cxs = SX + SW_ / 2 + 6
for (_, _, y, h), (_, _, yn, _) in zip(stages, stages[1:]):
    arrow([(cxs, y + h), (cxs, yn)], INK, SW, hs=3)
# feedback of earlier-stage cards
line([(SX, mids[0]), (FBX, mids[0]), (FBX, mids[2])], INK, SW)
arrow([(FBX, mids[1]), (SX, mids[1])], INK, SW, hs=3)
arrow([(FBX, mids[2]), (SX, mids[2])], INK, SW, hs=3)
lw = tw("Φ^{(<s)}", 6)
rect(FBX - lw / 2 - 1, 49.6, lw + 2, 7.4, rx=0, fill=BG, stroke=None)
text(FBX, 55.2, "Φ^{(<s)}", 6, "middle")

# raw card stack
STX, STY = x0 + 10, 113
arrow([(STX + 7, 101), (STX + 7, STY - 0.5)], INK, SW, hs=3)
for k in (2, 1, 0):
    card_icon(STX + k * 2.2, STY + k * 2.2)
text(STX + 9, 135, "Raw cards", 6, "middle", maxw=34)
text(STX + 9, 142.5, "Φ_{raw}", 6, "middle")

# enlarged example card
CX, CY, CW, CH = x0 + 44, 107, 53, 34
line([(STX + 13, STY), (CX, CY)], GRAY, 0.6, dash="1.6,1.2")
line([(STX + 13 + 4.4, STY + 4.4 + 9.5), (CX, CY + CH)], GRAY, 0.6, dash="1.6,1.2")
rect(CX, CY, CW, CH, rx=2, fill=WHITE, stroke=INK)
path(f"M{CX},{CY + 9.5} V{CY + 2} Q{CX},{CY} {CX + 2},{CY} H{CX + CW - 2} "
     f"Q{CX + CW},{CY} {CX + CW},{CY + 2} V{CY + 9.5} Z", INK, SW, fill=LBLUE)
text(CX + CW / 2, CY + 6.9, "span $h$", 6, "middle", bold=True)
text(CX + 4, CY + 18.4, "$p$_{1} = ⟨$e$_{1}, $d$_{1}⟩", 6, maxw=CW - 6)
line([(CX + 3, CY + 21.6), (CX + CW - 3, CY + 21.6)], GRAY, 0.5)
text(CX + 4, CY + 29.2, "$p$_{2} = ⟨$e$_{2}, $d$_{2}⟩", 6, maxw=CW - 6)

# ---------------------------------------------------------------- panel 2
x0, pw = P2
GX, GY, GW, GH = x0 + 4, 40, pw - 8, 89
rect(GX, GY, GW, GH, rx=3, fill="none", stroke=GRAY, sw=SW)
arrow([(P1[0] + P1[1] - 5, 124), (GX, 124)], INK, THICK, hs=4.6)

cols = [
    (35.0, ["Existence", "check"], ["Column · Join"]),
    (35.0, ["Content", "check"], ["Value · NULL"]),
    (39.0, ["Execution-", "equivalence", "check"], ["Scope ·", "Attachment ·", "NULL"]),
]
cx_ = GX + 2.5
CTOP, CBOT = GY + 2.5, 104
col_x = []
for k, (cw, title, sub) in enumerate(cols):
    rect(cx_, CTOP, cw, CBOT - CTOP, rx=2.2, fill=WHITE, stroke=INK)
    ic = cx_ + cw / 2
    iy = CTOP + 4
    if k == 0:
        table_icon(ic - 7, iy + 1, 12, 10)
        magnifier(ic + 4.5, iy + 10, 2.8)
    elif k == 1:
        cylinder(ic - 6, iy, 11, 13, stroke=BLUE)
        magnifier(ic + 5, iy + 10, 2.8)
    else:
        for dx in (-9.5, 3.5):
            rect(ic + dx, iy, 6, 5, rx=0.6, fill=WHITE, stroke=BLUE, sw=0.6)
            line([(ic + dx + 1.2, iy + 1.8), (ic + dx + 4.8, iy + 1.8)], BLUE, 0.4)
            line([(ic + dx + 1.2, iy + 3.3), (ic + dx + 3.6, iy + 3.3)], BLUE, 0.4)
        line([(ic - 1.7, iy + 1.8), (ic + 1.7, iy + 1.8)], INK, 0.6)
        line([(ic - 1.7, iy + 3.3), (ic + 1.7, iy + 3.3)], INK, 0.6)
        cylinder(ic - 5, iy + 6.6, 10, 7.4, stroke=BLUE)
    ty = CTOP + 23.5
    for j, t in enumerate(title):
        text(ic, ty + j * 6.8, t, 6, "middle", bold=True, maxw=cw - 2)
    sy = ty + len(title) * 6.8 + 1.5
    for j, s in enumerate(sub):
        text(ic, sy + j * 6.2, s, 5.5, "middle", italic=True, color=BLUE, maxw=cw - 1)
    col_x.append((cx_, cw))
    cx_ += cw + 2.5

# principles bar
BX, BY, BW, BH = GX + 2.5, 106.5, GW - 5, 20
rect(BX, BY, BW, BH, rx=1.5, fill=BG, stroke=GRAY, sw=0.6)
for j, (p, t) in enumerate([("P1", "act only on positive evidence"),
                            ("P2", "write a single reading only if informative"),
                            ("P3", "check only where data can decide")]):
    text(BX + 2.5, BY + 5.9 + j * 6.2, f"!{{{p}}} {t}", 5.4, maxw=BW - 4)

# outcome: remove
RPX, RPY = GX + 6, 136.5
arrow([(RPX + 14, GY + GH), (RPX + 14, RPY)], GRAY, 1.0, hs=3.2)
pill(RPX, RPY, 50, 10.5, GRAY)
trash_icon(RPX + 7.2, RPY + 5.4)
text(RPX + 12.5, RPY + 7.4, "Remove card", 6, maxw=36)
text(GX + 61, 140.0, "any failure →", 5.5, italic=True)
text(GX + 61, 146.4, "pass unchanged", 5.5, italic=True)

# outcome: write to E (curved over panel 3 into panel 4)
GAP23 = (P2[0] + P2[1] + P3[0]) / 2
E4X = P4[0] + 54
WY = 9.0
pts = [(GX + GW, 47), (GAP23, 47), (GAP23, WY), (E4X, WY), (E4X, 42)]
arrow(pts, LBLUE, 1.1, hs=3.6, r=7)
wpw = 40
wpx = P3[0] + P3[1] / 2 - wpw / 2
pill(wpx, WY - 5, wpw, 10, LBLUE)
text(wpx + wpw / 2, WY + 2.1, "Write to $E$", 6, "middle", bold=True)

# outcome: remaining cards -> panel 3
JY = 62.0
arrow([(GX + GW, JY), (P3[0] + 6, JY)], INK, THICK, hs=4.6)

# ---------------------------------------------------------------- panel 3
x0, pw = P3
text(x0 + 6, 46.0, "Remaining cards Φ", 5.5, italic=True)
JX, JW, JH = x0 + 6, 26, 20
box(JX, JY - JH / 2, JW, JH, ["JEV", "scorer"], 6, bold_first=True, stroke=BLUE)
# probability chart
CHX, CBASE = x0 + 39, JY + 9
arrow([(JX + JW, JY), (CHX - 1, JY)], INK, SW, hs=3)
for k, (lab, hgt, col) in enumerate([("A", 5, LBLUE), ("B", 17, BLUE), ("C", 3.5, LBLUE)]):
    bx = CHX + 1.5 + k * 7.5
    rect(bx, CBASE - hgt, 5, hgt, rx=0, fill=col, stroke=None)
    text(bx + 2.5, CBASE + 6, lab, 5.5, "middle")
line([(CHX, CBASE), (CHX + 24, CBASE)], INK, SW)
line([(CHX, CBASE), (CHX, CBASE - 18.5)], INK, SW)
# formula
FX = x0 + 69
text(FX, JY - 6.5, "$H$_{norm} =", 6)
num = "−Σ_{$j$} $p$_{$j$} log $p$_{$j$}"
nw = tw(num, 6)
text(FX, JY + 2.2, num, 6, maxw=x0 + pw - FX - 2)
line([(FX, JY + 4.6), (FX + nw, JY + 4.6)], INK, 0.6)
text(FX + nw / 2, JY + 11, "log $m$", 6, "middle")

# diamond
DCX, DCY, DHW, DHH = x0 + 38, 99.0, 29.0, 13.0
path(f"M{DCX},{DCY - DHH} L{DCX + DHW},{DCY} L{DCX},{DCY + DHH} L{DCX - DHW},{DCY} Z",
     INK, SW, fill=WHITE)
text(DCX, DCY + 2.1, "$H$_{norm} ≤ θ ?", 6, "middle", maxw=2 * DHW - 12)
arrow([(FX + nw / 2, JY + 13.5), (FX + nw / 2, 79), (DCX, 79), (DCX, DCY - DHH)], INK, SW, hs=3, r=2)
# yes -> Auto
APX, APW = x0 + 77, 39
arrow([(DCX + DHW, DCY), (APX, DCY)], INK, SW, hs=3)
text((DCX + DHW + APX) / 2, DCY - 2.8, "yes", 5.5, "middle", italic=True)
pill(APX, DCY - 5.5, APW, 11, BLUE)
text(APX + APW / 2, DCY + 2.1, "Auto($p$_{$j$}^{*})", 6, "middle", bold=True, color=WHITE)
# no -> ask / drop
NY1, NY2 = 117.5, 136.0
TRX = DCX
QX, QW = x0 + 48, 61
DPW = 25
line([(TRX, DCY + DHH), (TRX, NY2)], INK, SW)
text(TRX - 1.8, DCY + DHH + 6.0, "no", 5.5, "end", italic=True)
arrow([(TRX, NY1), (QX, NY1)], INK, SW, hs=3)
arrow([(TRX, NY2 - 0.01), (TRX + 0.01, NY2), (QX, NY2)], INK, SW, hs=3)
pill(QX, NY1 - 5.5, QW, 11, ORANGE)
bubble_icon(QX + 6.5, NY1 - 0.2)
text(QX + 11.5, NY1 + 2.1, "Ask user → $r$(φ)", 6, bold=True, maxw=QW - 13)
text(QX + 2, NY1 + 11.2, "interactive", 5.5, italic=True)
pill(QX, NY2 - 5.5, DPW, 11, GRAY)
text(QX + DPW / 2, NY2 + 2.1, "Drop", 6, "middle", bold=True)
text(QX + DPW + 3, NY2 + 2.0, "non-interactive", 5.5, italic=True, maxw=x0 + pw - QX - DPW - 4)

# ---------------------------------------------------------------- panel 4
x0, pw = P4
EX, EY, EW, EH = x0 + 4, 42, pw - 8, 30
GAP34 = (P3[0] + P3[1] + P4[0]) / 2
rect(EX, EY, EW, EH, rx=2.2, fill=WHITE, stroke=INK)
lines(EX + EW / 2, EY + EH / 2, ["!{$E$′ = $E$ ⊕}", "clarification", "sentences"], 6)
# arrows from Auto (blue) and Ask (orange)
arrow([(APX + APW, DCY), (GAP34 - 2, DCY), (GAP34 - 2, EY + 10), (EX, EY + 10)], BLUE, 1.0, hs=3.4, r=3)
arrow([(QX + QW, NY1), (GAP34 + 2, NY1), (GAP34 + 2, EY + 20), (EX, EY + 20)], ORANGE, 1.0, hs=3.4, r=3)
# parser
PX, PY, PWW, PHH = EX, 82, EW, 20
arrow([(EX + EW / 2, EY + EH), (EX + EW / 2, PY)], INK, SW, hs=3)
rect(PX, PY, PWW, PHH, rx=2.2, fill=INK, stroke=INK)
lines(PX + PWW / 2, PY + PHH / 2, ["!{Parser}", "(black box)"], 6, color=WHITE)
text(EX, 110.5, "sees table and", 5.5, italic=True)
text(EX, 116.6, "column names only", 5.5, italic=True, maxw=EW)
# SQL output
QBX, QBY, QBW, QBH = EX + 8, 124, EW - 16, 22
arrow([(PX + PWW / 2 + 22, PY + PHH), (PX + PWW / 2 + 22, QBY)], INK, SW, hs=3)
rect(QBX, QBY, QBW, QBH, rx=2, fill=WHITE, stroke=INK)
text(QBX + 3.5, QBY + 7.4, "SQL", 6.2, bold=True)
for k, ln in enumerate((0.78, 0.55, 0.66)):
    line([(QBX + 3.5, QBY + 11.5 + k * 3.4), (QBX + 3.5 + (QBW - 7) * ln, QBY + 11.5 + k * 3.4)], GRAY, 1.0)
check_icon(QBX + QBW - 5, QBY + 5.2)

# ---------------------------------------------------------------- offline strip
SX0, SX1 = P1[0], P3[0] + P3[1]
rect(SX0, SY0, SX1 - SX0, SY1 - SY0, rx=3, fill=WHITE, stroke=INK, dash="3,2")
SCY = (SY0 + SY1) / 2
text(SX0 + 5, SCY - 3.5, "Offline", 7, bold=True)
text(SX0 + 5, SCY + 3.5, "training &", 5.5, italic=True)
text(SX0 + 5, SCY + 9.5, "θ selection", 5.5, italic=True)

BH_ = 24
left = [
    ["Cards from 60", "BIRD-train databases"],
    ["Simulated-user", "labels"],
    ["!{Train JEV} (LoRA,", "soft-label cross-entropy,", "option shuffling)"],
]
right = [
    ["9 held-out", "databases"],
    ["!{Select θ}: largest θ", "with agreement ≥ α"],
]


def bw(rows, s=5.8):
    return max(tw(r, s) for r in rows) + 6


widths = [bw(r) for r in left + right]
start, end = SX0 + 40, SX1 - 6
gap = (end - start - sum(widths)) / 5
pos = []
xx = start
for k, wdt in enumerate(widths):
    pos.append((xx, wdt))
    xx += wdt + (gap if k != 2 else gap)
for k, ((bx, wdt), rows) in enumerate(zip(pos, left + right)):
    stroke = BLUE if k in (2, 4) else INK
    box(bx, SCY - BH_ / 2, wdt, BH_, rows, 5.8, stroke=stroke)
for k in (0, 1, 3):
    (ax, aw), (bx, _) = pos[k], pos[k + 1]
    arrow([(ax + aw, SCY), (bx, SCY)], INK, SW, hs=3)
# divider between training and threshold selection
dvx = (pos[2][0] + pos[2][1] + pos[3][0]) / 2
line([(dvx, SY0 + 4), (dvx, SY1 - 4)], GRAY, 0.75, dash="2,1.5")

# theta: from "Select theta" up into the diamond
s5x, s5w = pos[4]
TX = P3[0] + 21.0
ty_edge = DCY + DHH * (1 - (DCX - TX) / DHW)
arrow([(s5x + s5w / 2, SCY - BH_ / 2), (s5x + s5w / 2, 155.5), (TX, 155.5), (TX, ty_edge)],
      BLUE, 0.9, dash="2.2,1.4", hs=3.2, r=2)
text(TX - 2, 146, "θ", 7, "end", bold=True, color=BLUE)

# ---------------------------------------------------------------- legend
LX, LY = P4[0] + 2, 163.5
items = [
    ("card flow", dict(color=INK, sw=1.0)),
    ("write to evidence", dict(color=LBLUE, sw=1.1)),
    ("removed / dropped", dict(color=GRAY, sw=1.0)),
    ("offline parameter", dict(color=BLUE, sw=0.9, dash="2.2,1.4")),
]
for k, (lab, st) in enumerate(items):
    yy = LY + k * 8.4
    arrow([(LX, yy), (LX + 13, yy)], hs=3, **st)
    text(LX + 16, yy + 2, lab, 5.5, maxw=P4[0] + P4[1] - LX - 16)

# ================================================================ write
svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="7.16in" height="{H / 72:.4f}in" '
       f'viewBox="0 0 {W} {H}">\n' + "\n".join(out) + "\n</svg>\n")
dst = Path(__file__).parent / "figure"
dst.mkdir(exist_ok=True)
(dst / "architecture.svg").write_text(svg, encoding="utf-8")

import cairosvg  # noqa: E402

cairosvg.svg2pdf(bytestring=svg.encode(), write_to=str(dst / "architecture.pdf"))
cairosvg.svg2png(bytestring=svg.encode(), write_to=str(dst / "architecture.png"),
                 output_width=int(7.16 * 600))
for w_ in WARN:
    print("WARN", w_)
print("wrote", *sorted(p.name for p in dst.iterdir()))
