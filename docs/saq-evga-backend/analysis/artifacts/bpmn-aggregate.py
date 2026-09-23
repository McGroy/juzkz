import json, re
from collections import defaultdict, OrderedDict, Counter
D = json.load(open('./bpmn_parsed.json'))
out = []
def w(s=''): out.append(s)

# message reference check
w('## MESSAGE REFERENCE CHECK')
for P in D:
    refs = Counter(e.get('message') for e in P['elements'].values() if e.get('message'))
    for mid, m in P['messages'].items():
        w(f"{P['id']:45s} {mid:28s} name={m['name']:28s} corr={m['corr']}  refs={refs.get(mid,0)}")
w()
# per-process table
w('## PER-PROCESS TABLE')
w('| process id | name | statuses (workflow-update newStatus) | action codes (availableActions) | roles | timers | ext calls (zeebe action/action_code/doc_type; case-workflow-update newStatus; other urls) | counts |')
allactions = defaultdict(lambda: {'ru': Counter(), 'kz': Counter(), 'icon': Counter(), 'color': Counter(), 'sig': Counter(), 'comment': Counter(), 'roles': Counter(), 'procs': set(), 'states': Counter()})
caseactions = defaultdict(lambda: {'ru': Counter(), 'kz': Counter(), 'icon': Counter(), 'roles': Counter(), 'procs': set(), 'states': Counter()})
roles = defaultdict(lambda: Counter())
status_ctr = Counter(); status_procs = defaultdict(set)
zeebe_calls = Counter()
urls = Counter()
for P in D:
    statuses = []; acts = OrderedDict(); rset = set(); timers = []; ext = []
    for e in P['elements'].values():
        if 'url' in e: urls[re.sub(r'.*?/webhook/', '/webhook/', e['url'])] += 1
        bi = e.get('bodyInfo', {})
        url = e.get('url','')
        if 'workflow-update' in url and 'case-workflow-update' not in url:
            st = bi.get('newStatus')
            if st and st not in statuses: statuses.append(st)
            if st: status_ctr[st] += 1; status_procs[st].add(P['id'])
            for a in bi.get('availableActions', []):
                c = a['code']; acts.setdefault(c, set()).update(a.get('allowed_roles', []))
                rset.update(a.get('allowed_roles', []))
                A = allactions[c]; A['ru'][a.get('name_ru')] += 1; A['kz'][a.get('name_kz')] += 1; A['icon'][a.get('icon')] += 1; A['color'][a.get('color')] += 1
                A['sig'][a.get('requires_signature')] += 1; A['comment'][a.get('requires_comment')] += 1
                for r in a.get('allowed_roles', []): A['roles'][r] += 1; roles[r][c] += 1
                A['procs'].add(P['id']); A['states'][st] += 1
        elif 'case-workflow-update' in url:
            st = bi.get('newStatus')
            ext.append(f"case-workflow-update newStatus={st}" if st else "case-workflow-update(actions)")
            for a in bi.get('availableActions', []):
                c = a['code']; acts.setdefault('CASE:'+c, set()).update(a.get('allowed_roles', []))
                rset.update(a.get('allowed_roles', []))
                A = caseactions[c]; A['ru'][a.get('name_ru')] += 1; A['kz'][a.get('name_kz')] += 1; A['icon'][a.get('icon')] += 1
                for r in a.get('allowed_roles', []): A['roles'][r] += 1; roles[r]['CASE:'+c] += 1
                A['procs'].add(P['id']); A['states'][st] += 1
        elif '/webhook/evga/zeebe' in url:
            s = f"zeebe:{bi.get('action')}/{bi.get('action_code')}" + (f"/{bi.get('doc_type')}" if bi.get('doc_type') else '')
            ext.append(s); zeebe_calls[s] += 1
        elif url:
            ext.append(re.sub(r'.*?/webhook/', '', url) + ('' if not bi.get('action') else f"({bi.get('action')})"))
        if 'timer' in e: timers.append(f"{e['id']}: {e['timer']}")
        if 'calls' in e: ext.append(f"CALL {e['calls']}")
    cnt = Counter(e['type'] for e in P['elements'].values())
    w(f"| {P['id']} | {P['name']} | {', '.join(statuses)} | {', '.join(k+'['+'/'.join(sorted(v))+']' for k,v in acts.items())} | {', '.join(sorted(rset))} | {'; '.join(timers)} | {'; '.join(OrderedDict.fromkeys(ext))} | st={cnt.get('serviceTask',0)} gw={cnt.get('exclusiveGateway',0)+cnt.get('eventBasedGateway',0)+cnt.get('parallelGateway',0)} wait={cnt.get('intermediateCatchEvent',0)} end={cnt.get('endEvent',0)} |")
w()
w('## STATUS CATALOG (workflow-update newStatus)')
for st, n in status_ctr.most_common():
    w(f"{st:35s} n={n:3d} procs={len(status_procs[st])}: {', '.join(sorted(status_procs[st]))[:300]}")
w()
w('## DOC ACTION CATALOG')
for c, A in sorted(allactions.items()):
    w(f"{c:32s} | ru={A['ru'].most_common(3)} | kz={A['kz'].most_common(2)} | icon={A['icon'].most_common(2)} | color={A['color'].most_common(2)} | sig={dict(A['sig'])} | comment={dict(A['comment'])} | roles={dict(A['roles'])} | from_states={dict(A['states'])} | nprocs={len(A['procs'])}")
w()
w('## CASE ACTION CATALOG (case-workflow-update availableActions)')
for c, A in sorted(caseactions.items()):
    w(f"{c:32s} | ru={A['ru'].most_common(2)} | kz={A['kz'].most_common(1)} | icon={A['icon'].most_common(1)} | roles={dict(A['roles'])} | nprocs={len(A['procs'])} procs={sorted(A['procs'])}")
w()
w('## ROLE CATALOG')
for r, C in sorted(roles.items()):
    w(f"{r:28s} | {dict(C.most_common())}")
w()
w('## ZEEBE WEBHOOK CALLS')
for s, n in zeebe_calls.most_common(): w(f"{n:3d} {s}")
w()
w('## URL CATALOG')
for u, n in urls.most_common(): w(f"{n:4d} {u}")
w()
# gateway conditions that are not actionCode checks
w('## NON-ACTIONCODE CONDITIONS')
for P in D:
    for f in P['flows']:
        if f['cond'] and 'actionCode' not in f['cond']:
            w(f"{P['id']:40s} {f['src']} -> {f['dst']}: {f['cond']}")
w()
# all actionCode values expected in catch-event conditions (incl. those not in availableActions)
w('## ACTIONCODE VALUES IN CONDITIONS')
condcodes = defaultdict(set)
for P in D:
    for f in P['flows']:
        if f['cond']:
            for m in re.findall(r'actionCode\s*=\s*"([^"]+)"', f['cond']): condcodes[m].add(P['id'])
for c, ps in sorted(condcodes.items()):
    w(f"{c:32s} in_availableActions={'Y' if c in allactions or c in caseactions else 'N'} procs={len(ps)}: {', '.join(sorted(ps))[:250]}")
open('./aggregate.txt','w').write('\n'.join(out))
print(len(out))
