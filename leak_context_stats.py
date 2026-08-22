import json,glob,os,re,csv,collections,datetime,sys
root=os.path.expanduser('~/.claude/projects')
PAT = re.compile(r'(?m)^[ \t]*(?:user(?![A-Za-z_.\-])[ \t]*\S|système)')
LABEL_ONLY = {'思考', 'système', 'システム', 'thinking', 'Thinking', 'system'}
PRIME = re.compile(r'捏造|fabricat|ラベル漏れ|role.?leak|偽の?ユーザ|偽user|fake.?user', re.I)
ANYLABEL = re.compile(r'(?m)^[ \t]*user(?![A-Za-z_.\-])')
def check(text):
    body = re.sub(r'```.*?```', '', text, flags=re.S)
    if not body.strip(): return None
    if body.strip() in LABEL_ONLY: return (0,len(body.strip()))
    m=PAT.search(body)
    if not m: return None
    return (m.start()/len(body), len(body)-m.start())
def ts(o):
    t=o.get('timestamp')
    if not t: return None
    return datetime.datetime.fromisoformat(t.replace('Z','+00:00')).timestamp()
rows=[]
for f in sorted(glob.glob(root+'/*/*.jsonl')):
    sess=os.path.basename(f)[:8]
    last_human_t=None; depth=0; prev_kind='start'; att_h=set(); att_a=set()
    prior_leaks=0; prior_prime=0; prior_anylabel=0; sitting_start=None; last_t=None
    last_compact_i=None; i=0; prev_stop=None; n_human=0
    with open(f,encoding='utf-8',errors='replace') as fh:
        for line in fh:
            try:o=json.loads(line)
            except: continue
            i+=1; t=o.get('type'); T=ts(o)
            if T is not None:
                if last_t is None or T-last_t>3600: sitting_start=T
                last_t=T
            if t=='attachment':
                k=o.get('attachment',{}).get('type'); att_h.add(k); att_a.add(k); prev_kind='att:'+str(k); continue
            if t=='system':
                st=o.get('subtype')
                if st=='compact_boundary': last_compact_i=i
                prev_kind='sys:'+str(st); continue
            if t=='user':
                m=o.get('message',{}); c=m.get('content')
                if o.get('isCompactSummary'):
                    last_compact_i=i; prev_kind='user_compact'; continue
                kinds=set()
                if isinstance(c,list): kinds={b.get('type') for b in c if isinstance(b,dict)}
                else: kinds={'str'}
                txt = c if isinstance(c,str) else ''.join(b.get('text','') for b in c if isinstance(b,dict) and b.get('type')=='text')
                if 'tool_result' in kinds:
                    prev_kind='user_tool_result'
                elif o.get('isMeta'):
                    prev_kind='user_meta'
                else:
                    prev_kind='user_human'; last_human_t=T; depth=0; att_h=set(); n_human+=1
                    if PRIME.search(txt): prior_prime+=1
                    if ANYLABEL.search(txt): prior_anylabel+=1
                continue
            if t!='assistant':
                prev_kind=t; continue
            m=o.get('message',{}); c=m.get('content') or []
            texts=[b.get('text','') for b in c if isinstance(b,dict) and b.get('type')=='text' and b.get('text','').strip()]
            has_tool=any(isinstance(b,dict) and b.get('type')=='tool_use' for b in c)
            if not texts:
                prev_kind='assistant_notext'; depth+=1; att_a=set(); continue
            text='\n'.join(texts)
            u=m.get('usage') or {}
            ctx=(u.get('cache_read_input_tokens') or 0)+(u.get('cache_creation_input_tokens') or 0)+(u.get('input_tokens') or 0)
            r=check(text)
            rows.append(dict(sess=sess,i=i,ts=o.get('timestamp'),uuid=o.get('uuid'),msg_id=m.get('id'),model=m.get('model'),
                stop=m.get('stop_reason'),prev_stop=prev_stop,ctx=ctx,out=u.get('output_tokens'),leak=1 if r else 0,
                leak_pos=round(r[0],2) if r else '',leak_len=r[1] if r else '',tlen=len(text),
                since_human=round(T-last_human_t) if (T and last_human_t) else '',depth=depth,prev_kind=prev_kind,
                att_h='+'.join(sorted(x for x in att_h if x)),att_a='+'.join(sorted(x for x in att_a if x)),
                prior_leaks=prior_leaks,prior_prime=prior_prime,prior_anylabel=prior_anylabel,
                sitting=round(T-sitting_start) if (T and sitting_start) else '',
                since_compact=(i-last_compact_i) if last_compact_i else '',n_human=n_human,version=o.get('version'),
                has_tool=int(has_tool),head=text[:80].replace('\n',' ')))
            if r: prior_leaks+=1
            if PRIME.search(text): prior_prime+=1
            if ANYLABEL.search(text): prior_anylabel+=1
            prev_stop=m.get('stop_reason'); prev_kind='assistant_text'; depth+=1; att_a=set()
out='feat.csv'
with open(out,'w',newline='') as fh:
    w=csv.DictWriter(fh,fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
print('rows',len(rows),'leaks',sum(r['leak'] for r in rows))
def rate(key,fn,order=None):
    g=collections.defaultdict(lambda:[0,0])
    for r in rows:
        k=fn(r); g[k][0]+=r['leak']; g[k][1]+=1
    print('\n##',key)
    keys=order or sorted(g,key=lambda k:(str(type(k)),k))
    for k in keys:
        if k in g:
            l,n=g[k]; print(f'  {str(k):28s} {l:3d}/{n:5d}  {100*l/n:5.2f}%')
rate('session',lambda r:r['sess'])
def b(x,edges):
    if x=='' : return 'NA'
    for e in edges:
        if x<e: return f'<{e}'
    return f'>={edges[-1]}'
rate('ctx tokens',lambda r:b(r['ctx'],[50000,100000,150000,200000,300000,400000,600000]),['<50000','<100000','<150000','<200000','<300000','<400000','<600000','>=600000'])
rate('depth in agentic turn',lambda r:b(r['depth'],[1,2,4,8,16]))
rate('prev_kind',lambda r:r['prev_kind'])
rate('since_human sec',lambda r:b(r['since_human'],[30,60,120,300,600,1800]))
rate('prior_leaks in session',lambda r:b(r['prior_leaks'],[1,2,4,8]))
rate('prior_prime msgs',lambda r:b(r['prior_prime'],[1,5,20,50]))
rate('prior_anylabel',lambda r:b(r['prior_anylabel'],[1,3,10,30]))
rate('sitting sec',lambda r:b(r['sitting'],[600,1800,3600,7200,14400]))
rate('since_compact records',lambda r:b(r['since_compact'],[20,50,100,300]))
rate('prev_stop',lambda r:r['prev_stop'])
rate('has_tool same record',lambda r:r['has_tool'])
rate('att_h contains task_reminder',lambda r:'task_reminder' in r['att_h'])
rate('att_h contains queued_command',lambda r:'queued_command' in r['att_h'])
rate('att_h contains date_change',lambda r:'date_change' in r['att_h'])
rate('att_h contains hook_system_message',lambda r:'hook_system_message' in r['att_h'])
rate('att_a (since prev assistant)',lambda r:r['att_a'] or '-')
rate('model',lambda r:r['model'])
rate('date',lambda r:(r['ts'] or '')[:10])
