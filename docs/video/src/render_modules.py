import sys, os, json, math, random, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render_base as R
from render_base import *  # helpers, palette, icons, s1

LEAD, PAD = 0.2, 0.35
DUR = json.load(open('dur.json'))
LINES = json.load(open('lines.json'))

def cue(si, phrase, off=0.0):
    s = LINES[si]; i = s.find(phrase)
    assert i >= 0, (si, phrase)
    return LEAD + DUR[si] * i / len(s) + off

def nframes():
    out = []
    for i, d in enumerate(DUR):
        extra = 1.2 if i == len(DUR) - 1 else 0
        out.append(round((d + LEAD + PAD + extra) * FPS))
    return out

def steps_bar(cv, t, active, names, y=1000):
    a = eo(p(t, 0, .5)); n = len(names); span = 300 * (n - 1)
    xs = [W / 2 - span / 2 + 300 * i for i in range(n)]
    line(cv, xs[0], y, xs[-1], y, LINE, a, 3)
    if active >= 0: line(cv, xs[0], y, xs[active], y, TEAL, a, 3)
    for i, x in enumerate(xs):
        on = i <= active
        cv.drawCircle(x, y, 15, paint(TEAL if i == active else (TEALD if on else PANEL2), a))
        cv.drawCircle(x, y, 15, paint(TEAL if on else LINE, a, 2.5))
        text(cv, str(i + 1), x, y + 6, 16, BG if i == active else WHITE, a, 'b', 'c')
        text(cv, names[i], x, y + 46, 20, WHITE if i == active else DIM, a, 's' if i == active else 'm', 'c')

RSTEPS = ['Parse', 'Extract', 'Limitations', 'Lineage']

# ---------- module icons ----------
def board_icon(cv, cx, cy, s=1, a=1):
    rr(cv, cx - 90 * s, cy - 65 * s, 180 * s, 130 * s, 12 * s, BG, a); rr(cv, cx - 90 * s, cy - 65 * s, 180 * s, 130 * s, 12 * s, TEAL, a, 2.5)
    pts = [(-50, -30), (40, -32), (-20, 30)]
    line(cv, cx - 50 * s, cy - 30 * s, cx + 40 * s, cy - 32 * s, TEAL, a, 2)
    line(cv, cx - 50 * s, cy - 30 * s, cx - 20 * s, cy + 30 * s, TEAL, a, 2)
    for x, y in pts:
        rr(cv, cx + (x - 26) * s, cy + (y - 16) * s, 52 * s, 32 * s, 5 * s, PANEL2, a); rr(cv, cx + (x - 26) * s, cy + (y - 16) * s, 52 * s, 32 * s, 5 * s, WHITE, a, 2)

def folder_icon(cv, cx, cy, s=1, a=1, c=TEAL):
    w, h = 170 * s, 120 * s; x, y = cx - w / 2, cy - h / 2 + 10 * s
    pa = skia.Path(); pa.moveTo(x, y); pa.lineTo(x + 60 * s, y); pa.lineTo(x + 75 * s, y + 16 * s); pa.lineTo(x + w, y + 16 * s)
    pa.lineTo(x + w, y + h); pa.lineTo(x, y + h); pa.close()
    cv.drawPath(pa, paint(PANEL2, a)); cv.drawPath(pa, paint(c, a, 2.5))
    line(cv, x, y + 34 * s, x + w, y + 34 * s, c, a, 2)

def lineage_icon(cv, cx, cy, s=1, a=1):
    nodes = [(0, 45), (-55, -10), (55, -10), (-80, -60), (-25, -60), (80, -60)]
    for (i, j) in [(0, 1), (0, 2), (1, 3), (1, 4), (2, 5)]:
        line(cv, cx + nodes[i][0] * s, cy + nodes[i][1] * s, cx + nodes[j][0] * s, cy + nodes[j][1] * s, TEAL, a, 2)
    for k, (x, y) in enumerate(nodes):
        cv.drawCircle(cx + x * s, cy + y * s, (16 if k == 0 else 11) * s, paint(WHITE if k == 0 else TEAL, a))

def note_card(cv, x, y, title, a=1, w=230, h=118, hl=0.0):
    rr(cv, x, y, w, h, 10, PANEL2, a); rr(cv, x, y, w, h, 10, TEAL if hl > .5 else WHITE, a * (.9 if hl > .5 else .75), 2)
    text(cv, title, x + 16, y + 34, 19, WHITE, a, 's')
    line(cv, x + 16, y + 62, x + w - 30, y + 62, MUTED, a * .6, 4)
    line(cv, x + 16, y + 82, x + w - 80, y + 82, MUTED, a * .6, 4)

def xmark(cv, cx, cy, s=1, a=1):
    cv.drawCircle(cx, cy, 22 * s, paint(WHITE, a * .08)); cv.drawCircle(cx, cy, 22 * s, paint(MUTED, a, 2.5))
    line(cv, cx - 9 * s, cy - 9 * s, cx + 9 * s, cy + 9 * s, WHITE, a, 4); line(cv, cx - 9 * s, cy + 9 * s, cx + 9 * s, cy - 9 * s, WHITE, a, 4)

def box(cv, x, y, w, h, a=1, c=TEAL, fill=PANEL2, r=16, sw=2.5):
    rr(cv, x, y, w, h, r, fill, a); rr(cv, x, y, w, h, r, c, a, sw)

# ---------- scenes ----------
def v0(cv, t, T):
    a = eo(p(t, .1, .8))
    text(cv, 'NOTE ATLAS  ·  RESEARCH EXPLAINER', W / 2, 330, 24, TEAL, a, 's', 'c', track=5)
    a2 = eo(p(t, .4, 1.2))
    text(cv, 'Local Retrieval-Augmented Generation', W / 2, 440 + (1 - a2) * 20, 80, WHITE, a2, 'd', 'c')
    a3 = eo(p(t, 1.0, 1.8))
    text(cv, 'A local-first research workspace: Boards · Files · Research Track', W / 2, 510, 32, MUTED, a3, 'l', 'c')
    a4 = eo(p(t, 1.6, 2.4)); bx, by, bw, bh = W / 2 - 430, 600, 860, 270
    rr(cv, bx, by, bw, bh, 22, TEAL, a4 * .9, 2.5, dash=([14, 10],))
    text(cv, 'localhost · 127.0.0.1', bx + 26, by + 40, 20, TEAL, a4, 'mono')
    cx = [W / 2 - 280, W / 2, W / 2 + 280]; cy = by + 150
    ap = [eo(p(t, 2.0 + i * .45, 2.6 + i * .45)) for i in range(3)]
    board_icon(cv, cx[0], cy, .8, ap[0]); folder_icon(cv, cx[1], cy, .8, ap[1]); lineage_icon(cv, cx[2], cy, .9, ap[2])

def v2(cv, t, T):
    header(cv, t, 'ARCHITECTURE', 'One machine, three modules')
    g = eo(p(t, .4, 1.3))
    bx, by, bw, bh = 140, 250, 1640, 640
    rr(cv, bx, by, bw, bh, 26, PANEL, g * .55); rr(cv, bx, by, bw, bh, 26, TEAL, g, 2.5, dash=([14, 10],))
    text(cv, 'localhost · 127.0.0.1  ·  no cloud services required', bx + 30, by + 46, 21, TEAL, g, 'mono')
    mods = [('Boards', 'notes on a spatial canvas', board_icon, 'Boards'), ('Files', 'folders of PDFs, DOCX, TXT', folder_icon, 'Files'),
            ('Research Track', 'uploaded academic papers', lineage_icon, 'Research Track')]
    for i, (name, sub, icon, ph) in enumerate(mods):
        st = cue(2, ph, -.2); ma = eo(p(t, st, st + .6))
        x = bx + 60 + i * 520; y = by + 90 + (1 - ma) * 20
        box(cv, x, y, 480, 300, ma, TEAL if i == 2 else WHITE, PANEL2, 18, 2.5 if i == 2 else 2)
        icon(cv, x + 240, y + 115, 1.0, ma)
        text(cv, name, x + 240, y + 235, 32, WHITE, ma, 's', 'c')
        text(cv, sub, x + 240, y + 272, 21, MUTED, ma, 'r', 'c')
    infra = [('FastAPI :8888', 'Backend'), ('SQLite + sqlite-vec', 'vector stores'), ('ChromaDB', 'vector stores'),
             ('GROBID :8070 (Docker)', 'vector stores'), ('Ollama :11434', 'Ollama')]
    xx = bx + 60; yy = by + 470
    text(cv, 'SHARED LOCAL STACK', bx + 60, yy - 18, 17, MUTED, eo(p(t, cue(2, 'Backend', -.3), cue(2, 'Backend', .3))), 's', track=3)
    for i, (lbl, ph) in enumerate(infra):
        st = cue(2, ph, -.1) + i * .18; ia = eo(p(t, st, st + .4))
        xx += tag(cv, xx, yy, lbl, ia, TEAL if 'Ollama' in lbl else WHITE, 21, mono=True) + 16
    text(cv, 'Ollama models:  qwen3:4b · phi3 · nomic-embed-text      Embeddings:  all-MiniLM-L6-v2', bx + 60, yy + 110, 19, DIM,
         eo(p(t, cue(2, 'across', 0), cue(2, 'across', .6))), 'mono')

def v3(cv, t, T):
    header(cv, t, 'MODULE 1  ·  BOARDS', 'Notes on a canvas, joined by strings')
    px, py, pw, ph = 120, 250, 1110, 650
    ca = eo(p(t, .3, .9))
    rr(cv, px, py, pw, ph, 18, PANEL, ca * .7); rr(cv, px, py, pw, ph, 18, LINE, ca, 2)
    text(cv, 'Board canvas', px + pw - 20, py + ph - 20, 18, MUTED, ca, 'm', 'r')
    notes = {1: (170, 310, 'Local RAG basics'), 2: (480, 300, 'Chunking strategy'), 3: (260, 520, 'Embedding models'),
             4: (870, 520, 'Ollama setup'), 5: (880, 310, 'Privacy risks')}
    c = lambda k: (notes[k][0] + 115, notes[k][1] + 59)
    t_topic = cue(3, 'extracts'); t_emb = cue(3, 'embeddings'); t_lasso = cue(3, 'lasso'); t_ans = cue(3, 'answers only')
    # strings
    line(cv, *c(1), *c(2), TEAL, ca * .8, 2.5)
    line(cv, *c(5), *c(4), TEAL, ca * .8, 2.5)
    gs = eo(p(t, t_emb, t_emb + .6)); acc = eo(p(t, t_emb + 1.6, t_emb + 2.1))
    if gs > 0:
        line(cv, *c(2), *c(3), TEAL, gs * (1 - acc) * .9, 2.5, dash=([8, 8],))
        line(cv, *c(2), *c(3), TEAL, acc * .9, 2.5)
        mx, my = (c(2)[0] + c(3)[0]) / 2, (c(2)[1] + c(3)[1]) / 2
        tag(cv, mx - 270, my + 8, 'suggested · cos 0.61' if acc < .5 else 'string accepted', gs, TEAL, 16, mono=True)
    aa0 = eo(p(t, t_ans, t_ans + .6))
    if aa0 > 0:
        for k in (2, 3):
            line(cv, 770, 720, *c(k), TEAL, aa0 * .9, 2.5, eo(p(t, t_ans + .3, t_ans + 1.0)))
    for k, (x, y, ttl) in notes.items():
        na = eo(p(t, .5 + k * .12, 1.0 + k * .12))
        note_card(cv, x, y, ttl, na, hl=1 if k == 2 and p(t, t_topic, t_topic + 2) > 0 else 0)
    # extraction shimmer on note 2
    sh = p(t, t_topic, t_topic + 1.4)
    if 0 < sh < 1:
        x, y = notes[2][0], notes[2][1]
        sx = x + 230 * sh
        rr(cv, sx - 30, y + 2, 40, 114, 6, TEAL, .25 * math.sin(sh * math.pi))
    ta = eo(p(t, t_topic + 1.2, t_topic + 1.7))
    if ta > 0:
        x, y = notes[2][0], notes[2][1]
        xx = x; xx += tag(cv, xx, y + 126, '#chunking', ta, TEAL, 15, mono=True) + 8; tag(cv, xx, y + 126, '#rag', ta, TEAL, 15, mono=True)
    # lasso
    la = eo(p(t, t_lasso, t_lasso + .8))
    if la > 0:
        lw, lh = 620 * la, 390 * la
        rr(cv, 150, 285, lw, lh, 14, WHITE, .8, 2, dash=([6, 6], -t * 30))
        text(cv, 'Shift-drag lasso  →  /  Ask', 160, 285 + lh + 30, 18, WHITE, la, 'mono')
    aa = eo(p(t, t_ans, t_ans + .6))
    if aa > 0:
        ax, ay = 620, 720
        box(cv, ax, ay, 300, 150, aa, TEAL, PANEL2, 12)
        text(cv, 'ASK · ANSWER', ax + 18, ay + 32, 15, TEAL, aa, 's', track=2)
        for j, L in enumerate([250, 220, 160]):
            line(cv, ax + 18, ay + 62 + j * 22, ax + 18 + L * eo(p(t, t_ans + .4 + j * .3, t_ans + .8 + j * .3)), ay + 62 + j * 22, WHITE, aa * .7, 5)
        text(cv, 'cites 2 notes', ax + 18, ay + 136, 15, MUTED, aa, 'mono')
    # feature list
    feats = [('Topic + tag extraction', 'local LLM (qwen3:4b), wording kept', t_topic),
             ('Related-note strings', 'MiniLM embeddings, 384-d, sqlite-vec', t_emb),
             ('Lasso-scoped Ask', 'declines below similarity 0.35', t_lasso)]
    for i, (f, sub, st) in enumerate(feats):
        fa = eo(p(t, st, st + .5)); y = 330 + i * 150
        check(cv, 1300, y, 1, fa, eo(p(t, st + .1, st + .6)))
        text(cv, f, 1345, y + 2, 27, WHITE, fa, 's')
        text(cv, sub, 1345, y + 38, 19, MUTED, fa, 'r')

def v4(cv, t, T):
    header(cv, t, 'MODULE 2  ·  FILES', 'A classic RAG pipeline over document folders')
    xs = [220, 470, 720, 970, 1220, 1470, 1720]; y = 520
    names = [('Folder', 'PDF · DOCX · TXT'), ('Extract', 'PyMuPDF, per page'), ('Chunk', '500 characters'), ('Embed', 'nomic-embed-text'),
             ('Store', 'ChromaDB'), ('Retrieve', 'top-3, cosine'), ('Generate', 'phi3 via Ollama')]
    cues = [cue(4, 'Documents', -.3), cue(4, 'Documents', .4), cue(4, 'split'), cue(4, 'embedded'), cue(4, 'Chroma'), cue(4, 'three nearest'), cue(4, 'ground')]
    for i in range(6):
        k = eo(p(t, cues[i + 1] - .3, cues[i + 1] + .2))
        arrow(cv, xs[i] + 92, y, xs[i + 1] - 92, y, TEAL, 1, 3, k, 11)
    for i, (n, sub) in enumerate(names):
        a = eo(p(t, cues[i] - .2, cues[i] + .3)); lit = p(t, cues[i], cues[i] + .3)
        box(cv, xs[i] - 85, y - 85, 170, 170, a, TEAL if lit > 0 else LINE, PANEL2, 16)
        cx, cy = xs[i], y - 6
        if i == 0: folder_icon(cv, cx, cy, .62, a)
        elif i == 1: doc(cv, cx, cy, .7, a)
        elif i == 2:
            for j in range(4): rr(cv, cx - 50, cy - 46 + j * 25, 100, 18, 4, TEAL if j == 0 else WHITE, a * (.9 if j == 0 else .55))
        elif i == 3:
            for j in range(8): rr(cv, cx - 58 + j * 15, cy - 22, 11, 44, 3, TEAL, a * (.3 + .7 * ((j * 37) % 10) / 10))
        elif i == 4: cylinder(cv, cx, cy, .45, a)
        elif i == 5:
            for j in range(3): cv.drawCircle(cx - 34 + j * 34, cy, 13, paint(TEAL, a))
        else: chip(cv, cx, cy, .55, a)
        text(cv, n, xs[i], y + 125, 26, WHITE, a, 's', 'c')
        text(cv, sub, xs[i], y + 158, 18, MUTED, a, 'mono', 'c')
    ca = eo(p(t, cue(4, 'cited by page'), cue(4, 'cited by page', .5)))
    x0 = 1240; yy = 780
    text(cv, 'Sources', x0, yy + 20, 18, MUTED, ca, 'm')
    xx = x0 + 90
    for s in ['lecture.pdf · p.4', 'notes.txt · p.1']:
        xx += tag(cv, xx, yy - 8, s, ca, TEAL, 17, mono=True) + 10
    oa = eo(p(t, cue(4, 'Chroma', .8), cue(4, 'Chroma', 1.3)))
    text(cv, 'Optional: BM25 + vector hybrid search, fused by reciprocal rank', 120, 800, 19, DIM, oa, 'mono')

def v5(cv, t, T):
    header(cv, t, 'MODULE 3  ·  RESEARCH TRACK', 'Every uploaded paper enters a job queue')
    da = eo(p(t, .3, .8)); drop = eio(p(t, .5, 1.3))
    doc(cv, 240, lerp(300, 560, drop), 1.1, da)
    text(cv, 'paper.pdf', 240, 690, 22, MUTED, da * drop, 'mono', 'c')
    xs = [600, 900, 1200, 1500]; y = 560
    subs = ['GROBID → TEI XML', 'fields + contributions', 'quote-verified', 'parent papers']
    st0 = cue(5, 'resumable', -.4)
    for i in range(4):
        a = eo(p(t, st0 + i * .3, st0 + .5 + i * .3))
        if i < 3: arrow(cv, xs[i] + 125, y, xs[i + 1] - 125, y, TEAL, a, 3, a, 11)
        box(cv, xs[i] - 120, y - 100, 240, 200, a, TEAL, PANEL2, 18)
        text(cv, f'0{i + 1}', xs[i], y - 38, 22, TEAL, a, 'mono', 'c')
        text(cv, RSTEPS[i], xs[i], y + 8, 32, WHITE, a, 'd', 'c')
        text(cv, subs[i], xs[i], y + 52, 18, MUTED, a, 'r', 'c')
    arrow(cv, 310, 560, 470, 560, TEAL, drop, 3, eo(p(t, 1.2, 1.7)), 12)
    # token moving through steps
    tk = p(t, st0 + 1.4, T - .3)
    if tk > 0:
        x = lerp(xs[0], xs[3], eio(tk)); cv.drawCircle(x, y + 125, 9, paint(TEAL, 1))
    ba = eo(p(t, cue(5, 'four-step'), cue(5, 'four-step', .5)))
    text(cv, 'one worker  ·  one paper at a time  ·  a failed step is retried alone', W / 2 + 90, 790, 21, MUTED, ba, 'mono', 'c')

def v6(cv, t, T):
    header(cv, t, 'RESEARCH  ·  STEP 01', 'Parse: PDF to structured XML')
    steps_bar(cv, t, 0, RSTEPS)
    da = eo(p(t, .2, .7)); doc(cv, 210, 520, 1.15, da, label='paper.pdf')
    ga = eo(p(t, cue(6, 'GROBID', -.3), cue(6, 'GROBID', .3)))
    arrow(cv, 280, 520, 420, 520, TEAL, ga, 3, ga, 11)
    box(cv, 430, 420, 300, 200, ga, TEAL, PANEL2, 18)
    text(cv, 'GROBID', 580, 500, 36, WHITE, ga, 'd', 'c')
    text(cv, 'local Docker container', 580, 540, 18, MUTED, ga, 'r', 'c')
    text(cv, '127.0.0.1:8070', 580, 578, 18, TEAL, ga, 'mono', 'c')
    ta = eo(p(t, cue(6, 'structured'), cue(6, 'structured', .4)))
    arrow(cv, 735, 520, 860, 520, TEAL, ta, 3, ta, 11)
    box(cv, 870, 260, 560, 560, ta, WHITE, PANEL, 14, 2)
    text(cv, 'paper.tei.xml', 892, 296, 18, MUTED, ta, 'mono')
    xml = [('<teiHeader>', 0, 'metadata'), ('<title> … </title>', 1, 'metadata'), ('<author> … </author>', 1, 'metadata'),
           ('</teiHeader>', 0, 'metadata'), ('<body>', 0, 'sections'), ('<div><head>Method</head> …', 1, 'sections'),
           ('<div><head>Results</head> …', 1, 'sections'), ('</body>', 0, 'sections'), ('<listBibl>', 0, 'every reference'),
           ('<biblStruct> … </biblStruct>', 1, 'every reference'), ('<biblStruct> … </biblStruct>', 1, 'every reference'), ('</listBibl>', 0, 'every reference')]
    for i, (s, ind, ph) in enumerate(xml):
        st = cue(6, ph, -.3) + (i % 4) * .12
        xa = eo(p(t, st, st + .3)) * ta
        col = TEAL if s.startswith('<') and not s.startswith('<div') and not s.startswith('<title') and not s.startswith('<author') and not s.startswith('<biblStruct') else WHITE
        text(cv, s, 900 + ind * 32, 345 + i * 38, 20, col, xa, 'mono')
    # leads
    lst = cue(6, 'stored as a lead', -.4)
    for i in range(6):
        la = eo(p(t, lst + i * .15, lst + .4 + i * .15))
        y = 300 + i * 68
        arrow(cv, 1435, 735, 1500, y + 22, LINE, la * .8, 2, la, 8)
        tag(cv, 1510, y, f'Lead  · ref {i + 1}' if i < 5 else '+ 37 more', la, TEAL if i < 5 else MUTED, 18, mono=True)
    fa = eo(p(t, cue(6, 'lead', .6), cue(6, 'lead', 1.1)))
    text(cv, 'GROBID unavailable → plain text via pypdf, without references', 120, 880, 19, DIM, fa, 'mono')

def v7(cv, t, T):
    header(cv, t, 'RESEARCH  ·  STEP 02', 'Extract: structured fields and claims')
    steps_bar(cv, t, 1, RSTEPS)
    da = eo(p(t, .2, .7)); doc(cv, 210, 540, 1.15, da, label='paper body')
    ca = eo(p(t, cue(7, 'local model', -.3), cue(7, 'local model', .3)))
    arrow(cv, 280, 540, 430, 540, TEAL, ca, 3, ca, 11)
    box(cv, 440, 420, 300, 240, ca, TEAL, PANEL2, 18)
    chip(cv, 590, 500, .6, ca)
    text(cv, 'local LLM', 590, 600, 26, WHITE, ca, 's', 'c')
    text(cv, 'qwen3:4b · JSON schema', 590, 634, 17, MUTED, ca, 'mono', 'c')
    ea = eo(p(t, cue(7, 'records', -.2), cue(7, 'records', .3)))
    arrow(cv, 745, 540, 880, 540, TEAL, ea, 3, ea, 11)
    box(cv, 890, 250, 900, 620, ea, WHITE, PANEL, 16, 2)
    text(cv, 'EXTRACTION', 920, 292, 17, TEAL, ea, 's', track=3)
    fields = [('Research question', 'research question'), ('Method', 'method'), ('Key results', 'key results'), ('Scope', 'scope')]
    for i, (f, ph) in enumerate(fields):
        st = cue(7, ph, -.1); fa = eo(p(t, st, st + .3)) * ea; y = 330 + i * 90
        text(cv, f, 920, y + 22, 21, MUTED, fa, 'm')
        line(cv, 1150, y + 15, 1150 + 590 * eo(p(t, st + .1, st + .8)), y + 15, WHITE, fa * .7, 6)
        line(cv, 1150, y + 38, 1150 + 420 * eo(p(t, st + .3, st + 1.0)), y + 38, WHITE, fa * .45, 6)
        line(cv, 920, y + 66, 1760, y + 66, LINE, fa, 1)
    st = cue(7, 'each contribution', -.1)
    text(cv, 'Contributions', 920, 712, 21, MUTED, eo(p(t, st, st + .3)) * ea, 'm')
    xx = 920
    for i in range(3):
        k = eo(p(t, st + .3 + i * .3, st + .7 + i * .3)) * ea
        xx += tag(cv, xx, 740, f'Claim · C{i + 1}', k, TEAL, 19, mono=True) + 12
    text(cv, 'each claim is individually editable and can be sent to a Board', 920, 832, 17, DIM, eo(p(t, st + 1.4, st + 1.9)) * ea, 'r')

def v8(cv, t, T):
    header(cv, t, 'RESEARCH  ·  STEP 03', 'Limitations: kept only if the quote is verified')
    steps_bar(cv, t, 2, RSTEPS)
    cands = [('Small sample (n = 24)', '“our sample of 24 participants limits …”'),
             ('No offline evaluation', '“… evaluated without a network …”'),
             ('Larger corpora planned', '“future work will use larger corpora”')]
    g1x, g2x, outx = 860, 1240, 1560
    g1 = eo(p(t, cue(8, 'kept only', -.4), cue(8, 'kept only', .2)))
    g2 = eo(p(t, cue(8, 'second check', -.4), cue(8, 'second check', .2)))
    for gx, ga, l1, l2 in [(g1x, g1, 'Quote in full text?', 'fuzzy match ≥ 0.85'), (g2x, g2, 'Admits a weakness?', 'second LLM check')]:
        box(cv, gx - 150, 280, 300, 560, ga, TEAL, PANEL, 18, 2.5)
        text(cv, l1, gx, 330, 23, WHITE, ga, 's', 'c'); text(cv, l2, gx, 362, 17, MUTED, ga, 'mono', 'c')
    oa = eo(p(t, cue(8, 'second check', .8), cue(8, 'second check', 1.3)))
    box(cv, outx, 380, 300, 200, oa, TEAL, PANEL, 14)
    text(cv, 'KEPT  ·  limitation + quote', outx + 150, 422, 16, TEAL, oa, 's', 'c', track=1)
    t0 = cue(8, 'verbatim', -.3)
    fate = [(True, True), (False, None), (True, False)]
    for i, (lbl, q) in enumerate(cands):
        ca = eo(p(t, t0 + i * .25, t0 + .5 + i * .25)); y0 = 300 + i * 175
        # positions
        tA = cue(8, 'kept only', .3) + i * .35
        tB = cue(8, 'second check', .3) + i * .35
        mv1 = eio(p(t, tA, tA + .7))
        ok1, ok2 = fate[i]
        x = lerp(110, g1x - 136, mv1); y = lerp(y0, 420 + i * 120 - 20, mv1)
        alpha = ca
        if not ok1: alpha *= 1 - p(t, tA + 1.4, tA + 2.0)
        if ok1:
            mv2 = eio(p(t, tB, tB + .7))
            x = lerp(x, g2x - 136, mv2)
            if ok2 is False: alpha *= 1 - p(t, tB + 1.4, tB + 2.0)
            if ok2:
                mv3 = eio(p(t, tB + 1.3, tB + 2.0)); x = lerp(x, outx + 32, mv3); y = lerp(y, 455, mv3)
        w = 236
        if alpha > 0:
            box(cv, x, y, w, 100, alpha, WHITE, PANEL2, 10, 2)
            text(cv, lbl, x + 14, y + 32, 16, WHITE, alpha, 's')
            text(cv, q[:27] + ('…' if len(q) > 27 else ''), x + 14, y + 62, 13, MUTED, alpha, 'mono')
        # gate marks
        m1 = eo(p(t, tA + .7, tA + 1.0));
        if m1 > 0 and mv1 >= 1:
            (check(cv, g1x + 120, 420 + i * 120 + 30, .9, m1 * (alpha if not ok1 else 1)) if ok1 else xmark(cv, g1x + 120, 420 + i * 120 + 30, .9, alpha))
        if ok1:
            m2 = eo(p(t, tB + .7, tB + 1.0))
            if m2 > 0:
                (check(cv, g2x + 120, 420 + i * 120 + 30, .9, m2) if ok2 else xmark(cv, g2x + 120, 420 + i * 120 + 30, .9, alpha))
    # kept arrow
    ka = eo(p(t, cue(8, 'second check', 1.0), cue(8, 'second check', 1.5)))
    arrow(cv, g2x + 150, 480, outx - 10, 480, TEAL, ka, 3, ka, 11)

def v9(cv, t, T):
    header(cv, t, 'RESEARCH  ·  STEP 04', 'Lineage: which references the paper builds on')
    steps_bar(cv, t, 3, RSTEPS)
    px, py = 960, 840
    pa = eo(p(t, .2, .7))
    n = 10; xs = [360 + i * 133 for i in range(n)]; ry = 590
    where = ['M', 'I', 'R', 'M', 'I', 'I', 'M', 'R', 'I', 'M']
    scores = [8.5, 2.0, 5.0, 7.0, 1.5, 3.0, 9.0, 4.5, 2.5, 6.5]
    parents = [i for i in range(n) if scores[i] >= 6]
    t_rank = cue(9, 'ranked'); t_score = cue(9, 'scores'); t_par = cue(9, 'strongest'); t_sib = cue(9, 'siblings')
    sel = eo(p(t, t_par, t_par + .6))
    for i, x in enumerate(xs):
        ra = eo(p(t, .4 + i * .06, .8 + i * .06))
        isp = i in parents
        ea = ra * (1 - sel * (0 if isp else .75))
        line(cv, x, ry + 16, px, py - 22, TEAL if (isp and sel > .5) else LINE, ea * (1 if isp and sel > .5 else .7), 3 if isp and sel > .5 else 1.5)
    for i, x in enumerate(xs):
        ra = eo(p(t, .4 + i * .06, .8 + i * .06)); isp = i in parents
        ea = ra * (1 - sel * (0 if isp else .7))
        cv.drawCircle(x, ry, 16, paint(TEAL if isp and sel > .5 else PANEL2, ea)); cv.drawCircle(x, ry, 16, paint(TEAL if isp else WHITE, ea, 2.5))
        wa = eo(p(t, t_rank + i * .05, t_rank + .4 + i * .05)) * ea
        text(cv, where[i], x, ry + 52, 17, MUTED, wa, 'mono', 'c')
        # bars
        ba = eo(p(t, t_score + i * .08, t_score + .5 + i * .08)) * (1 - eo(p(t, t_sib - .4, t_sib + .2)))
        if ba > 0:
            h = 150 * scores[i] / 10 * ba
            rr(cv, x - 13, ry - 30 - h, 26, h, 4, TEAL if scores[i] >= 6 else MUTED, ra * (.95 if scores[i] >= 6 else .5) * (1 - sel * (0 if isp else .5)))
    ba = eo(p(t, t_score, t_score + .5)) * (1 - eo(p(t, t_sib - .4, t_sib + .2)))
    thr = ry - 30 - 150 * .6
    line(cv, 320, thr, 1640, thr, WHITE, ba * .6, 1.5, dash=([6, 6],))
    text(cv, 'builds-on ≥ 6 / 10', 1650, thr + 6, 17, WHITE, ba, 'mono')
    la = eo(p(t, t_rank, t_rank + .5))
    text(cv, 'cited in:  M = Method  >  R = Results  >  I = Intro / related work', 360, 300, 17, DIM, la * (1 - eo(p(t, t_sib - .4, t_sib))), 'mono')
    # paper
    cv.drawCircle(px, py, 24, paint(WHITE, pa)); text(cv, 'this paper', px + 38, py + 7, 20, WHITE, pa, 's')
    # ancestors and siblings
    aa = eo(p(t, t_sib, t_sib + .7))
    if aa > 0:
        anc = [(parents[0], -60), (parents[0], 40), (parents[1], 0), (parents[2], -30), (parents[3], 50)]
        for j, (pi, dx) in enumerate(anc):
            ax, ay = xs[pi] + dx, 330
            line(cv, xs[pi], ry - 16, ax, ay + 12, TEAL, aa * .6, 2)
            cv.drawCircle(ax, ay, 12, paint(TEALD, aa)); cv.drawCircle(ax, ay, 12, paint(TEAL, aa, 2))
        text(cv, 'Ancestors · up to 2 hops', 360, 300, 19, TEAL, aa, 'm')
        for j, (sx, pi) in enumerate([(560, parents[0]), (1380, parents[3])]):
            line(cv, xs[pi], ry + 16, sx, py, MUTED, aa * .7, 2, dash=([6, 6],))
            cv.drawCircle(sx, py, 18, paint(PANEL2, aa)); cv.drawCircle(sx, py, 18, paint(MUTED, aa, 2.5))
        text(cv, 'Siblings · share a parent', 560, py + 50, 18, MUTED, aa, 'm', 'c')
        text(cv, 'Parent papers', xs[parents[-1]] + 40, ry - 40, 19, TEAL, aa, 's')

def v10(cv, t, T):
    header(cv, t, 'RESEARCH ASK  ·  PRIVACY', 'Ask across papers; lookups stay minimal')
    a = eo(p(t, .2, .8))
    box(cv, 120, 260, 800, 600, a, WHITE, PANEL, 18, 2)
    text(cv, 'RESEARCH ASK', 150, 304, 17, TEAL, a, 's', track=3)
    text(cv, 'index: fields + claims of each paper (no full text)', 150, 344, 18, MUTED, a, 'mono')
    qa = eo(p(t, .8, 1.3))
    box(cv, 150, 380, 740, 90, qa, WHITE, PANEL2, 12, 2)
    text(cv, 'Which limitations do these papers share?', 175, 435, 24, WHITE, qa, 'm')
    an = eo(p(t, 1.6, 2.1))
    box(cv, 150, 500, 740, 320, an, TEAL, PANEL2, 12, 2)
    for j, L in enumerate([660, 600, 640, 420]):
        line(cv, 175, 550 + j * 34, 175 + L * eo(p(t, 1.9 + j * .3, 2.3 + j * .3)), 550 + j * 34, WHITE, an * .7, 6)
    xx = 175
    for i, c in enumerate(['[1] Limitation · Paper A', '[2] Limitation · Paper C']):
        xx += tag(cv, xx, 740, c, eo(p(t, 3.0 + i * .3, 3.4 + i * .3)), TEAL, 17, mono=True) + 12
    # privacy
    t0 = cue(10, 'Optional', -.3); b = eo(p(t, t0, t0 + .5))
    box(cv, 1000, 260, 800, 600, b, TEAL, PANEL, 18, 2.5)
    text(cv, 'SCHOLARLY LOOKUPS  ·  OPTIONAL', 1030, 304, 17, TEAL, b, 's', track=3)
    text(cv, 'OpenAlex, Crossref fallback', 1030, 344, 18, MUTED, b, 'mono')
    sends = ['titles', 'DOIs', 'OpenAlex IDs']; never = ['PDFs', 'extracted text', 'notes']
    ts = cue(10, 'only titles', -.2); tn = cue(10, 'never', -.2)
    text(cv, 'Sends', 1030, 410, 22, WHITE, eo(p(t, ts, ts + .4)), 's')
    for i, s in enumerate(sends):
        k = eo(p(t, ts + i * .2, ts + .4 + i * .2)); check(cv, 1055, 460 + i * 58, .8, k, k); text(cv, s, 1095, 468 + i * 58, 22, WHITE, k, 'm')
    text(cv, 'Never sends', 1420, 410, 22, WHITE, eo(p(t, tn, tn + .4)), 's')
    for i, s in enumerate(never):
        k = eo(p(t, tn + i * .2, tn + .4 + i * .2)); xmark(cv, 1445, 460 + i * 58, .8, k); text(cv, s, 1485, 468 + i * 58, 22, WHITE, k, 'm')
    tt = cue(10, 'switched off', -.3); sw = eio(p(t, tt + .3, tt + .9)); ka = eo(p(t, tt - .2, tt + .3))
    sx, sy = 1030, 700
    rr(cv, sx, sy, 96, 50, 25, TEALD if sw < .5 else PANEL2, ka); rr(cv, sx, sy, 96, 50, 25, TEAL if sw < .5 else MUTED, ka, 2)
    cv.drawCircle(sx + lerp(71, 25, sw), sy + 25, 19, paint(WHITE, ka))
    text(cv, 'Lookups on' if sw < .5 else 'Lookups off → no network calls', sx + 120, sy + 34, 23, WHITE, ka, 'm')

def v11(cv, t, T):
    a = eo(p(t, .1, .7))
    text(cv, 'THESIS TAKEAWAY', W / 2, 250, 24, TEAL, a, 's', 'c', track=5)
    a2 = eo(p(t, .4, 1.1))
    text(cv, 'High-accuracy, grounded answers.', W / 2, 360 + (1 - a2) * 16, 78, WHITE, a2, 'd', 'c')
    t3 = cue(11, 'no internet', -.3); a3 = eo(p(t, t3, t3 + .6))
    text(cv, 'No internet connection required.', W / 2, 455 + (1 - a3) * 16, 78, TEAL, a3, 'd', 'c')
    rows = [('Boards, Files and Research Track share one local stack', cue(11, 'no internet', .6)),
            ('Every answer and claim is traceable to its source', cue(11, 'no document', -.4)),
            ('No document ever leaves the device', cue(11, 'leaving', -.2))]
    for i, (s, st) in enumerate(rows):
        ra = eo(p(t, st, st + .5)); y = 590 + i * 76
        check(cv, 540, y, 1, ra, eo(p(t, st + .1, st + .6)))
        text(cv, s, 590, y + 11, 32, WHITE, ra, 'm')
    fa = eo(p(t, T - 2.0, T - 1.3))
    text(cv, 'Note Atlas  ·  Ollama  ·  GROBID  ·  ChromaDB  ·  sqlite-vec', W / 2, 950, 22, MUTED, fa, 'mono', 'c')

SC = [v0, R.s1, v2, v3, v4, v5, v6, v7, v8, v9, v10, v11]

def frame(si, t, T):
    surf = skia.Surface(W, H)
    with surf as cv:
        bg(cv); SC[si](cv, t, T)
        fade = max(1 - p(t, 0, .3), p(t, T - .3, T))
        if fade > 0: cv.drawRect(skia.Rect.MakeWH(W, H), paint(BG, fade))
    return surf.makeImageSnapshot()

if __name__ == '__main__':
    NF = nframes(); mode = sys.argv[1]
    if mode == 'still':
        si, t = int(sys.argv[2]), float(sys.argv[3])
        frame(si, t, NF[si] / FPS).save(f'still_{si:02d}_{t}.png', skia.kPNG)
    elif mode == 'scene':
        si = int(sys.argv[2]); n = NF[si]; T = n / FPS
        tmp, out = f'scene{si:02d}.tmp.mp4', f'scene{si:02d}.mp4'
        pr = subprocess.Popen(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgba', '-s', f'{W}x{H}', '-r', str(FPS), '-i', '-',
                               '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '18', '-pix_fmt', 'yuv420p', '-r', str(FPS), tmp], stdin=subprocess.PIPE)
        for f in range(n):
            pr.stdin.write(frame(si, f / FPS, T).toarray(colorType=skia.kRGBA_8888_ColorType, alphaType=skia.kUnpremul_AlphaType).tobytes())
        pr.stdin.close()
        if pr.wait() == 0: os.rename(tmp, out); print('ok', si, n)
    elif mode == 'frames':
        print(NF, sum(NF) / FPS)
