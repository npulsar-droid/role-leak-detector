#!/usr/bin/env python3
"""直近の assistant 返答に、捏造された user ターンが混ざっていないか検査する。
Stop フックから呼ばれ、stdin に transcript_path を含む JSON を受け取る。
--test <file.jsonl> で過去ログに対して一括検査もできる。
"""
import json, sys, re, os, datetime

JST = datetime.timezone(datetime.timedelta(hours=9))

def jst(ts):
    try:
        return datetime.datetime.fromisoformat(ts.replace('Z','+00:00')).astimezone(JST).strftime('%m/%d %H:%M:%S')
    except Exception:
        return (ts or '')[:19]

# user の直後は「空白＋何か」または「非ASCII（日本語）」。username 等は拾わない
# 行頭一致で拾うのは、日本語の通常文に現れない語だけ。
# 「システム」「思考」は日常語なので LABEL_ONLY（本文がその1語のみ）でしか判定しない。
#   誤検知の実例: 「システムのデモ映像あります」
PAT = re.compile(r'(?m)^[ \t]*(?:user(?![A-Za-z_.\-])[ \t]*\S|système)')
# 「système」は単独行でも漏れる（実測: 5件中5件が本文つきの user ラベルと同時だったが、
#  単独で出れば現在の形でしか拾えない）。アクサン付きなので通常文には出ず、誤検知ゼロ。
#
# 判定の指針（本人の観察・2026-08-21）:
#   いずれかのラベルが漏れた時点で、**それ以降は全て捏造の疑いとして読む。**
#   実測23件のうち20件が「ラベル以降すべて捏造」。ラベルの無い捏造も
#   ラベル漏れの直後に現れる（08/13 13:20 の3要素目）。
MIN_POS = 0.00          # 位置では絞らない。ラベル以降が末尾まで続く形で判定する
LABEL_ONLY = {'思考', 'système', 'システム', 'thinking', 'Thinking', 'system'}

# ── 文字体系の混入 ──────────────────────────────────────────
# 日本語・英数以外の文字体系。ギリシャ文字は数式で普通に使うので主要な字を除外する
GREEK_OK = set('αβγδεζηθικλμνξοπρστυφχψωΑΒΓΔΘΛΞΠΣΦΨΩ')
SCRIPTS = [
    ('キリル',     'Ѐ-ӿ'),
    ('ギリシャ',   'Ͱ-Ͽ'),
    ('ハングル',   'ᄀ-ᇿ㄰-㆏가-힯'),
    ('タイ',       '฀-๿'),
    ('アラビア',   '؀-ۿ'),
    ('ヘブライ',   '֐-׿'),
    ('デーヴァナーガリー', 'ऀ-ॿ'),
    ('アルメニア', '԰-֏'),
    ('ジョージア', 'Ⴀ-ჿ'),
]
SCRIPT_PAT = [(name, re.compile(f'[{rng}]')) for name, rng in SCRIPTS]

# 簡体字は漢字と同じブロックにあるため文字体系では拾えない。日本語で使わない字を直接見る
SIMPLIFIED = re.compile(
    '[讠-谶钅-镳'   # 讠 / 钅 の簡体字群（说话语请谁课…）。谷(8c37)以降は日本語なので除外
    '这们东车马门问题现实经济发际关时应该个为从长图书电视网'
    '无业乐买卖儿么样过进开给种员亲爱产权势习华丽风飞鸟鱼龙齿]')

def check_script(text):
    body = re.sub(r'```.*?```', '', text, flags=re.S)
    body = re.sub(r'`[^`\n]*`', '', body)               # インラインコードも除外
    for name, pat in SCRIPT_PAT:
        for m in pat.finditer(body):
            ch = m.group()
            if name == 'ギリシャ' and ch in GREEK_OK:
                continue
            s = max(0, m.start() - 12); e = min(len(body), m.end() + 12)
            return (name, ch, body[s:e].replace('\n', ' '))
    m = SIMPLIFIED.search(body)
    if m:
        s = max(0, m.start() - 12); e = min(len(body), m.end() + 12)
        return ('簡体字', m.group(), body[s:e].replace('\n', ' '))
    return None


# ── 参照物の実在確認 ────────────────────────────────────────
# 言語を読まずに検証できるもの。ラベルの有無に関係なく効く
PATHRE = re.compile(r'(?:/Users/[A-Za-z0-9._-]+|~)/[A-Za-z0-9._/\- ]{2,80}')
URLRE  = re.compile(r'https?://[^\s)\]<>"\'）」、。]+')
REFLOG = os.path.expanduser('~/.claude/hooks/refs.log')

def _norm_path(p):
    """末尾に語がくっついた形（`~/.claude 2.5GB`）を1語ずつ落として実在を探す"""
    p = p.strip().rstrip('.、。,')
    while p:
        if os.path.exists(os.path.expanduser(p)):
            return p, True
        if ' ' in p:
            p = p.rsplit(' ', 1)[0].rstrip('.、。,')
        else:
            # 「Application」→「Application Support」のように、実在する名前の前半で
            # 切れているだけなら見逃す
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
    """存在しないローカルパスを返す。URLは判定せず記録だけする（外部通信なし）"""
    body = re.sub(r'```.*?```', '', text, flags=re.S)   # フェンスは例示が多いので除外
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
    body = re.sub(r'```.*?```', '', text, flags=re.S)   # コードフェンス内は除外
    if not body.strip():
        return None
    if body.strip() in LABEL_ONLY:                     # 本文がラベル1語だけ
        return (0, len(body.strip()), f'[ラベルのみ] {body.strip()}', 1, 1)
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
    """stop_reason が付いていない assistant メッセージを探す。
    最後の1件は「まだ確定していない」可能性があるので除外する（誤検知防止）。
    推測を含まない唯一の軸：記録に『終わっていない』と書いてある。

    ただし CLI（entrypoint: cli）は stop_reason を書かないことがあるため、
    その場合はこの軸を使わない。デスクトップアプリでは 3,900 件中 1 件しか
    欠けなかったのに対し、CLI では通常の応答でも欠ける。誤検出になる。"""
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
    sr, t, ts = rows[-2]                    # 直前の1件（確定済み）だけを見る
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
                            print(f"  {jst(o.get('timestamp',''))} [ラベル] {r[0]:3d}%地点 / {r[1]:4d}字 / {r[3]:2d}行 / {r[4]}段落  {r[2]}")
                        s = check_script(txt)
                        if s:
                            n += 1
                            print(f"  {jst(o.get('timestamp',''))} [{s[0]}] 「{s[1]}」  …{s[2]}…")
                        mp = check_refs(txt, log_urls=False)
                        if mp:
                            n += 1
                            print(f"  {jst(o.get('timestamp',''))} [参照] 存在しないパス: {' / '.join(mp[:3])}")
        print(f"検出 {n} 件")
        return 0
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    tp = payload.get('transcript_path')
    # 呼び出されたこと自体を記録（動作確認用。うるさければ消してよい）
    try:
        with open(os.path.expanduser('~/.claude/hooks/invocations.log'), 'a', encoding='utf-8') as f:
            f.write(datetime.datetime.now(JST).strftime('%Y-%m-%d %H:%M:%S')
                    + '\t' + (os.path.basename(tp)[:8] if tp else 'no-path') + '\n')
    except Exception:
        pass
    if not tp or not os.path.exists(tp):
        return 0
    # Stop フックは、最後の返答が .jsonl に書かれる前に走ることがある（CLIで実測）。
    # 少し待って読み直し、増えていれば新しいほうを使う
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
        msgs.append(f"ラベル漏れ（{r[0]}%地点／{r[1]}字／{r[3]}行／{r[4]}段落）: {r[2][:60]}")
    s = check_script(t)
    if s:
        msgs.append(f"{s[0]}が混入「{s[1]}」 …{s[2][:40]}…")
    mp = check_refs(t)
    if mp:
        msgs.append(f"存在しないパス → {' / '.join(mp[:3])}")
    tr = find_truncated(tp)
    if tr:
        msgs.append(f"前の返答が未完了（stop_reason 無し・{tr[1]}字）{tr[0]} 末尾: …{tr[2]}")

    if msgs:
        stamp = datetime.datetime.now(JST).strftime('%Y-%m-%d %H:%M:%S')
        # ① 消えない記録
        try:
            with open(os.path.expanduser('~/.claude/hooks/detections.log'), 'a', encoding='utf-8') as f:
                for m in msgs:
                    f.write(f'{stamp}\t{os.path.basename(tp)[:8]}\t{m}\n')
        except Exception:
            pass
        # ② 音で知らせる（通知は許可が要るので使わない。音は不要）
        #    無効化: 環境変数 CLAUDE_DETECT_SOUND=0
        if os.environ.get('CLAUDE_DETECT_SOUND', '1') != '0':
            try:
                import subprocess, platform
                if platform.system() == 'Darwin':
                    snd = '/System/Library/Sounds/Funk.aiff'
                    if os.path.exists(snd):
                        subprocess.Popen(['afplay', snd],
                                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                else:
                    sys.stderr.write('\a')      # 他OSは端末ベル
            except Exception:
                pass
        # ③ スキーマに載っている systemMessage で試す（表示されなくてもエラーにならない）
        try:
            print(json.dumps({"systemMessage": "⚠ 検出: " + " / ".join(msgs)[:300]},
                             ensure_ascii=False))
        except Exception:
            pass
    return 0          # 常に 0。停止をブロックしない（exit 2 はループの恐れ）

sys.exit(main())
