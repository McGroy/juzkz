import glob, re, os, json, sys
from xml.etree import ElementTree as ET
from collections import defaultdict, OrderedDict

NS = {
    'b': 'http://www.omg.org/spec/BPMN/20100524/MODEL',
    'z': 'http://camunda.org/schema/zeebe/1.0',
}
BPMN_DIR = 'n8n_old_project_archive/bpmn'
OUT_DIR = './tmp_bpmn'

def tag(el): return el.tag.split('}')[-1]

def parse_body(body):
    """Extract structured info from FEEL body text"""
    info = {}
    if body is None: return info
    m = re.search(r'"newStatus"\s*:\s*"([^"]*)"', body)
    if m: info['newStatus'] = m.group(1)
    m = re.search(r'"isEditable"\s*:\s*(true|false)', body)
    if m: info['isEditable'] = m.group(1)
    m = re.search(r'"action"\s*:\s*"([^"]*)"', body)
    if m: info['action'] = m.group(1)
    m = re.search(r'"action_code"\s*:\s*"([^"]*)"', body)
    if m: info['action_code'] = m.group(1)
    m = re.search(r'"action_code"\s*:\s*([^,\n}]+)', body)
    if m and 'action_code' not in info: info['action_code_expr'] = m.group(1).strip()
    m = re.search(r'"doc_type"\s*:\s*("[^"]*"|[^,\n}]+)', body)
    if m: info['doc_type'] = m.group(1).strip()
    m = re.search(r'"newStatus"\s*:\s*([^"\s][^,\n}]*)', body)
    if m and 'newStatus' not in info: info['newStatus_expr'] = m.group(1).strip()
    # availableActions: find each {...} block containing "code"
    actions = []
    # crude: split on '"code"' occurrences and parse fields following
    for am in re.finditer(r'\{\s*"code"\s*:\s*"([^"]+)"(.*?)\}', body, re.S):
        code = am.group(1); rest = am.group(2)
        a = {'code': code}
        for fld in ('name_ru','name_kz','icon','color'):
            mm = re.search(r'"%s"\s*:\s*"([^"]*)"' % fld, rest)
            if mm: a[fld] = mm.group(1)
        for fld in ('requires_signature','requires_comment','requires_file'):
            mm = re.search(r'"%s"\s*:\s*(true|false)' % fld, rest)
            if mm: a[fld] = mm.group(1)
        mm = re.search(r'"allowed_roles"\s*:\s*\[([^\]]*)\]', rest, re.S)
        if mm:
            a['allowed_roles'] = re.findall(r'"([^"]+)"', mm.group(1))
        # extra keys
        extra = set(re.findall(r'"([a-zA-Z_]+)"\s*:', rest)) - {'name_ru','name_kz','icon','color','requires_signature','requires_comment','requires_file','allowed_roles'}
        if extra: a['extra_keys'] = sorted(extra)
        actions.append(a)
    if actions or re.search(r'"availableActions"', body or ''):
        info['availableActions'] = actions
    return info

results = []
for path in sorted(glob.glob(os.path.join(BPMN_DIR, '*.bpmn'))):
    tree = ET.parse(path); root = tree.getroot()
    msgs = {}
    for msg in root.findall('b:message', NS):
        sub = msg.find('.//z:subscription', NS)
        msgs[msg.get('id')] = {'name': msg.get('name'), 'corr': sub.get('correlationKey') if sub is not None else None}
    for proc in root.findall('b:process', NS):
        P = OrderedDict()
        P['file'] = os.path.basename(path)
        P['id'] = proc.get('id'); P['name'] = proc.get('name')
        P['messages'] = msgs
        elems = OrderedDict(); flows = []
        for el in proc.iter():
            t = tag(el)
            if t == 'sequenceFlow':
                cond = el.find('b:conditionExpression', NS)
                flows.append({'id': el.get('id'), 'src': el.get('sourceRef'), 'dst': el.get('targetRef'),
                              'name': el.get('name'), 'cond': (cond.text or '').strip() if cond is not None else None})
                continue
            if t in ('serviceTask','userTask','scriptTask','businessRuleTask','sendTask','receiveTask',
                     'exclusiveGateway','parallelGateway','eventBasedGateway','inclusiveGateway',
                     'startEvent','endEvent','intermediateCatchEvent','intermediateThrowEvent',
                     'boundaryEvent','callActivity','subProcess','task','manualTask'):
                E = OrderedDict(); E['type'] = t; E['id'] = el.get('id'); E['name'] = (el.get('name') or '').replace('\n',' ')
                if el.get('default'): E['default'] = el.get('default')
                if t == 'boundaryEvent': E['attachedTo'] = el.get('attachedToRef'); E['cancel'] = el.get('cancelActivity','true')
                if t == 'subProcess': E['triggeredByEvent'] = el.get('triggeredByEvent')
                # direct children only for definitions
                for ch in el:
                    ct = tag(ch)
                    if ct == 'messageEventDefinition': E['message'] = ch.get('messageRef')
                    elif ct == 'timerEventDefinition':
                        E['timer'] = ''.join((c.text or '') for c in ch).strip(); E['timerType'] = ','.join(tag(c) for c in ch)
                    elif ct == 'errorEventDefinition': E['error'] = ch.get('errorRef')
                    elif ct == 'terminateEventDefinition': E['terminate'] = True
                    elif ct == 'signalEventDefinition': E['signal'] = ch.get('signalRef')
                    elif ct == 'multiInstanceLoopCharacteristics': E['multiInstance'] = True
                ext = el.find('b:extensionElements', NS)
                if ext is not None:
                    td = ext.find('z:taskDefinition', NS)
                    if td is not None: E['jobType'] = td.get('type'); E['retries'] = td.get('retries')
                    ce = ext.find('z:calledElement', NS)
                    if ce is not None: E['calls'] = ce.get('processId'); E['propagateAll'] = ce.get('propagateAllChildVariables')
                    io = ext.find('z:ioMapping', NS)
                    if io is not None:
                        ins = OrderedDict(); outs = OrderedDict()
                        for m in io:
                            if tag(m) == 'input': ins[m.get('target')] = m.get('source')
                            else: outs[m.get('target')] = m.get('source')
                        if ins: E['inputs'] = ins
                        if outs: E['outputs'] = outs
                        body = ins.get('body')
                        if body:
                            E['url'] = ins.get('url')
                            E['body'] = body
                            E['bodyInfo'] = parse_body(body)
                    hd = ext.find('z:taskHeaders', NS)
                    if hd is not None:
                        E['headers'] = {h.get('key'): h.get('value') for h in hd}
                    # loop characteristics
                    lc = el.find('.//z:loopCharacteristics', NS)
                    if lc is not None: E['loop'] = dict(lc.attrib)
                elems[E['id']] = E
        P['elements'] = elems; P['flows'] = flows
        results.append(P)

json.dump(results, open(os.path.join(OUT_DIR, 'bpmn_parsed.json'), 'w'), ensure_ascii=False, indent=1)

# ---------- digest ----------
out = []
def w(s=''): out.append(s)
for P in results:
    w('#'*110)
    w(f"PROCESS {P['id']} | {P['name']} | file={P['file']}")
    for mid, m in P['messages'].items():
        w(f"  MESSAGE {mid} name={m['name']} corr={m['corr']}")
    E = P['elements']; F = P['flows']
    succ = defaultdict(list); pred = defaultdict(list)
    for f in F: succ[f['src']].append(f); pred[f['dst']].append(f)
    types = defaultdict(int)
    for e in E.values(): types[e['type']] += 1
    w('  ELEMENT COUNTS: ' + ', '.join(f"{k}={v}" for k,v in sorted(types.items())))
    for e in E.values():
        line = f"  [{e['type']}] {e['id']} :: {e['name']}"
        if 'message' in e: line += f" | msg={e['message']}"
        if 'timer' in e: line += f" | timer({e.get('timerType')})={e['timer']}"
        if 'error' in e: line += f" | error={e['error']}"
        if 'terminate' in e: line += " | TERMINATE"
        if 'calls' in e: line += f" | CALLS={e['calls']}"
        if 'attachedTo' in e: line += f" | attachedTo={e['attachedTo']} cancel={e['cancel']}"
        if 'default' in e: line += f" | default={e['default']}"
        if 'jobType' in e: line += f" | job={e['jobType']}"
        if 'multiInstance' in e or 'loop' in e: line += " | MULTI-INSTANCE " + json.dumps(e.get('loop',{}), ensure_ascii=False)
        w(line)
        if 'url' in e: w(f"      url={e['url']}")
        if 'bodyInfo' in e:
            bi = e['bodyInfo']
            short = {k:v for k,v in bi.items() if k != 'availableActions'}
            w(f"      bodyInfo={json.dumps(short, ensure_ascii=False)}")
            for a in bi.get('availableActions', []):
                w(f"         ACTION {a.get('code')} | ru={a.get('name_ru')} | kz={a.get('name_kz')} | icon={a.get('icon')} | color={a.get('color')} | sig={a.get('requires_signature')} | comment={a.get('requires_comment')} | roles={a.get('allowed_roles')}" + (f" | extra={a['extra_keys']}" if 'extra_keys' in a else ''))
            if 'availableActions' in bi and not bi['availableActions']:
                w("         ACTIONS: []")
        if 'body' in e and 'bodyInfo' in e and not e['bodyInfo'].get('newStatus') and not e['bodyInfo'].get('action'):
            w("      BODY(raw)=" + e['body'].replace('\n',' ')[:600])
        if 'inputs' in e and 'body' not in e['inputs']:
            w("      inputs=" + json.dumps(e['inputs'], ensure_ascii=False)[:400])
        if 'outputs' in e: w("      outputs=" + json.dumps(e['outputs'], ensure_ascii=False)[:300])
        if 'headers' in e:
            hh = {k:v for k,v in e['headers'].items() if k not in ('elementTemplateVersion','elementTemplateId','retryBackoff')}
            if hh: w("      headers=" + json.dumps(hh, ensure_ascii=False)[:300])
        for f in succ[e['id']]:
            dst = E.get(f['dst'], {})
            w(f"      -> {f['dst']} ({dst.get('type','?')} '{dst.get('name','')}')" + (f" [{f['name']}]" if f['name'] else '') + (f" COND: {f['cond']}" if f['cond'] else '') + (" (DEFAULT)" if e.get('default')==f['id'] else ''))
open(os.path.join(OUT_DIR, 'digest.txt'), 'w').write('\n'.join(out))
print('processes:', len(results)); print('digest lines:', len(out))
