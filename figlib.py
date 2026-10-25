"""Small SVG drawing kit for print figures.

Units are PostScript points.  Text is laid out with explicit per-run x/y
positions measured from the Liberation fonts (metric-compatible with
Helvetica / Times / Courier), so every renderer produces the same layout.

Inline markup accepted by `text()`:
    $..$   math: italic serif letters, upright serif digits/operators
    `..`   monospace
    !{..}  bold          /{..}  italic (sans)
    _{..}  subscript     ^{..}  superscript
"""

import math
from pathlib import Path

from fontTools.ttLib import TTFont
from PIL import ImageFont

_FD = Path("/usr/share/fonts/truetype")
_FILES = {
    ("sans", False, False): "liberation/LiberationSans-Regular.ttf",
    ("sans", True, False): "liberation/LiberationSans-Bold.ttf",
    ("sans", False, True): "liberation/LiberationSans-Italic.ttf",
    ("sans", True, True): "liberation/LiberationSans-BoldItalic.ttf",
    ("serif", False, False): "liberation/LiberationSerif-Regular.ttf",
    ("serif", True, False): "liberation/LiberationSerif-Bold.ttf",
    ("serif", False, True): "liberation/LiberationSerif-Italic.ttf",
    ("serif", True, True): "liberation/LiberationSerif-BoldItalic.ttf",
    ("mono", False, False): "liberation/LiberationMono-Regular.ttf",
    ("mono", True, False): "liberation/LiberationMono-Bold.ttf",
    ("mono", False, True): "liberation/LiberationMono-Italic.ttf",
    ("mono", True, True): "liberation/LiberationMono-BoldItalic.ttf",
}
_FALLBACK = {
    "sans": ("dejavu/DejaVuSans.ttf", "dejavu/DejaVuSans-Bold.ttf"),
    "serif": ("dejavu/DejaVuSerif.ttf", "dejavu/DejaVuSerif-Bold.ttf"),
    "mono": ("dejavu/DejaVuSansMono.ttf", "dejavu/DejaVuSansMono-Bold.ttf"),
}
FAMILY = {
    "sans": "'Liberation Sans', Helvetica, Arial, sans-serif",
    "serif": "'Liberation Serif', 'Times New Roman', Times, serif",
    "mono": "'Liberation Mono', 'Courier New', Courier, monospace",
    "fb-sans": "'DejaVu Sans', 'Segoe UI Symbol', sans-serif",
    "fb-serif": "'DejaVu Serif', 'Cambria Math', 'STIX Two Math', serif",
    "fb-mono": "'DejaVu Sans Mono', 'Segoe UI Symbol', monospace",
}

_pil, _cmap = {}, {}


def _font(rel):
    if rel not in _pil:
        _pil[rel] = ImageFont.truetype(str(_FD / rel), 100)
        _cmap[rel] = set(TTFont(str(_FD / rel)).getBestCmap())
    return _pil[rel]


UPRIGHT_WORDS = {"log", "Detect", "norm", "res", "raw", "Auto", "Ask", "Fig"}
MIN_PT = 6.0


class Canvas:
    def __init__(self, w, h, stroke=0.7, ink="#333333"):
        self.w, self.h, self.sw, self.ink = w, h, stroke, ink
        self.items: list[str] = []
        self.warn: list[str] = []

    # ------------------------------------------------------------ markup
    def _parse(self, s, mode="sans", bold=False, italic=False, shift=0):
        runs, buf, i = [], "", 0

        def flush():
            nonlocal buf
            if buf:
                runs.append((buf, mode, bold, italic, shift))
                buf = ""

        while i < len(s):
            c = s[i]
            if c in "$`":
                flush()
                j = s.index(c, i + 1)
                inner = s[i + 1 : j]
                if c == "$":
                    runs += self._parse(inner, "math", bold, italic, shift)
                else:
                    runs.append((inner, "mono", bold, False, shift))
                i = j + 1
            elif c in "!/_^" and i + 1 < len(s) and s[i + 1] == "{":
                flush()
                depth, j = 0, i + 1
                while True:
                    depth += {"{": 1, "}": -1}.get(s[j], 0)
                    if depth == 0:
                        break
                    j += 1
                inner = s[i + 2 : j]
                if c == "!":
                    runs += self._parse(inner, mode, True, italic, shift)
                elif c == "/":
                    runs += self._parse(inner, mode, bold, True, shift)
                else:
                    runs += self._parse(inner, mode, bold, italic, -1 if c == "_" else 1)
                i = j + 1
            else:
                buf += c
                i += 1
        flush()
        return runs

    def _glyph_runs(self, markup, bold=False, italic=False, mode="sans"):
        """Resolve markup into (text, font_rel, family_key, bold, italic, shift)."""
        out = []
        for txt, md, b, it, sh in self._parse(markup, mode, bold, italic):
            pieces = []
            if md == "math":
                tok, kind = "", None
                k = 0
                while k < len(txt):
                    word = next((w for w in UPRIGHT_WORDS if txt.startswith(w, k)
                                 and not (k + len(w) < len(txt) and txt[k + len(w)].isalpha())
                                 and not (k > 0 and txt[k - 1].isalpha())), None)
                    if word:
                        pieces.append((word, "serif", b, False))
                        k += len(word)
                        continue
                    ch = txt[k]
                    pieces.append((ch, "serif", b, ch.isalpha()))
                    k += 1
            else:
                pieces = [(ch, md, b, it) for ch in txt]
            for ch, fam, bb, ii in pieces:
                rel = _FILES[(fam, bb, ii)]
                _font(rel)
                fkey = fam
                if any(ord(c) not in _cmap[rel] for c in ch):
                    rel = _FALLBACK[fam][1 if bb else 0]
                    _font(rel)
                    fkey = "fb-" + fam
                    ii = False
                if out and out[-1][1:] == (rel, fkey, bb, ii, sh):
                    out[-1] = (out[-1][0] + ch,) + out[-1][1:]
                else:
                    out.append((ch, rel, fkey, bb, ii, sh))
        return out

    @staticmethod
    def _size(size, sh):
        return max(MIN_PT, 0.74 * size) if sh else size

    def tw(self, markup, size=6, bold=False, italic=False, mode="sans"):
        return sum(_font(rel).getlength(t) / 100 * self._size(size, sh)
                   for t, rel, _, _, _, sh in self._glyph_runs(markup, bold, italic, mode))

    def text(self, x, y, markup, size=6, anchor="start", bold=False, italic=False,
             color=None, maxw=None, mode="sans"):
        color = color or self.ink
        if size < MIN_PT - 1e-6:
            self.warn.append(f"font {size}pt < {MIN_PT}: {markup!r}")
        w = self.tw(markup, size, bold, italic, mode)
        if maxw is not None and w > maxw + 0.05:
            self.warn.append(f"overflow {w:.1f}>{maxw:.1f}: {markup!r}")
        x -= {"start": 0, "middle": w / 2, "end": w}[anchor]
        parts = [f'<text fill="{color}" xml:space="preserve">']
        cx = x
        for t, rel, fkey, b, it, sh in self._glyph_runs(markup, bold, italic, mode):
            s = self._size(size, sh)
            dy = {0: 0, -1: 0.24 * size, 1: -0.4 * size}[sh]
            a = (f'x="{cx:.2f}" y="{y + dy:.2f}" font-family="{FAMILY[fkey]}" '
                 f'font-size="{s:.2f}"')
            if b:
                a += ' font-weight="bold"'
            if it:
                a += ' font-style="italic"'
            parts.append(f"<tspan {a}>{_esc(t)}</tspan>")
            cx += _font(rel).getlength(t) / 100 * s
        parts.append("</text>")
        self.items.append("".join(parts))
        return w

    # ------------------------------------------------------------ shapes
    def rect(self, x, y, w, h, rx=3, fill="#FFFFFF", stroke=None, sw=None, dash=None):
        sw = sw or self.sw
        s = f'stroke="{stroke}" stroke-width="{sw}"' if stroke else 'stroke="none"'
        d = f' stroke-dasharray="{dash}"' if dash else ""
        self.items.append(f'<rect x="{x:.2f}" y="{y:.2f}" width="{w:.2f}" height="{h:.2f}" '
                          f'rx="{rx}" fill="{fill}" {s}{d}/>')

    def circle(self, cx, cy, r, fill="#FFFFFF", stroke=None, sw=None):
        sw = sw or self.sw
        s = f'stroke="{stroke}" stroke-width="{sw}"' if stroke else 'stroke="none"'
        self.items.append(f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="{r}" fill="{fill}" {s}/>')

    def path(self, d, color=None, sw=None, fill="none", dash=None, cap="round"):
        color = color or self.ink
        sw = sw or self.sw
        da = f' stroke-dasharray="{dash}"' if dash else ""
        self.items.append(f'<path d="{d}" fill="{fill}" stroke="{color}" stroke-width="{sw}" '
                          f'stroke-linejoin="round" stroke-linecap="{cap}"{da}/>')

    def line(self, pts, color=None, sw=None, dash=None, r=0, cap="round"):
        self.path(_rounded(pts, r), color, sw, dash=dash, cap=cap)

    def polygon(self, pts, fill):
        p = " ".join(f"{a:.2f},{b:.2f}" for a, b in pts)
        self.items.append(f'<polygon points="{p}" fill="{fill}"/>')

    def arrow(self, pts, color=None, sw=None, dash=None, hs=None, r=0, halo=None, cap="round"):
        """Polyline ending in a filled arrowhead.  `halo` draws a white underlay."""
        color = color or self.ink
        sw = sw or self.sw
        hs = hs or (4.8 if sw >= 1.3 else 3.2)
        tip, prev = pts[-1], pts[-2]
        seg = math.dist(tip, prev)
        back = hs * 0.8
        body = pts[:-1] + [(tip[0] - (tip[0] - prev[0]) * back / seg,
                            tip[1] - (tip[1] - prev[1]) * back / seg)]
        if halo:
            self.line(body, "#FFFFFF", sw + halo, r=r)
        self.line(body, color, sw, dash, r=r, cap=cap)
        a = math.atan2(tip[1] - prev[1], tip[0] - prev[0])
        bx, by = tip[0] - hs * math.cos(a), tip[1] - hs * math.sin(a)
        px, py = -math.sin(a) * hs * 0.42, math.cos(a) * hs * 0.42
        self.polygon([tip, (bx + px, by + py), (bx - px, by - py)], color)

    def cylinder(self, x, y, w, h, fill="#FFFFFF", stroke=None, sw=None):
        stroke = stroke or self.ink
        ry = min(h * 0.17, w * 0.22)
        self.path(f"M{x},{y + ry} A{w / 2},{ry} 0 0 1 {x + w},{y + ry} V{y + h - ry} "
                  f"A{w / 2},{ry} 0 0 1 {x},{y + h - ry} Z", stroke, sw, fill=fill)
        self.path(f"M{x},{y + ry} A{w / 2},{ry} 0 0 0 {x + w},{y + ry}", stroke, sw)

    # ------------------------------------------------------------ output
    def svg(self, w_in, h_in):
        return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w_in}in" height="{h_in}in" '
                f'viewBox="0 0 {self.w} {self.h}">\n'
                f'<rect width="{self.w}" height="{self.h}" fill="#FFFFFF"/>\n'
                + "\n".join(self.items) + "\n</svg>\n")

    def save(self, stem, w_in, h_in, dpi=600):
        import cairosvg

        svg = self.svg(w_in, h_in)
        stem = Path(stem)
        stem.parent.mkdir(parents=True, exist_ok=True)
        stem.with_suffix(".svg").write_text(svg, encoding="utf-8")
        cairosvg.svg2pdf(bytestring=svg.encode(), write_to=str(stem.with_suffix(".pdf")))
        cairosvg.svg2png(bytestring=svg.encode(), write_to=str(stem.with_suffix(".png")),
                         output_width=int(w_in * dpi))
        for m in self.warn:
            print("WARN", m)


def _esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _rounded(pts, r):
    d = f"M{pts[0][0]:.2f},{pts[0][1]:.2f}"
    for i in range(1, len(pts) - 1):
        (x0, y0), (x1, y1), (x2, y2) = pts[i - 1], pts[i], pts[i + 1]
        l1, l2 = math.dist((x0, y0), (x1, y1)), math.dist((x1, y1), (x2, y2))
        if not r or l1 == 0 or l2 == 0:
            d += f" L{x1:.2f},{y1:.2f}"
            continue
        rr = min(r, l1 / 2, l2 / 2)
        ax, ay = x1 + (x0 - x1) * rr / l1, y1 + (y0 - y1) * rr / l1
        bx, by = x1 + (x2 - x1) * rr / l2, y1 + (y2 - y1) * rr / l2
        d += f" L{ax:.2f},{ay:.2f} Q{x1:.2f},{y1:.2f} {bx:.2f},{by:.2f}"
    d += f" L{pts[-1][0]:.2f},{pts[-1][1]:.2f}"
    return d
