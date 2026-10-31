import sys, os, json, math, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render_base as R
import render_modules as r2   # loads dur.json / lines.json from the build dir (cwd)
from render_base import *
from render_modules import box, xmark, note_card, board_icon, folder_icon, lineage_icon, steps_bar

LEAD, PAD, END_HOLD = 0.25, 0.55, 2.0
DUR = json.load(open('dur.json')); LINES = json.load(open('lines.json'))
r2.DUR, r2.LINES, r2.LEAD = DUR, LINES, LEAD

def cue(si, phrase, off=0.0):
    s = LINES[si]; i = s.find(phrase); assert i >= 0, (si, phrase)
    return LEAD + DUR[si] * i / len(s) + off

OLD2NEW = {2: 3, 3: 4, 4: 6, 5: 8, 6: 9, 7: 10, 8: 11, 9: 12, 10: 14, 11: 19}
r2.cue = lambda si, ph, off=0.0: cue(OLD2NEW[si], ph, off)

def nframes():
    return [round((d + LEAD + PAD + (END_HOLD if i == len(DUR) - 1 else 0)) * FPS) for i, d in enumerate(DUR)]

def ap(t, st, d=.5): return eo(p(t, st, st + d))

# ---------- 2: why RAG ----------
def n2(cv, t, T):
    header(cv, t, 'WHY RAG', 'Answers grounded in your own documents')
    qa = ap(t, .3)
    box(cv, 110, 440, 360, 130, qa, WHITE, PANEL2, 14, 2)
    text(cv, 'QUESTION', 135, 480, 16, TEAL, qa, 's', track=3)
    text(cv, 'What did the study find?', 135, 530, 25, WHITE, qa, 'm')
    lx, ly = 1220, 505
    la = ap(t, .6)
    box(cv, lx - 120, ly - 110, 240, 220, la, TEAL, PANEL2, 18); chip(cv, lx, ly - 25, .6, la)
    text(cv, 'LLM', lx, ly + 75, 26, WHITE, la, 's', 'c')
    # memory-only path
    tm = cue(2, 'memorised', -.3); ma = ap(t, tm) * (1 - ap(t, cue(2, 'handed', .6)) * .75)
    pa = skia.Path(); pa.moveTo(290, 436); pa.cubicTo(400, 250, 1000, 250, lx - 40, ly - 115)
    pt = paint(MUTED, ma * .8, 2.5, dash=([8, 8],)); cv.drawPath(pa, pt)
    text(cv, 'training memory only  →  may invent facts', 760, 282, 20, MUTED, ma, 'mono', 'c')
    xm = ap(t, tm + 1.0); xmark(cv, 760, 318, .9, ma * xm)
    # corpus
    th = cue(2, 'handed', -.4)
    ca = ap(t, th)
    text(cv, 'your documents', 735, 438, 19, MUTED, ca, 'm', 'c')
    hl = {(0, 1), (1, 3), (2, 0)}
    for r in range(3):
        for c in range(4):
            x, y = 600 + c * 90, 500 + r * 110
            on = (r, c) in hl; ka = ap(t, cue(2, 'most relevant', -.2) + (r * 4 + c) * .03)
            doc(cv, x, y, .5, ca, TEAL if on and ka > .5 else WHITE)
    arrow(cv, 475, 505, 560, 505, TEAL, ca, 3, ca, 11)
    ra = ap(t, cue(2, 'most relevant', .3))
    arrow(cv, 915, 505, lx - 128, 505, TEAL, ra, 3, ap(t, cue(2, 'most relevant', .3), .6), 12)
    text(cv, 'top passages', 1005, 490, 18, TEAL, ra, 'mono', 'c')
    # answer
    aa = ap(t, cue(2, 'must answer', -.2))
    arrow(cv, lx + 125, ly, 1415, ly, TEAL, aa, 3, aa, 12)
    box(cv, 1425, 380, 380, 260, aa, WHITE, PANEL2, 14, 2)
    text(cv, 'ANSWER', 1450, 420, 16, TEAL, aa, 's', track=3)
    for j, L in enumerate([320, 280, 300, 200]):
        line(cv, 1450, 460 + j * 30, 1450 + L * ap(t, cue(2, 'must answer') + j * .25, .5), 460 + j * 30, WHITE, aa * .7, 5)
    xx = 1450
    for k in range(3):
        xx += tag(cv, xx, 580, f'[{k + 1}]', ap(t, cue(2, 'citations', -.9) + k * .2), TEAL, 17, mono=True) + 10

# ---------- 5: board ask declines ----------
def n5(cv, t, T):
    header(cv, t, 'BOARDS  ·  ASK', 'Weak retrieval is declined, not guessed')
    qa = ap(t, .3)
    box(cv, 110, 300, 500, 130, qa, WHITE, PANEL2, 14, 2)
    text(cv, 'ASK  ·  off-topic question', 135, 340, 16, TEAL, qa, 's', track=2)
    text(cv, 'Which GPU does the lab use?', 135, 392, 26, WHITE, qa, 'm')
    px, py, pw, ph = 720, 260, 1080, 560
    pa = ap(t, .5)
    box(cv, px, py, pw, ph, pa, LINE, PANEL, 16, 2)
    text(cv, 'top note chunks · similarity (MiniLM)', px + 24, py + 40, 19, MUTED, pa, 'm')
    base = [0.22, 0.17, 0.14, 0.11, 0.07]; boost = [0, 0.08, 0, 0, 0]
    ts = cue(5, 'semantic similarity', -.3); tb = cue(5, 'boosts', -.2); tt = cue(5, 'threshold', -.3); td = cue(5, 'declines', -.6)
    y0 = py + ph - 70; sc = 900
    for i in range(5):
        x = px + 120 + i * 190; g = ap(t, ts + i * .12, .6)
        h = base[i] * sc * g
        rr(cv, x, y0 - h, 80, h, 6, MUTED, pa * .75)
        bh = boost[i] * sc * ap(t, tb, .6)
        if bh > 0:
            rr(cv, x, y0 - h - bh, 80, bh, 6, TEAL, pa)
            text(cv, '+ keyword', x + 40, y0 - h - bh - 14, 16, TEAL, ap(t, tb + .3), 'mono', 'c')
        text(cv, f'chunk {i + 1}', x + 40, y0 + 30, 16, DIM, pa, 'mono', 'c')
    ta = ap(t, tt)
    thy = y0 - .35 * sc
    line(cv, px + 60, thy, px + pw - 40, thy, WHITE, ta * .8, 2, ap(t, tt, .8), dash=([8, 7],))
    text(cv, 'threshold 0.35', px + pw - 40, thy - 14, 18, WHITE, ta, 'mono', 'r')
    da = ap(t, td)
    arrow(cv, 360, 435, 360, 600, TEAL, da, 3, da, 12)
    box(cv, 110, 610, 500, 150, da, TEAL, PANEL2, 14)
    text(cv, 'ANSWER', 135, 650, 16, TEAL, da, 's', track=3)
    text(cv, '“I don\'t have that in the notes.”', 135, 705, 25, WHITE, da, 'm')
    text(cv, 'nothing is invented', 135, 740, 17, MUTED, da, 'mono')

# ---------- 7: files options + Streamlit ----------
def toggle(cv, x, y, on, a):
    rr(cv, x, y, 72, 38, 19, TEALD if on > .5 else PANEL2, a); rr(cv, x, y, 72, 38, 19, TEAL if on > .5 else MUTED, a, 2)
    cv.drawCircle(x + lerp(19, 53, on), y + 19, 14, paint(WHITE, a))

def n7(cv, t, T):
    header(cv, t, 'FILES  ·  ENHANCEMENTS', 'Switchable improvements, one pipeline')
    opts = [('Word documents (.docx)', 'paragraphs and table rows, in order', 'Word documents'),
            ('Hybrid search', 'BM25 + vectors, reciprocal rank fusion (k = 60)', 'keyword search'),
            ('Conversational memory', 'recent turns carried into the prompt', 'conversational memory'),
            ('Model picker', 'any Ollama model already pulled', 'model picker')]
    for i, (n, sub, ph) in enumerate(opts):
        st = cue(7, ph, -.3); a = ap(t, .3 + i * .15); on = eio(p(t, st, st + .4)); y = 290 + i * 130
        toggle(cv, 120, y, on, a)
        text(cv, n, 220, y + 18, 26, WHITE, a, 's')
        text(cv, sub, 220, y + 52, 18, MUTED, a, 'mono')
    text(cv, 'each switch: FILES_* setting, 1 = on, 0 = off', 120, 840, 18, DIM, ap(t, 1.2), 'mono')
    # streamlit window
    ts7 = cue(7, 'The same pipeline', -.3); sa = ap(t, ts7, .7); wx, wy, ww, wh = 960, 270, 840, 580
    if sa > 0:
        box(cv, wx, wy, ww, wh, sa, WHITE, PANEL, 12, 2)
        rr(cv, wx, wy, ww, 44, 12, PANEL2, sa)
        for k in range(3): cv.drawCircle(wx + 24 + k * 20, wy + 22, 6, paint(DIM, sa))
        text(cv, 'localhost:8501  ·  Simple RAG with Phi-3', wx + ww / 2, wy + 29, 17, MUTED, sa, 'mono', 'c')
        rr(cv, wx + 1, wy + 44, 230, wh - 45, 0, BG, sa * .8)
        text(cv, 'Folders', wx + 20, wy + 86, 18, WHITE, sa, 's')
        for k, f in enumerate(['Lectures', 'Thesis']): text(cv, '› ' + f, wx + 24, wy + 122 + k * 32, 17, MUTED, sa, 'r')
        box(cv, wx + 20, wy + 210, 190, 44, sa, TEAL, TEALD, 8, 2)
        text(cv, 'Build Knowledge Base', wx + 115, wy + 238, 14, WHITE, sa, 's', 'c')
        text(cv, 'Stored chunks: 412', wx + 20, wy + 290, 15, MUTED, sa, 'mono')
        mx = wx + 260
        box(cv, mx, wy + 70, 550, 60, sa, LINE, PANEL2, 10, 1.5)
        text(cv, 'What methodology was used in the study?', mx + 18, wy + 108, 18, WHITE, sa, 'm')
        for j, L in enumerate([500, 460, 380]):
            line(cv, mx + 18, wy + 170 + j * 28, mx + 18 + L * ap(t, ts7 + .6 + j * .25), wy + 170 + j * 28, WHITE, sa * .7, 5)
        text(cv, 'Retrieved 3 chunks.', mx + 18, wy + 290, 16, TEAL, ap(t, ts7 + 1.5), 'mono')
        for j in range(3):
            ea = ap(t, ts7 + 1.7 + j * .2)
            box(cv, mx, wy + 310 + j * 70, 550, 56, ea * sa, LINE, PANEL2, 8, 1.5)
            text(cv, f'› Retrieved Context {j + 1}  ·  lecture.pdf p.{[4, 7, 2][j]}', mx + 16, wy + 345 + j * 70, 16, MUTED, ea * sa, 'mono')

# ---------- 13: research ask ----------
def n13(cv, t, T):
    header(cv, t, 'RESEARCH ASK', 'Questions answered from claims, not raw text')
    papers = ['Paper A', 'Paper B', 'Paper C', 'Paper D']
    chips = ['RQ', 'Method', 'Results', 'Scope', 'C1', 'C2', 'L1']
    ti = cue(13, 'indexed', -.4)
    for i, pname in enumerate(papers):
        a = ap(t, .3 + i * .15); y = 270 + i * 140
        box(cv, 110, y, 560, 115, a, WHITE, PANEL2, 12, 1.8)
        text(cv, pname, 132, y + 38, 22, WHITE, a, 's')
        xx = 132
        for c in chips:
            lim = c.startswith('L'); hl = lim and p(t, cue(13, 'exact claim', -1.2), cue(13, 'exact claim', -.6)) > 0
            xx += tag(cv, xx, y + 58, c, a, TEAL if (c[0] in 'CL' and not hl) or hl else MUTED, 15, fill=TEALD if hl else None, mono=True) + 6
    ia = ap(t, ti)
    arrow(cv, 680, 500, 800, 500, TEAL, ia, 3, ia, 12)
    cylinder(cv, 920, 480, .7, ia)
    text(cv, 'research index', 920, 610, 22, WHITE, ia, 's', 'c')
    text(cv, 'fields + claims · MiniLM', 920, 642, 17, MUTED, ia, 'mono', 'c')
    nf = ap(t, cue(13, 'never the full text', -.3))
    tag(cv, 840, 690, 'full text', nf, MUTED, 18, mono=True)
    line(cv, 838, 709, 1000, 709, WHITE, nf, 3, ap(t, cue(13, 'never the full text', .2), .5))
    qa = ap(t, cue(13, 'searches', -.2))
    box(cv, 1110, 270, 690, 110, qa, WHITE, PANEL2, 12, 2)
    text(cv, 'Which limitations do these papers share?', 1135, 335, 23, WHITE, qa, 'm')
    arrow(cv, 1035, 480, 1100, 480, TEAL, qa, 3, qa, 11)
    aa = ap(t, cue(13, 'every citation', -.4))
    box(cv, 1110, 410, 690, 380, aa, TEAL, PANEL2, 12)
    text(cv, 'ANSWER', 1135, 450, 16, TEAL, aa, 's', track=3)
    for j, L in enumerate([620, 560, 600, 400]):
        line(cv, 1135, 490 + j * 32, 1135 + L * ap(t, cue(13, 'every citation', -.2) + j * .25), 490 + j * 32, WHITE, aa * .7, 6)
    for k, c in enumerate(['[1] Limitation L1 · Paper A', '[2] Limitation L1 · Paper C']):
        tag(cv, 1135, 640 + k * 62, c, ap(t, cue(13, 'exact claim', -.2) + k * .3), TEAL, 18, mono=True)

# ---------- 14: privacy ----------
def n14(cv, t, T):
    header(cv, t, 'PRIVACY', 'Scholarly lookups are minimal and optional')
    b = ap(t, .3); bx, by, bw, bh = 360, 260, 1200, 600
    box(cv, bx, by, bw, bh, b, TEAL, PANEL, 18, 2.5)
    text(cv, 'OpenAlex · Crossref fallback · Semantic Scholar with your own key', bx + 40, by + 54, 20, MUTED, b, 'mono')
    sends = ['titles', 'DOIs', 'OpenAlex IDs']; never = ['PDFs', 'extracted text', 'notes']
    ts = cue(14, 'only titles', -.2); tn = cue(14, 'never', -.2)
    text(cv, 'Sends', bx + 60, by + 130, 26, WHITE, ap(t, ts, .4), 's')
    for i, s in enumerate(sends):
        k = ap(t, ts + i * .2, .4); check(cv, bx + 85, by + 185 + i * 66, .9, k, k); text(cv, s, bx + 130, by + 194 + i * 66, 26, WHITE, k, 'm')
    text(cv, 'Never sends', bx + 640, by + 130, 26, WHITE, ap(t, tn, .4), 's')
    for i, s in enumerate(never):
        k = ap(t, tn + i * .2, .4); xmark(cv, bx + 665, by + 185 + i * 66, .9, k); text(cv, s, bx + 710, by + 194 + i * 66, 26, WHITE, k, 'm')
    tt = cue(14, 'switched off', -.3); sw = eio(p(t, tt + .3, tt + .9)); ka = ap(t, tt - .2)
    sx, sy = bx + 60, by + 450
    rr(cv, sx, sy, 110, 56, 28, TEALD if sw < .5 else PANEL2, ka); rr(cv, sx, sy, 110, 56, 28, TEAL if sw < .5 else MUTED, ka, 2)
    cv.drawCircle(sx + lerp(82, 28, sw), sy + 28, 21, paint(WHITE, ka))
    text(cv, 'Lookups on' if sw < .5 else 'Lookups off  →  no network calls; metadata from the PDF only', sx + 140, sy + 37, 24, WHITE, ka, 'm')

# ---------- 15: MCP bridge ----------
def n15(cv, t, T):
    header(cv, t, 'CLAUDE  ·  MCP', 'Model Context Protocol bridge')
    y = 540
    nodes = [(270, 'Claude Code', 'Claude Desktop', 'MCP client', 'Claude Code'),
             (760, 'mcp_server.py', 'local, launched by client', 'MCP server', 'small local server'),
             (1230, 'Atlas backend', 'FastAPI · 127.0.0.1:8888', 'HTTP API', 'running backend'),
             (1650, 'Boards · Files', 'Research Track', 'data', 'running backend')]
    for i, (x, a1, a2, kind, ph) in enumerate(nodes):
        a = ap(t, cue(15, ph, -.4) + (i == 3) * .4)
        w = 340 if i < 3 else 280
        box(cv, x - w / 2, y - 110, w, 220, a, TEAL if i == 1 else WHITE, PANEL2, 16, 2.5 if i == 1 else 2)
        text(cv, kind.upper(), x, y - 62, 15, TEAL, a, 's', 'c', track=2)
        text(cv, a1, x, y - 8, 28, WHITE, a, 'mono' if i == 1 else 's', 'c')
        text(cv, a2, x, y + 32, 18, MUTED, a, 'r' if i != 2 else 'mono', 'c')
        if i == 3:
            for k in range(3): cv.drawCircle(x - 40 + k * 40, y + 72, 8, paint(TEAL, a))
    links = [(440, 590, 'stdio', 'standard input'), (930, 1060, 'HTTP', 'running backend'), (1400, 1510, '', 'running backend')]
    for x1, x2, lbl, ph in links:
        a = ap(t, cue(15, ph, -.1))
        line(cv, x1, y - 18, x2, y - 18, TEAL, a, 2.5); line(cv, x1, y + 18, x2, y + 18, TEAL, a, 2.5)
        if lbl: text(cv, lbl, (x1 + x2) / 2, y - 34, 18, TEAL, a, 'mono', 'c')
        # moving packets
        if a > .9:
            for d in (0, 1):
                ph2 = ((t * .7) + d * .5) % 1
                xx = lerp(x1, x2, ph2) if d == 0 else lerp(x2, x1, ph2)
                cv.drawCircle(xx, y - 18 if d == 0 else y + 18, 6, paint(WHITE, a))
    la = ap(t, cue(15, 'Model Context Protocol', -.3))
    text(cv, 'An open standard that lets AI clients call tools on local servers', W / 2, 330, 24, MUTED, la, 'r', 'c')
    ba = ap(t, cue(15, 'standard input', .5))
    text(cv, 'claude mcp add atlas -- backend/.venv/bin/python backend/mcp_server.py', W / 2, 790, 20, DIM, ba, 'mono', 'c')

# ---------- 16: tools ----------
def n16(cv, t, T):
    header(cv, t, 'CLAUDE  ·  MCP', 'Nine tools over the running backend')
    tools = [('list_boards', 'Boards and counts', 'boards and notes'), ('list_notes', 'note titles', 'boards and notes'),
             ('get_note', 'one note, topics, points', 'boards and notes'), ('search', 'best-matching passages', 'semantic search'),
             ('ask', 'Atlas RAG answer, cited', 'grounded Ask'), ('list_studies', 'papers and leads', 'research library'),
             ('get_study', 'extraction, claims, lineage', 'research library'), ('research_ask', 'answers over claims', 'and Research Ask'),
             ('create_note', 'adds a note to a Board', 'except creating')]
    for i, (n, sub, ph) in enumerate(tools):
        r, c = divmod(i, 3); x, y = 150 + c * 560, 270 + r * 190
        a = ap(t, cue(16, ph, -.2) + (i % 3) * .12)
        write = n == 'create_note'
        box(cv, x, y, 520, 160, a, WHITE if write else TEAL, PANEL2, 14, 2.5 if write else 2)
        text(cv, n, x + 26, y + 58, 28, WHITE, a, 'mono')
        text(cv, sub, x + 26, y + 98, 19, MUTED, a, 'r')
        ba = ap(t, cue(16, 'read-only', -.2) + i * .05) if not write else ap(t, cue(16, 'except creating', .2))
        tag(cv, x + 26, y + 112, 'write' if write else 'read-only', ba, WHITE if write else TEAL, 14, fill=PANEL if write else None, mono=True)
    ea = ap(t, T - 3.2)
    text(cv, '“Which papers in my Atlas library deal with PII, and what are their limitations?”', W / 2, 880, 21, MUTED, ea, 'r', 'c')

# ---------- 17: boundary ----------
def n17(cv, t, T):
    header(cv, t, 'CLAUDE  ·  MCP', 'An optional bridge across the device boundary')
    bx = 1080
    ba = ap(t, .3)
    line(cv, bx, 260, bx, 880, WHITE, ba * .7, 2.5, ap(t, .3, .8), dash=([12, 10],))
    text(cv, 'YOUR MACHINE', bx - 40, 290, 18, TEAL, ba, 's', 'r', track=3)
    text(cv, 'ANTHROPIC API', bx + 40, 290, 18, WHITE, ap(t, cue(17, 'runs in the cloud', -.3)), 's', track=3)
    la = ap(t, .4)
    box(cv, 140, 380, 360, 260, la, TEAL, PANEL2, 16)
    text(cv, 'Atlas', 320, 440, 30, WHITE, la, 's', 'c')
    text(cv, 'Boards · Files · Research', 320, 478, 18, MUTED, la, 'r', 'c')
    chip(cv, 320, 560, .5, la); text(cv, 'Ollama, local', 320, 625, 16, TEAL, la, 'mono', 'c')
    box(cv, 600, 440, 300, 140, la, TEAL, PANEL2, 14)
    text(cv, 'mcp_server.py', 750, 520, 22, WHITE, la, 'mono', 'c')
    line(cv, 500, 510, 600, 510, TEAL, la, 2.5)
    ra = ap(t, cue(17, 'runs in the cloud', -.4))
    server(cv, 1460, 530, .9, ra, WHITE, 4, MUTED)
    text(cv, 'Claude', 1460, 700, 28, WHITE, ra, 's', 'c'); text(cv, 'hosted model', 1460, 734, 18, MUTED, ra, 'r', 'c')
    fa = ap(t, cue(17, 'leaves the machine', -.5))
    arrow(cv, 905, 480, 1330, 480, WHITE, fa, 2.5, fa, 12)
    arrow(cv, 1330, 560, 905, 560, MUTED, fa * .8, 2, fa, 10)
    text(cv, 'results: notes, claims', 1100, 462, 16, WHITE, fa, 'mono')
    text(cv, 'tool calls', 1100, 596, 16, MUTED, fa, 'mono')
    oa = ap(t, cue(17, 'optional', -.2))
    tag(cv, 140, 790, 'Optional: off by default, added only when you configure it', oa, WHITE, 20)
    na = ap(t, cue(17, 'never depends', -.3))
    tag(cv, 140, 700, 'Local pipeline works without it', na, TEAL, 22)

# ---------- 18: accuracy ----------
def n18(cv, t, T):
    header(cv, t, 'DESIGN FOR ACCURACY', 'Accuracy from constraint, not model size')
    cols = [('Cite', 'Every answer names the notes, pages\nor claims it drew on', 'cite their sources'),
            ('Decline', 'Weak retrieval returns “I don\'t have\nthat” instead of a guess', 'declined'),
            ('Verify', 'A limitation is kept only if its quote\nis found in the paper', 'verified quote')]
    for i, (h, sub, ph) in enumerate(cols):
        x = 140 + i * 560; a = ap(t, cue(18, ph, -.6), .6)
        box(cv, x, 290, 500, 520, a, TEAL, PANEL2, 18)
        cx, cy = x + 250, 450
        if i == 0:
            for k in range(3): tag(cv, cx - 150 + k * 105, cy - 22, f'[{k + 1}]', a, TEAL, 26, mono=True)
        elif i == 1:
            for k, hh in enumerate([60, 44, 30]): rr(cv, cx - 90 + k * 70, cy + 50 - hh, 44, hh, 5, MUTED, a * .7)
            line(cv, cx - 120, cy - 30, cx + 130, cy - 30, WHITE, a, 2, dash=([7, 6],))
            text(cv, '0.35', cx + 140, cy - 24, 18, WHITE, a, 'mono')
        else:
            check(cv, cx, cy, 2.2, a, ap(t, cue(18, ph, -.4), .5))
        text(cv, h, cx, 600, 40, WHITE, a, 'd', 'c')
        for j, ln in enumerate(sub.split('\n')):
            text(cv, ln, cx, 660 + j * 34, 21, MUTED, a, 'r', 'c')
    ta = ap(t, cue(18, 'accuracy comes', -.3))
    text(cv, 'Across Boards, Files, Research Track and the Claude bridge', W / 2, 880, 20, DIM, ta, 'mono', 'c')

SC = [r2.v0, R.s1, n2, r2.v2, r2.v3, n5, r2.v4, n7, r2.v5, r2.v6, r2.v7, r2.v8, r2.v9, n13, n14, n15, n16, n17, n18, r2.v11]

def frame(si, t, T):
    surf = skia.Surface(W, H)
    with surf as cv:
        bg(cv); SC[si](cv, t, T)
        fade = max(1 - p(t, 0, .35), p(t, T - .35, T))
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
