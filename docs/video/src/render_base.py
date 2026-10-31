import skia, math, json, random, subprocess, sys, os
import numpy as np

W, H, FPS = 1920, 1080, 30
LEAD, PAD = 0.25, 0.45

def hx(h, a=1.0):
    h = h.lstrip('#'); r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return skia.ColorSetARGB(int(max(0, min(1, a)) * 255), r, g, b)

BG = '#0A1628'; PANEL = '#10223F'; PANEL2 = '#152B4E'; LINE = '#2A4470'
WHITE = '#F4F7FB'; MUTED = '#8FA3C0'; DIM = '#56708F'; TEAL = '#2EC4B6'; TEALD = '#17807A'

FD = os.environ.get('INTER_DIR', '/usr/share/fonts/opentype/inter').rstrip('/') + '/'
TF = {k: skia.Typeface.MakeFromFile(FD + f) for k, f in
      dict(r='Inter-Regular.otf', m='Inter-Medium.otf', s='Inter-SemiBold.otf', b='Inter-Bold.otf',
           d='InterDisplay-SemiBold.otf', l='InterDisplay-Light.otf').items()}
TF['mono'] = skia.Typeface.MakeFromFile(os.environ.get('MONO_FONT', '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf'))

def cl(x, a=0., b=1.): return max(a, min(b, x))
def p(t, a, b): return cl((t - a) / (b - a)) if b > a else float(t >= a)
def eo(x): x = cl(x); return 1 - (1 - x) ** 3
def eio(x): x = cl(x); return 4 * x ** 3 if x < .5 else 1 - (-2 * x + 2) ** 3 / 2
def lerp(a, b, k): return a + (b - a) * k

def paint(c, a=1, stroke=0, dash=None, cap=True):
    pt = skia.Paint(AntiAlias=True, Color=hx(c, a))
    if stroke:
        pt.setStyle(skia.Paint.kStroke_Style); pt.setStrokeWidth(stroke)
        if cap: pt.setStrokeCap(skia.Paint.kRound_Cap); pt.setStrokeJoin(skia.Paint.kRound_Join)
        if dash: pt.setPathEffect(skia.DashPathEffect.Make(dash[0], dash[1] if len(dash) > 1 else 0))
    return pt

def text(cv, s, x, y, size, c=WHITE, a=1, w='r', align='l', track=0):
    if a <= 0.001: return 0
    f = skia.Font(TF[w], size); f.setSubpixel(True)
    if track:
        tw = sum(f.measureText(ch) for ch in s) + track * (len(s) - 1)
    else:
        tw = f.measureText(s)
    if align == 'c': x -= tw / 2
    elif align == 'r': x -= tw
    pt = paint(c, a)
    if track:
        for ch in s:
            cv.drawString(ch, x, y, f, pt); x += f.measureText(ch) + track
    else:
        cv.drawString(s, x, y, f, pt)
    return tw

def tw(s, size, w='r'): return skia.Font(TF[w], size).measureText(s)

def rr(cv, x, y, w, h, r, c, a=1, stroke=0, dash=None):
    cv.drawRoundRect(skia.Rect.MakeXYWH(x, y, w, h), r, r, paint(c, a, stroke, dash))

def line(cv, x1, y1, x2, y2, c, a=1, w=2, k=1.0, dash=None):
    if k <= 0: return
    cv.drawLine(x1, y1, lerp(x1, x2, k), lerp(y1, y2, k), paint(c, a, w, dash))

def arrow(cv, x1, y1, x2, y2, c=TEAL, a=1, w=3, k=1.0, head=14, dash=None):
    if k <= 0.001: return
    ex, ey = lerp(x1, x2, k), lerp(y1, y2, k)
    cv.drawLine(x1, y1, ex, ey, paint(c, a, w, dash))
    ang = math.atan2(y2 - y1, x2 - x1)
    pa = skia.Path(); pa.moveTo(ex, ey)
    pa.lineTo(ex - head * math.cos(ang - .45), ey - head * math.sin(ang - .45))
    pa.lineTo(ex - head * math.cos(ang + .45), ey - head * math.sin(ang + .45)); pa.close()
    cv.drawPath(pa, paint(c, a))

# ---------- icons ----------
def doc(cv, cx, cy, s=1, a=1, c=WHITE, label=None):
    w, h, f = 96 * s, 124 * s, 26 * s
    x, y = cx - w / 2, cy - h / 2
    pa = skia.Path(); pa.moveTo(x, y); pa.lineTo(x + w - f, y); pa.lineTo(x + w, y + f)
    pa.lineTo(x + w, y + h); pa.lineTo(x, y + h); pa.close()
    cv.drawPath(pa, paint(PANEL2, a)); cv.drawPath(pa, paint(c, a, 2.5 * max(s, .6)))
    fo = skia.Path(); fo.moveTo(x + w - f, y); fo.lineTo(x + w - f, y + f); fo.lineTo(x + w, y + f)
    cv.drawPath(fo, paint(c, a, 2.5 * max(s, .6)))
    for i in range(5):
        ll = (0.72 if i % 3 == 2 else 0.86) * (w - 28 * s)
        line(cv, x + 14 * s, y + (40 + i * 16) * s, x + 14 * s + ll, y + (40 + i * 16) * s, MUTED, a * .8, 3 * s)
    if label: text(cv, label, cx, y + h + 34 * s, 22 * max(s, .8), MUTED, a, 'm', 'c')

def laptop(cv, cx, cy, s=1, a=1):
    w, h = 250 * s, 160 * s
    rr(cv, cx - w / 2, cy - h, w, h, 12 * s, PANEL2, a)
    rr(cv, cx - w / 2, cy - h, w, h, 12 * s, WHITE, a, 3)
    rr(cv, cx - w / 2 + 14 * s, cy - h + 14 * s, w - 28 * s, h - 28 * s, 5 * s, BG, a)
    pa = skia.Path(); pa.moveTo(cx - w / 2 - 30 * s, cy + 18 * s); pa.lineTo(cx + w / 2 + 30 * s, cy + 18 * s)
    pa.lineTo(cx + w / 2 + 6 * s, cy); pa.lineTo(cx - w / 2 - 6 * s, cy); pa.close()
    cv.drawPath(pa, paint(PANEL2, a)); cv.drawPath(pa, paint(WHITE, a, 3))

def server(cv, cx, cy, s=1, a=1, c=WHITE, units=4, leds=TEAL):
    w, uh = 230 * s, 56 * s
    h = units * uh + 20 * s
    x, y = cx - w / 2, cy - h / 2
    rr(cv, x, y, w, h, 10 * s, PANEL2, a); rr(cv, x, y, w, h, 10 * s, c, a, 3)
    for i in range(units):
        yy = y + 10 * s + i * uh
        rr(cv, x + 14 * s, yy + 8 * s, w - 28 * s, uh - 16 * s, 5 * s, BG, a)
        for j in range(3):
            cv.drawCircle(x + 34 * s + j * 18 * s, yy + uh / 2, 4.5 * s, paint(leds if j == 0 else DIM, a))
        for j in range(5):
            line(cv, x + 120 * s + j * 16 * s, yy + 18 * s, x + 120 * s + j * 16 * s, yy + uh - 18 * s, DIM, a, 3 * s)

def cylinder(cv, cx, cy, s=1, a=1, c=TEAL, fill=0.0):
    w, h, e = 190 * s, 210 * s, 46 * s
    x, top = cx - w / 2, cy - h / 2
    body = skia.Path(); body.moveTo(x, top + e / 2); body.lineTo(x, top + h - e / 2)
    body.arcTo(skia.Rect.MakeXYWH(x, top + h - e, w, e), 180, -180, False)
    body.lineTo(x + w, top + e / 2); body.close()
    cv.drawPath(body, paint(PANEL2, a))
    if fill > 0:  # stored level
        lvl = top + h - e / 2 - (h - e) * fill
        fp = skia.Path(); fp.moveTo(x, lvl); fp.lineTo(x, top + h - e / 2)
        fp.arcTo(skia.Rect.MakeXYWH(x, top + h - e, w, e), 180, -180, False)
        fp.lineTo(x + w, lvl); fp.arcTo(skia.Rect.MakeXYWH(x, lvl - e / 2, w, e), 0, 180, False); fp.close()
        cv.drawPath(fp, paint(TEALD, a * .55))
    for k in (0.33, 0.66):
        yy = top + e / 2 + (h - e) * k
        cv.drawArc(skia.Rect.MakeXYWH(x, yy - e / 2, w, e), 0, 180, False, paint(c, a * .5, 2))
    cv.drawPath(body, paint(c, a, 3))
    cv.drawOval(skia.Rect.MakeXYWH(x, top, w, e), paint(PANEL, a))
    cv.drawOval(skia.Rect.MakeXYWH(x, top, w, e), paint(c, a, 3))

def chip(cv, cx, cy, s=1, a=1, c=TEAL):
    w = 120 * s
    for i in range(4):
        o = -w / 2 + w * (i + .5) / 4
        for (x1, y1, x2, y2) in [(cx + o, cy - w / 2, cx + o, cy - w / 2 - 18 * s), (cx + o, cy + w / 2, cx + o, cy + w / 2 + 18 * s),
                                 (cx - w / 2, cy + o, cx - w / 2 - 18 * s, cy + o), (cx + w / 2, cy + o, cx + w / 2 + 18 * s, cy + o)]:
            line(cv, x1, y1, x2, y2, c, a, 4 * s)
    rr(cv, cx - w / 2, cy - w / 2, w, w, 12 * s, PANEL2, a); rr(cv, cx - w / 2, cy - w / 2, w, w, 12 * s, c, a, 3)
    rr(cv, cx - w / 4, cy - w / 4, w / 2, w / 2, 6 * s, c, a * .25); rr(cv, cx - w / 4, cy - w / 4, w / 2, w / 2, 6 * s, c, a, 2)

def wifi_off(cv, cx, cy, s=1, a=1, c=WHITE):
    for i, r in enumerate((22, 44, 66)):
        cv.drawArc(skia.Rect.MakeXYWH(cx - r * s, cy - r * s, 2 * r * s, 2 * r * s), 225, 90, False, paint(c, a * .9, 6 * s))
    cv.drawCircle(cx, cy, 6 * s, paint(c, a))
    line(cv, cx - 58 * s, cy - 70 * s, cx + 58 * s, cy + 18 * s, TEAL, a, 7 * s)

def check(cv, cx, cy, s=1, a=1, k=1.0):
    cv.drawCircle(cx, cy, 22 * s, paint(TEAL, a * .18)); cv.drawCircle(cx, cy, 22 * s, paint(TEAL, a, 2.5))
    pa = skia.Path(); pts = [(cx - 10 * s, cy + 1 * s), (cx - 3 * s, cy + 8 * s), (cx + 11 * s, cy - 8 * s)]
    pa.moveTo(*pts[0])
    if k < .4:
        kk = k / .4; pa.lineTo(lerp(pts[0][0], pts[1][0], kk), lerp(pts[0][1], pts[1][1], kk))
    else:
        pa.lineTo(*pts[1]); kk = (k - .4) / .6; pa.lineTo(lerp(pts[1][0], pts[2][0], kk), lerp(pts[1][1], pts[2][1], kk))
    if k > 0: cv.drawPath(pa, paint(TEAL, a, 4))

def bg(cv):
    cv.clear(hx(BG))
    pt = paint(LINE, .35)
    for x in range(48, W, 48):
        for y in range(48, H, 48):
            cv.drawCircle(x, y, 1.3, pt)

def header(cv, t, tag, title):
    a = eo(p(t, 0, .5)); dy = (1 - a) * 14
    text(cv, tag, 120, 112 + dy, 22, TEAL, a, 's', track=4)
    text(cv, title, 120, 172 + dy, 50, WHITE, a, 'd')
    line(cv, 120, 200, 120 + 120 * eo(p(t, .2, .9)), 200, TEAL, a, 3)

def pipeline(cv, t, active):
    names = ['Parse & index', 'Retrieve', 'Generate']
    a = eo(p(t, 0, .5)); y = 1000; xs = [W / 2 - 360, W / 2, W / 2 + 360]
    line(cv, xs[0], y, xs[2], y, LINE, a, 3)
    line(cv, xs[0], y, xs[active], y, TEAL, a, 3)
    for i, x in enumerate(xs):
        on = i <= active
        cv.drawCircle(x, y, 15, paint(TEAL if i == active else (TEALD if on else PANEL2), a))
        cv.drawCircle(x, y, 15, paint(TEAL if on else LINE, a, 2.5))
        text(cv, str(i + 1), x, y + 6, 16, BG if i == active else WHITE, a, 'b', 'c')
        text(cv, names[i], x, y + 46, 20, WHITE if i == active else DIM, a, 's' if i == active else 'm', 'c')

def tag(cv, x, y, s, a=1, c=TEAL, size=22, fill=None, w='s', mono=False):
    f = 'mono' if mono else w
    ww = tw(s, size, f) + 36
    rr(cv, x, y, ww, size + 22, (size + 22) / 2, fill or PANEL2, a)
    rr(cv, x, y, ww, size + 22, (size + 22) / 2, c, a, 2)
    text(cv, s, x + 18, y + size + 5, size, c, a, f)
    return ww

# ---------- scenes ----------
def s0(cv, t, T):
    a = eo(p(t, .1, .8))
    text(cv, 'NOTE ATLAS  ·  RESEARCH EXPLAINER', W / 2, 330, 24, TEAL, a, 's', 'c', track=5)
    a2 = eo(p(t, .4, 1.2))
    text(cv, 'Local Retrieval-Augmented Generation', W / 2, 440 + (1 - a2) * 20, 80, WHITE, a2, 'd', 'c')
    a3 = eo(p(t, 1.0, 1.8))
    text(cv, 'Private, high-accuracy AI on local hardware', W / 2, 510, 34, MUTED, a3, 'l', 'c')
    # mini pipeline preview inside localhost box
    a4 = eo(p(t, 1.6, 2.4)); bx, by, bw, bh = W / 2 - 430, 600, 860, 270
    rr(cv, bx, by, bw, bh, 22, TEAL, a4 * .9, 2.5, dash=([14, 10],))
    text(cv, 'localhost · 127.0.0.1', bx + 26, by + 40, 20, TEAL, a4, 'mono')
    cx = [W / 2 - 280, W / 2, W / 2 + 280]; cy = by + 155
    ap = [eo(p(t, 2.0 + i * .5, 2.6 + i * .5)) for i in range(3)]
    doc(cv, cx[0], cy, .72, ap[0]); cylinder(cv, cx[1], cy, .55, ap[1]); chip(cv, cx[2], cy, .62, ap[2])
    arrow(cv, cx[0] + 60, cy, cx[1] - 75, cy, TEAL, 1, 3, eo(p(t, 2.4, 3.0)))
    arrow(cv, cx[1] + 70, cy, cx[2] - 70, cy, TEAL, 1, 3, eo(p(t, 2.9, 3.5)))

def s1(cv, t, T):
    header(cv, t, 'THE PROBLEM', 'Commercial LLMs process prompts off-device')
    a = eo(p(t, .3, 1.0))
    lx, ly, rx, ry = 430, 600, 1490, 560
    laptop(cv, lx, ly, 1, a)
    text(cv, 'Your device', lx, ly + 75, 26, WHITE, a, 's', 'c')
    a2 = eo(p(t, .8, 1.5))
    server(cv, rx, ry, 1, a2, WHITE, 4, MUTED)
    text(cv, 'Provider data centre', rx, ry + 190, 26, WHITE, a2, 's', 'c')
    text(cv, 'third-party infrastructure', rx, ry + 225, 20, MUTED, a2, 'r', 'c')
    # link
    x1, x2, y = lx + 175, rx - 140, 520
    k = eo(p(t, 1.2, 2.0))
    line(cv, x1, y, x2, y, MUTED, .7, 3, k, dash=([10, 10], -t * 60))
    text(cv, 'public internet', (x1 + x2) / 2, y - 26, 20, MUTED, eo(p(t, 1.6, 2.2)), 'm', 'c')
    # packets
    labels = ['prompt', 'notes.pdf', 'dataset.csv', 'draft.docx']
    for i in range(7):
        st = 2.0 + i * 1.05
        q = p(t, st, st + 1.8)
        if 0 < q < 1:
            xx = lerp(x1 + 40, x2 - 90, eio(q)); fa = min(1, q * 6, (1 - q) * 6)
            doc(cv, xx, y + 70, .42, fa, WHITE)
            text(cv, labels[i % 4], xx, y + 140, 18, MUTED, fa, 'mono', 'c')
    # risks
    risks = [('LOGGED', 6.4), ('RETAINED', 7.3), ('LEAKED', 8.3)]
    for i, (r, st) in enumerate(risks):
        ra = eo(p(t, st, st + .45)); xx = rx + 160 + (1 - ra) * 30; yy = ry - 150 + i * 92
        if ra <= 0: continue
        rr(cv, xx, yy, 200, 62, 10, PANEL, ra); rr(cv, xx, yy, 200, 62, 10, WHITE, ra, 2)
        # warning triangle
        tx, ty = xx + 34, yy + 31
        pa = skia.Path(); pa.moveTo(tx, ty - 15); pa.lineTo(tx + 15, ty + 12); pa.lineTo(tx - 15, ty + 12); pa.close()
        cv.drawPath(pa, paint(WHITE, ra, 2.5)); text(cv, '!', tx, ty + 9, 17, WHITE, ra, 'b', 'c')
        text(cv, r, xx + 62, yy + 40, 22, WHITE, ra, 's', track=2)
    # leaked: copies escaping off the right
    for j in range(3):
        st = 8.8 + j * .45; q = p(t, st, st + 1.2)
        if 0 < q < 1:
            xx = lerp(rx + 260, W + 80, eio(q)); yy = ry + 150 + j * 22
            doc(cv, xx, yy + 60, .3, min(1, (1 - q) * 3), MUTED)

def s2(cv, t, T):
    header(cv, t, 'THE SOLUTION', 'Local RAG: the whole pipeline on one machine')
    lx, ly, rx, ry = 430, 600, 1490, 560
    out = eo(p(t, 1.4, 2.4))
    if out < 1:
        laptop(cv, lx, ly, 1, 1 - out)
        server(cv, rx, ry, 1, (1 - eo(p(t, .7, 1.6))), WHITE, 4, MUTED)
        x1, x2, y = lx + 175, rx - 140, 520
        mid = (x1 + x2) / 2; gap = 60 * eo(p(t, .3, .8))
        la = 1 - out
        line(cv, x1, y, mid - gap, y, MUTED, .7 * la, 3, dash=([10, 10],))
        line(cv, mid + gap, y, x2, y, MUTED, .7 * la * (1 - eo(p(t, .7, 1.4))), 3, dash=([10, 10],))
        xa = eo(p(t, .3, .7)) * la
        line(cv, mid - 22, y - 22, mid + 22, y + 22, TEAL, xa, 6); line(cv, mid - 22, y + 22, mid + 22, y - 22, TEAL, xa, 6)
        text(cv, 'connection removed', mid, y + 62, 20, TEAL, xa, 'm', 'c')
    # localhost box
    g = eo(p(t, 1.9, 2.9))
    bw, bh = lerp(300, 1500, g), lerp(160, 520, g); bx, by = W / 2 - bw / 2, 300 + (520 - bh) / 2
    if g > 0:
        rr(cv, bx, by, bw, bh, 26, PANEL, g * .6)
        rr(cv, bx, by, bw, bh, 26, TEAL, g, 2.5, dash=([14, 10],))
        text(cv, 'localhost · 127.0.0.1', bx + 30, by + 44, 22, TEAL, eo(p(t, 2.6, 3.2)), 'mono')
    cx = [W / 2 - 480, W / 2, W / 2 + 480]; cy = 560
    items = [('Documents', 'PDF · TXT · DOCX'), ('Vector index', 'ChromaDB on disk'), ('Local LLM', 'served by Ollama')]
    for i in range(3):
        ia = eo(p(t, 2.9 + i * .55, 3.5 + i * .55))
        if i == 0: doc(cv, cx[0], cy, 1.0, ia)
        elif i == 1: cylinder(cv, cx[1], cy, .72, ia)
        else: chip(cv, cx[2], cy, .9, ia)
        text(cv, items[i][0], cx[i], cy + 145, 30, WHITE, ia, 's', 'c')
        text(cv, items[i][1], cx[i], cy + 182, 21, MUTED, ia, 'r', 'c')
    arrow(cv, cx[0] + 85, cy, cx[1] - 110, cy, TEAL, 1, 3, eo(p(t, 3.6, 4.2)))
    arrow(cv, cx[1] + 110, cy, cx[2] - 90, cy, TEAL, 1, 3, eo(p(t, 4.2, 4.8)))
    ba = eo(p(t, 5.2, 5.8))
    lbl = 'No data sent off-device'; tag(cv, W / 2 - (tw(lbl, 24, 's') + 36) / 2, 870, lbl, ba, TEAL, 24)

def s3(cv, t, T):
    header(cv, t, 'STEP 01', 'Document parsing into a vector database')
    pipeline(cv, t, 0)
    dx, dy = 250, 560
    da = eo(p(t, .3, .9))
    split = eo(p(t, 1.3, 2.4))
    doc(cv, dx, dy, 1.5, da * (1 - split * .6))
    text(cv, 'PDF / TXT', dx, dy + 140, 24, MUTED, da, 'm', 'c')
    text(cv, 'text extraction', dx, dy + 172, 20, DIM, da, 'r', 'c')
    # chunks
    N = 5; colx = 560; cw, ch = 250, 54; top = dy - (N * ch + (N - 1) * 16) / 2
    enc_x, enc_y = 1010, dy
    ea = eo(p(t, 2.6, 3.2))
    rr(cv, enc_x - 130, enc_y - 95, 260, 190, 18, PANEL2, ea); rr(cv, enc_x - 130, enc_y - 95, 260, 190, 18, TEAL, ea, 2.5)
    text(cv, 'EMBEDDING MODEL', enc_x, enc_y - 40, 17, TEAL, ea, 's', 'c', track=2)
    text(cv, 'nomic-embed-text', enc_x, enc_y + 8, 25, WHITE, ea, 'mono', 'c')
    text(cv, '768-dim vectors', enc_x, enc_y + 50, 20, MUTED, ea, 'r', 'c')
    dbx = 1640; cyl_fill = 0
    for i in range(N):
        tx, ty = colx, top + i * (ch + 16)
        ox, oy = dx - cw / 2 + 40, dy - 60 + i * 22
        x = lerp(ox, tx, eio(p(t, 1.3 + i * .12, 2.3 + i * .12))); y = lerp(oy, ty, eio(p(t, 1.3 + i * .12, 2.3 + i * .12)))
        ca = eo(p(t, 1.3 + i * .12, 1.7 + i * .12))
        st = 3.4 + i * .85  # travel through encoder
        q1 = p(t, st, st + .55)       # chunk -> encoder
        q2 = p(t, st + .55, st + 1.2)  # vector -> db
        if q1 < 1:
            xx = lerp(x, enc_x - 130 - cw, eio(q1)); yy = lerp(y, enc_y - ch / 2, eio(q1))
            fa = ca * (1 - p(q1, .75, 1))
            rr(cv, xx, yy, cw, ch, 8, PANEL2, fa); rr(cv, xx, yy, cw, ch, 8, WHITE, fa, 2)
            text(cv, f'chunk {i + 1}', xx + 18, yy + 34, 20, WHITE, fa, 's')
            text(cv, '500 chars', xx + cw - 18, yy + 34, 18, MUTED, fa, 'mono', 'r')
        if q1 >= 1 and q2 < 1:
            vx = lerp(enc_x + 140, dbx - 120, eio(q2)); vy = enc_y - 16
            va = min(1, q2 * 8) * (1 - p(q2, .8, 1))
            rnd = random.Random(i)
            for j in range(10):
                v = rnd.random()
                rr(cv, vx + j * 17, vy, 14, 32, 3, TEAL, va * (.25 + .75 * v))
        if q2 >= 1: cyl_fill += 1
    if t > 2.0:
        text(cv, 'fixed 500-character chunks', colx + cw / 2, top + N * (ch + 16) + 30, 21, MUTED, eo(p(t, 2.2, 2.8)) * (1 - eo(p(t, 7.0, 7.6))), 'm', 'c')
    da2 = eo(p(t, 2.9, 3.5))
    cylinder(cv, dbx, dy, 1.0, da2, TEAL, .12 + .7 * cyl_fill / N)
    text(cv, 'ChromaDB', dbx, dy + 150, 30, WHITE, da2, 's', 'c')
    text(cv, f'{cyl_fill * 1 if cyl_fill else 0} / {N} vectors stored', dbx, dy + 186, 20, MUTED, da2, 'mono', 'c')
    arrow(cv, enc_x + 140, enc_y + 70, dbx - 115, enc_y + 70, LINE, da2, 2, 1, 10)

PTS = None
def pts():
    global PTS
    if PTS: return PTS
    r = random.Random(7); P = []
    centers = [(.25, .3), (.7, .25), (.55, .72), (.2, .75), (.85, .65)]
    for cx, cy in centers:
        for _ in range(9): P.append((cl(r.gauss(cx, .07), .04, .96), cl(r.gauss(cy, .07), .06, .94)))
    PTS = P; return P

def s4(cv, t, T):
    header(cv, t, 'STEP 02', 'Semantic retrieval, computed locally')
    pipeline(cv, t, 1)
    qa = eo(p(t, .3, .9))
    rr(cv, 120, 400, 470, 150, 16, PANEL2, qa); rr(cv, 120, 400, 470, 150, 16, WHITE, qa, 2)
    text(cv, 'QUESTION', 150, 445, 17, TEAL, qa, 's', track=3)
    text(cv, 'What methodology was', 150, 488, 27, WHITE, qa, 'm')
    text(cv, 'used in the study?', 150, 524, 27, WHITE, qa, 'm')
    ea = eo(p(t, .9, 1.4))
    rr(cv, 230, 620, 250, 74, 14, PANEL2, ea); rr(cv, 230, 620, 250, 74, 14, TEAL, ea, 2)
    text(cv, 'nomic-embed-text', 355, 665, 21, WHITE, ea, 'mono', 'c')
    arrow(cv, 355, 552, 355, 616, TEAL, ea, 3, eo(p(t, 1.0, 1.4)), 11)
    # plot
    px, py, pw, ph = 760, 250, 1000, 640
    pa = eo(p(t, .5, 1.1))
    rr(cv, px, py, pw, ph, 18, PANEL, pa * .7); rr(cv, px, py, pw, ph, 18, LINE, pa, 2)
    text(cv, 'embedding space (2-D projection)', px + 24, py + 40, 19, MUTED, pa, 'm')
    P = pts(); Q = (.53, .44)
    qx, qy = px + Q[0] * pw, py + Q[1] * ph
    d = sorted(range(len(P)), key=lambda i: (P[i][0] - Q[0]) ** 2 + ((P[i][1] - Q[1]) * ph / pw) ** 2)
    top3 = d[:3]
    for i, (x, y) in enumerate(P):
        a = eo(p(t, .8 + i * .02, 1.2 + i * .02))
        hi = eo(p(t, 4.0 + top3.index(i) * .35, 4.4 + top3.index(i) * .35)) if i in top3 else 0
        cv.drawCircle(px + x * pw, py + y * ph, 8 + 3 * hi, paint(MUTED if hi < .5 else TEAL, a * (.55 + .45 * hi)))
    arrow(cv, 482, 657, qx - 30, qy + 10, TEAL, ea, 2.5, eo(p(t, 1.6, 2.3)), 12, dash=([8, 8],))
    qa2 = eo(p(t, 2.2, 2.6))
    if qa2 > 0:
        s = 16 * qa2; dp = skia.Path(); dp.moveTo(qx, qy - s); dp.lineTo(qx + s, qy); dp.lineTo(qx, qy + s); dp.lineTo(qx - s, qy); dp.close()
        cv.drawPath(dp, paint(WHITE, qa2)); text(cv, 'query', qx - 24, qy - 16, 20, WHITE, qa2, 's', 'r')
    ring = p(t, 2.7, 4.0)
    if 0 < ring < 1:
        cv.drawCircle(qx, qy, 40 + 200 * eo(ring), paint(TEAL, (1 - ring) * .7, 2))
    sims = ['0.82', '0.79', '0.74']
    for k, i in enumerate(top3):
        x, y = px + P[i][0] * pw, py + P[i][1] * ph
        la = eo(p(t, 4.0 + k * .35, 4.5 + k * .35))
        line(cv, qx, qy, x, y, TEAL, la, 2.5, la)
        text(cv, sims[k], x + 16, y + 30, 18, TEAL, la, 'mono')
    ta = eo(p(t, 5.2, 5.8))
    tag(cv, px + pw - 470, py + ph - 70, 'top-k = 3  ·  cosine similarity', ta, TEAL, 20, mono=True)

def s5(cv, t, T):
    header(cv, t, 'STEP 03', 'Local response generation with Ollama')
    pipeline(cv, t, 2)
    srcs = ['[1] lab-handout.pdf · p.4', '[2] methods.pdf · p.2', '[3] notes.txt']
    for i, s in enumerate(srcs):
        a = eo(p(t, .2 + i * .2, .7 + i * .2)); y = 300 + i * 120
        rr(cv, 110, y, 440, 96, 12, PANEL2, a); rr(cv, 110, y, 440, 96, 12, TEAL, a, 2)
        text(cv, s, 132, y + 36, 19, TEAL, a, 'mono')
        for j in range(2):
            line(cv, 132, y + 60 + j * 16, 132 + (380 if j == 0 else 260), y + 60 + j * 16, MUTED, a * .7, 4)
    text(cv, 'retrieved context + question', 330, 690, 20, MUTED, eo(p(t, .8, 1.3)), 'm', 'c')
    ox, oy = 960, 500
    oa = eo(p(t, 1.2, 1.8))
    rr(cv, ox - 190, oy - 200, 380, 400, 22, PANEL, oa); rr(cv, ox - 190, oy - 200, 380, 400, 22, TEAL, oa, 3)
    chip(cv, ox, oy - 60, .9, oa)
    text(cv, 'Ollama', ox, oy + 80, 36, WHITE, oa, 'd', 'c')
    text(cv, 'phi3 · open-source', ox, oy + 120, 22, MUTED, oa, 'mono', 'c')
    text(cv, '127.0.0.1:11434', ox, oy + 160, 19, TEAL, oa, 'mono', 'c')
    for i in range(3):
        arrow(cv, 556, 348 + i * 120, ox - 200, oy - 20 + i * 20, TEAL, oa, 2.5, eo(p(t, 1.8 + i * .15, 2.4 + i * .15)), 11)
    # pulse while generating
    gp = p(t, 2.6, 6.5)
    if 0 < gp < 1:
        r = (t * 1.2) % 1
        rr(cv, ox - 190 - 14 * r, oy - 200 - 14 * r, 380 + 28 * r, 400 + 28 * r, 26, TEAL, (1 - r) * .5, 2)
    arrow(cv, ox + 200, oy, 1290, oy, TEAL, 1, 3, eo(p(t, 2.6, 3.1)), 13)
    ax, ay, aw, ah = 1300, 300, 510, 400
    aa = eo(p(t, 2.9, 3.4))
    rr(cv, ax, ay, aw, ah, 16, PANEL2, aa); rr(cv, ax, ay, aw, ah, 16, WHITE, aa, 2)
    text(cv, 'ANSWER', ax + 28, ay + 46, 17, TEAL, aa, 's', track=3)
    lens = [440, 400, 450, 300, 420, 360, 250]
    for i, L in enumerate(lens):
        k = eo(p(t, 3.3 + i * .38, 3.7 + i * .38))
        line(cv, ax + 28, ay + 92 + i * 34, ax + 28 + L * k, ay + 92 + i * 34, WHITE, aa * .75, 6)
    xx = ax + 28
    for i, c in enumerate(['[1]', '[2]', '[3]']):
        ca = eo(p(t, 6.0 + i * .3, 6.4 + i * .3))
        xx += tag(cv, xx, ay + ah - 72, c, ca, TEAL, 19, mono=True) + 12
    na = eo(p(t, 7.0, 7.6))
    text(cv, 'Answers only from retrieved context.', ax + aw / 2, ay + ah + 46, 21, MUTED, na, 'm', 'c')
    text(cv, 'Off-topic → “I don\'t have that in the notes.”', ax + aw / 2, ay + ah + 78, 19, DIM, na, 'mono', 'c')

def s6(cv, t, T):
    a = eo(p(t, .1, .7))
    text(cv, 'THESIS TAKEAWAY', W / 2, 250, 24, TEAL, a, 's', 'c', track=5)
    a2 = eo(p(t, .4, 1.1))
    text(cv, 'High-accuracy answers.', W / 2, 360 + (1 - a2) * 16, 84, WHITE, a2, 'd', 'c')
    a3 = eo(p(t, 1.6, 2.3))
    text(cv, 'No internet connection.', W / 2, 460 + (1 - a3) * 16, 84, TEAL, a3, 'd', 'c')
    rows = [('Grounded in your own documents, with citations', 2.6), ('Runs offline: parsing, retrieval and generation', 3.6), ('No data leaves the device', 5.0)]
    for i, (s, st) in enumerate(rows):
        ra = eo(p(t, st, st + .5)); y = 590 + i * 76
        check(cv, 590, y, 1, ra, eo(p(t, st + .1, st + .6)))
        text(cv, s, 640, y + 11, 32, WHITE, ra, 'm')
    fa = eo(p(t, 5.8, 6.5))
    text(cv, 'Note Atlas  ·  Ollama  ·  ChromaDB  ·  nomic-embed-text  ·  phi3', W / 2, 950, 22, MUTED, fa, 'mono', 'c')

SCENES = [s0, s1, s2, s3, s4, s5, s6]

def frame(si, t, T):
    surf = skia.Surface(W, H)
    with surf as cv:
        bg(cv); SCENES[si](cv, t, T)
        fade = max(1 - p(t, 0, .3), p(t, T - .3, T)) if si not in (0,) else max(0, p(t, T - .3, T))
        if si == 0: fade = max(fade, 1 - p(t, 0, .35))
        if fade > 0: cv.drawRect(skia.Rect.MakeWH(W, H), paint(BG, fade))
    return surf.makeImageSnapshot()

def durations():
    d = json.load(open('dur.json'))
    return [round((x + LEAD + PAD) * FPS) for x in d]

if __name__ == '__main__':
    mode = sys.argv[1]
    NF = durations()
    if mode == 'still':
        si, t = int(sys.argv[2]), float(sys.argv[3])
        frame(si, t, NF[si] / FPS).save(f'still_{si}_{t}.png', skia.kPNG)
    elif mode == 'scene':
        si = int(sys.argv[2]); n = NF[si]; T = n / FPS
        tmp, out = f'scene{si}.tmp.mp4', f'scene{si}.mp4'
        pr = subprocess.Popen(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgba', '-s', f'{W}x{H}', '-r', str(FPS), '-i', '-',
                               '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '18', '-pix_fmt', 'yuv420p', '-r', str(FPS), tmp], stdin=subprocess.PIPE)
        for f in range(n):
            img = frame(si, f / FPS, T)
            pr.stdin.write(img.toarray(colorType=skia.kRGBA_8888_ColorType, alphaType=skia.kUnpremul_AlphaType).tobytes())
        pr.stdin.close()
        if pr.wait() == 0: os.rename(tmp, out); print('ok', si, n)
