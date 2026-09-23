import json, os, sys, re

WF_DIR = "n8n_old_project_archive/n8n_export/workflows"
OUT = "./out"
os.makedirs(OUT, exist_ok=True)

FILES = sys.argv[1:]

def dump(wf):
    lines = []
    lines.append(f"WORKFLOW: {wf.get('name')} (id={wf.get('id')}, active={wf.get('active')})")
    # connections summary
    conns = wf.get("connections", {})
    lines.append("--- CONNECTIONS ---")
    for src, outs in conns.items():
        for otype, branches in outs.items():
            for bi, br in enumerate(branches):
                tgts = [f"{c.get('node')}[{c.get('index',0)}]" for c in br]
                lines.append(f"  {src} --{otype}[{bi}]--> {', '.join(tgts)}")
    lines.append("--- NODES ---")
    for n in wf.get("nodes", []):
        t = n.get("type", "")
        name = n.get("name", "")
        p = n.get("parameters", {})
        disabled = " DISABLED" if n.get("disabled") else ""
        if "webhook" in t.lower() and "respond" not in t.lower():
            lines.append(f"=== WEBHOOK [{name}]{disabled} method={p.get('httpMethod')} path={p.get('path')} respond={p.get('responseMode')} opts={json.dumps(p.get('options',{}),ensure_ascii=False)}")
        elif "respondtowebhook" in t.lower():
            lines.append(f"=== RESPOND [{name}]{disabled} {json.dumps(p, ensure_ascii=False)[:600]}")
        elif "postgres" in t.lower():
            lines.append(f"=== POSTGRES [{name}]{disabled} op={p.get('operation')} table={p.get('table')} schema={p.get('schema')}")
            if p.get("query"):
                lines.append(p.get("query"))
            else:
                lines.append(json.dumps({k: v for k, v in p.items() if k != 'query'}, ensure_ascii=False)[:1500])
        elif t.endswith(".code"):
            lines.append(f"=== CODE [{name}]{disabled} mode={p.get('mode')}")
            lines.append(p.get("jsCode") or p.get("pythonCode") or "")
        elif "httprequest" in t.lower():
            lines.append(f"=== HTTP [{name}]{disabled} method={p.get('method')} url={p.get('url')}")
            body = p.get("jsonBody") or p.get("body") or p.get("bodyParameters")
            if body:
                lines.append("  body=" + (json.dumps(body, ensure_ascii=False) if not isinstance(body, str) else body)[:3000])
            if p.get("headerParameters"):
                lines.append("  headers=" + json.dumps(p.get("headerParameters"), ensure_ascii=False)[:800])
            if p.get("queryParameters"):
                lines.append("  query=" + json.dumps(p.get("queryParameters"), ensure_ascii=False)[:800])
            if p.get("authentication"):
                lines.append("  auth=" + str(p.get("authentication")) + " " + str(p.get("nodeCredentialType") or p.get("genericAuthType")))
        elif t.endswith(".set"):
            lines.append(f"=== SET [{name}]{disabled}")
            lines.append(json.dumps(p, ensure_ascii=False)[:3000])
        elif t.endswith(".if"):
            lines.append(f"=== IF [{name}]{disabled}")
            conds = p.get("conditions", {})
            lines.append(json.dumps(conds, ensure_ascii=False)[:1500])
        elif t.endswith(".switch"):
            lines.append(f"=== SWITCH [{name}]{disabled}")
            lines.append(json.dumps(p, ensure_ascii=False)[:4000])
        elif t.endswith(".executeWorkflow"):
            lines.append(f"=== EXEC_WF [{name}]{disabled} {json.dumps(p.get('workflowId'), ensure_ascii=False)} inputs={json.dumps((p.get('workflowInputs') or {}).get('value'), ensure_ascii=False)[:800]}")
        elif t.endswith(".executeWorkflowTrigger"):
            lines.append(f"=== EXEC_WF_TRIGGER [{name}]{disabled} {json.dumps(p, ensure_ascii=False)[:800]}")
        elif "zeebe" in t.lower() or "camunda" in t.lower():
            lines.append(f"=== ZEEBE [{name}]{disabled} type={t}")
            lines.append(json.dumps(p, ensure_ascii=False)[:3000])
        elif t.endswith(".merge") or t.endswith(".splitInBatches") or t.endswith(".noOp") or t.endswith(".splitOut") or t.endswith(".aggregate"):
            lines.append(f"=== {t.split('.')[-1].upper()} [{name}]{disabled} {json.dumps(p, ensure_ascii=False)[:300]}")
        elif "trigger" in t.lower():
            lines.append(f"=== TRIGGER [{name}]{disabled} type={t} {json.dumps(p, ensure_ascii=False)[:800]}")
        else:
            lines.append(f"=== OTHER [{name}]{disabled} type={t}")
            lines.append(json.dumps(p, ensure_ascii=False)[:2000])
    return "\n".join(lines)

for f in FILES:
    path = os.path.join(WF_DIR, f)
    with open(path, encoding="utf-8") as fh:
        wf = json.load(fh)
    txt = dump(wf)
    outp = os.path.join(OUT, f.replace(".json", ".txt"))
    with open(outp, "w", encoding="utf-8") as fh:
        fh.write(txt)
    print(f"{f}: nodes={len(wf.get('nodes',[]))} -> {outp} ({len(txt.splitlines())} lines)")
