#!/usr/bin/env python3
"""Check whether the latest assistant reply contains a fabricated user turn.
Called as a Stop hook; reads JSON containing transcript_path from stdin.
Use --test <file.jsonl> to scan a past log in one go.
"""
import json, sys, re, os, datetime

JST = datetime.timezone(datetime.timedelta(hours=9))

def jst(ts):
    try:
        return datetime.datetime.fromisoformat(ts.replace('Z','+00:00')).astimezone(JST).strftime('%m/%d %H:%M:%S')
    except Exception:
        return (ts or '')[:19]

# After "user" comes either "whitespace + something" or a non-ASCII char (Japanese).
# Words like "username" are not matched.
# Only words that never appear in ordinary Japanese text are matched at line start.
# 「システム」 (system) and 「思考」 (thinking) are everyday words, so they are only
# checked via LABEL_ONLY (the whole body is that single word).
#   Real false positive: 「システムのデモ映像あります」 ("there's a demo video of the system")
PAT = re.compile(r'(?m)^[ \t]*(?:user(?![A-Za-z_.\-])[ \t]*\S|système)')
# "système" also leaks on a line of its own (observed: 5 of 5 cases appeared together
#  with a user label that had body text, but if it shows up alone, only the current
#  pattern can catch it). It carries an accent, so it never appears in ordinary text:
#  zero false positives.
#
# Reading guideline (author's observation, 2026-08-21):
#   Once any label has leaked, **treat everything after it as suspected fabrication.**
#   In 20 of 23 observed cases, everything after the label was fabricated. Fabrication
#   without a label also appears right after a label leak (3rd element of 08/13 13:20).
MIN_POS = 0.00          # No filtering by position. Judge by the label running to the end
LABEL_ONLY = {'思考', 'système', 'システム', 'thinking', 'Thinking', 'system'}

# ── Script mixing ────────────────────────────────────────────
# Scripts other than Japanese and Latin/digits. Greek letters are common in math,
# so the main letters are excluded
GREEK_OK = set('αβγδεζηθικλμνξοπρστυφχψωΑΒΓΔΘΛΞΠΣΦΨΩ')
SCRIPTS = [
    ('Cyrillic',   'Ѐ-ӿ'),
    ('Greek',      'Ͱ-Ͽ'),
    ('Hangul',     'ᄀ-ᇿ㄰-㆏가-힯'),
    ('Thai',       '฀-๿'),
    ('Arabic',     '؀-ۿ'),
    ('Hebrew',     '֐-׿'),
    ('Devanagari', 'ऀ-ॿ'),
    ('Armenian',   '԰-֏'),
    ('Georgian',   'Ⴀ-ჿ'),
]
SCRIPT_PAT = [(name, re.compile(f'[{rng}]')) for name, rng in SCRIPTS]

# Simplified Chinese shares the block with kanji, so it cannot be caught by script range.
# Look directly for characters that Japanese does not use
SIMPLIFIED = re.compile(
    '[讠-谶钅-镳'   # simplified 讠 / 钅 radicals (说话语请谁课…). 谷 (8c37) onward is Japanese, so excluded
    '这们东车马门问题现实经济发际关时应该个为从长图书电视网'
    '无业乐买卖儿么样过进开给种员亲爱产权势习华丽风飞鸟鱼龙齿]')

def check_script(text):
    body = re.sub(r'```.*?```', '', text, flags=re.S)
    body = re.sub(r'`[^`\n]*`', '', body)               # exclude inline code too
    for name, pat in SCRIPT_PAT:
        for m in pat.finditer(body):
            ch = m.group()
            if name == 'Greek' and ch in GREEK_OK:
                continue
            s = max(0, m.start() - 12); e = min(len(body), m.end() + 12)
            return (name, ch, body[s:e].replace('\n', ' '))
    m = SIMPLIFIED.search(body)
    if m:
        s = max(0, m.start() - 12); e = min(len(body), m.end() + 12)
        return ('Simplified Chinese', m.group(), body[s:e].replace('\n', ' '))
    return None


# ── Do referenced things exist? ──────────────────────────────
# Verifiable without reading the language. Works whether or not a label leaked
PATHRE = re.compile(r'(?:/Users/[A-Za-z0-9._-]+|~)/[A-Za-z0-9._/\- ]{2,80}')
URLRE  = re.compile(r'https?://[^\s)\]<>"\'）」、。]+')
REFLOG = os.path.expanduser('~/.claude/hooks/refs.log')

def _norm_path(p):
    """For forms with trailing words attached (`~/.claude 2.5GB`), drop one word at a
    time until an existing path is found"""
    p = p.strip().rstrip('.、。,')
    while p:
        if os.path.exists(os.path.expanduser(p)):
            return p, True
        if ' ' in p:
            p = p.rsplit(' ', 1)[0].rstrip('.、。,')
        else:
            # If it is only cut off partway through a real name
            # ("Application" -> "Application Support"), let it pass
            full = os.path.expanduser(p)
            parent, base = os.path.dirname(full), os.path.basename(full)
            try:
                if base and any(e.startswith(base) for e in os.listdir(parent)):
                    return p, True
            except Exception:
                pass
            return p, False
    return p, False

def check_refs(text, log_urls=True):
    """Return local paths that do not exist. URLs are only recorded, not judged
    (no network access)"""
    body = re.sub(r'```.*?```', '', text, flags=re.S)   # fences are mostly examples, so excluded
    missing = []
    for raw in PATHRE.findall(body):
        p, exists = _norm_path(raw)
        if len(p) >= 4 and not exists and p not in missing:
            missing.append(p)
    if log_urls:
        urls = URLRE.findall(body)
        if urls:
            try:
                with open(REFLOG, 'a', encoding='utf-8') as f:
                    stamp = datetime.datetime.now(JST).strftime('%Y-%m-%d %H:%M:%S')
                    for u in dict.fromkeys(urls):
                        f.write(f'{stamp}\t{u}\n')
            except Exception:
                pass
    return missing


def check(text):
    body = re.sub(r'```.*?```', '', text, flags=re.S)   # exclude code fences
    if not body.strip():
        return None
    if body.strip() in LABEL_ONLY:                     # body is a single label word
        return (0, len(body.strip()), f'[label only] {body.strip()}', 1, 1)
    m = PAT.search(body)
    if not m:
        return None
    pos = m.start() / len(body)
    if pos < MIN_POS:
        return None
    tail = body[m.start():]
    lines = len([l for l in tail.split('\n') if l.strip()])
    paras = len([b for b in re.split(r'\n\s*\n', tail) if b.strip()])
    head = tail[:70].replace('\n', ' ')
    return (round(pos*100), len(tail), head, lines, paras)

def find_truncated(path):
    """Find an assistant message that has no stop_reason.
    The very last one may not be finalized yet, so it is excluded (avoids false positives).
    The only axis with no guessing: the record itself says "not finished".

    On the CLI (entrypoint: cli), however, the previous assistant record sometimes has
    no stop_reason yet at the moment this hook runs, so this axis is not used there.
    Counting the saved jsonl afterwards shows 0 missing on the CLI too (a matter of
    timing at hook time, not a gap in the record). In the desktop app, only 1 of 3,900
    was missing even at hook time."""
    rows = []
    is_cli = False
    with open(path, encoding='utf-8', errors='replace') as f:
        for line in f:
            try: o = json.loads(line)
            except: continue
            if o.get('entrypoint') == 'cli':
                is_cli = True
            if o.get('type') != 'assistant': continue
            m = o.get('message', {}) or {}
            c = m.get('content')
            t = ''.join(b.get('text','') for b in c if isinstance(b, dict)) if isinstance(c, list) else ''
            if not t.strip(): continue
            rows.append((m.get('stop_reason'), t, o.get('timestamp','')))
    if is_cli or len(rows) < 2:
        return None
    sr, t, ts = rows[-2]                    # look only at the previous (finalized) one
    if sr:
        return None
    return (jst(ts), len(t), t.strip()[-40:].replace('\n', ' '))


def last_assistant_text(path):
    last = None
    with open(path, encoding='utf-8', errors='replace') as f:
        for line in f:
            try: o = json.loads(line)
            except: continue
            if o.get('type') != 'assistant': continue
            for c in (o.get('message', {}).get('content') or []):
                if isinstance(c, dict) and c.get('type') == 'text' and c.get('text', '').strip():
                    last = c['text']
    return last

def main():
    if len(sys.argv) > 2 and sys.argv[1] == '--test':
        n = 0
        with open(sys.argv[2], encoding='utf-8', errors='replace') as f:
            for line in f:
                try: o = json.loads(line)
                except: continue
                if o.get('type') != 'assistant': continue
                for c in (o.get('message', {}).get('content') or []):
                    if isinstance(c, dict) and c.get('type') == 'text':
                        txt = c.get('text', '')
                        r = check(txt)
                        if r:
                            n += 1
                            print(f"  {jst(o.get('timestamp',''))} [label] at {r[0]:3d}% / {r[1]:4d} chars / {r[3]:2d} lines / {r[4]} paras  {r[2]}")
                        s = check_script(txt)
                        if s:
                            n += 1
                            print(f"  {jst(o.get('timestamp',''))} [{s[0]}] \"{s[1]}\"  …{s[2]}…")
                        mp = check_refs(txt, log_urls=False)
                        if mp:
                            n += 1
                            print(f"  {jst(o.get('timestamp',''))} [path] nonexistent path: {' / '.join(mp[:3])}")
        print(f"{n} detection(s) (timestamps in JST)")
        return 0
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    tp = payload.get('transcript_path')
    # Record that the hook was called at all (for checking it runs; delete if noisy)
    try:
        with open(os.path.expanduser('~/.claude/hooks/invocations.log'), 'a', encoding='utf-8') as f:
            f.write(datetime.datetime.now(JST).strftime('%Y-%m-%d %H:%M:%S')
                    + '\t' + (os.path.basename(tp)[:8] if tp else 'no-path') + '\n')
    except Exception:
        pass
    if not tp or not os.path.exists(tp):
        return 0
    # The Stop hook can run before the last reply is written to the .jsonl (observed on CLI).
    # Wait a moment and re-read; if the file grew, use the newer text
    t = last_assistant_text(tp)
    try:
        import time
        size = os.path.getsize(tp)
        time.sleep(0.5)
        if os.path.getsize(tp) != size:
            t2 = last_assistant_text(tp)
            if t2:
                t = t2
    except Exception:
        pass
    if not t:
        return 0
    msgs = []
    r = check(t)
    if r:
        msgs.append(f"label leak (at {r[0]}%, {r[1]} chars, {r[3]} lines, {r[4]} paras): {r[2][:60]}")
    s = check_script(t)
    if s:
        msgs.append(f"{s[0]} mixed in \"{s[1]}\" …{s[2][:40]}…")
    mp = check_refs(t)
    if mp:
        msgs.append(f"nonexistent path → {' / '.join(mp[:3])}")
    tr = find_truncated(tp)
    if tr:
        msgs.append(f"previous reply unfinished (no stop_reason, {tr[1]} chars) {tr[0]} JST, ends: …{tr[2]}")

    if msgs:
        stamp = datetime.datetime.now(JST).strftime('%Y-%m-%d %H:%M:%S')
        # (1) Permanent record (timestamps in JST)
        try:
            with open(os.path.expanduser('~/.claude/hooks/detections.log'), 'a', encoding='utf-8') as f:
                for m in msgs:
                    f.write(f'{stamp}\t{os.path.basename(tp)[:8]}\t{m}\n')
        except Exception:
            pass
        # (2) Alert with a sound (notifications need permission, so not used; sound does not)
        #     Disable: environment variable CLAUDE_DETECT_SOUND=0
        if os.environ.get('CLAUDE_DETECT_SOUND', '1') != '0':
            try:
                import subprocess, platform
                if platform.system() == 'Darwin':
                    snd = '/System/Library/Sounds/Funk.aiff'
                    if os.path.exists(snd):
                        subprocess.Popen(['afplay', snd],
                                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                else:
                    sys.stderr.write('\a')      # terminal bell on other OSes
            except Exception:
                pass
        # (3) Try systemMessage, which is in the schema (no error even if it is not shown)
        try:
            print(json.dumps({"systemMessage": "⚠ Detected: " + " / ".join(msgs)[:300]},
                             ensure_ascii=False))
        except Exception:
            pass
    return 0          # Always 0. Never block the stop (exit 2 risks a loop)

sys.exit(main())
