#!/usr/bin/env python3
"""Rich dump of n8n workflow nodes: webhook, SQL, jsCode (JWT guard collapsed),
HTTP request details, credentials, Set/Switch/If params, executeWorkflow, triggers."""
import json, os, re, sys, glob

WF_DIR = "n8n_old_project_archive/n8n_export/workflows"
OUT_DIR = "./out"
os.makedirs(OUT_DIR, exist_ok=True)

GUARD_RE = re.compile(r"// ==== PORTAL JWT GUARD v1 ====.*?// ==== END PORTAL JWT GUARD ====", re.S)
CHECK_RE = re.compile(r"\{\s*const __req = \$input\.first\(\)\.json \|\| \{\};.*?// ==== END PORTAL JWT CHECK ====", re.S)
RABBIT_RE = re.compile(r"function clean\(value\) \{.*?return \{\s*logLine: JSON\.stringify\(payload\),.*?\};", re.S)


def collapse(code: str) -> str:
    if not code:
        return code
    code, n1 = GUARD_RE.subn("/* [PORTAL JWT GUARD v1 boilerplate collapsed: verifies RS256 JWT from Keycloak via JWKS; $vars KEYCLOAK_REALM(default 'efc'), KEYCLOAK_ADMIN_BASE_URL, KEYCLOAK_JWT_ISSUER, KEYCLOAK_JWT_AUDIENCE(default 'account,web-ui-service'), KEYCLOAK_JWT_CLOCK_TOLERANCE_SEC(60), KEYCLOAK_JWKS_URL, KEYCLOAK_JWT_JWKS, KEYCLOAK_JWKS_TLS_INSECURE] */", code)
    code, n2 = CHECK_RE.subn("/* [PORTAL JWT CHECK collapsed: if Authorization header present -> __portalJwtVerify, throw 401/503 on failure] */", code)
    code, n3 = RABBIT_RE.subn("/* [Rabbit MQ logger body collapsed: builds logLine (text 'dd.LL.yyyy / HH:mm:ss | service | user (efc_user_id, idp_user_id) | ip | start | end | OK/FAILED | action [entity#id]: description' or JSON schemaVersion 1 {eventTime,eventType,outcome,service,action,subject{username,efcUserId,idpUserId},object{type,id,name,resource},source{ip},operation{startTime,endTime},description}); TZ Asia/Almaty] */", code)
    return code


def dump_wf(path):
    with open(path, encoding="utf-8") as f:
        wf = json.load(f)
    lines = []
    lines.append("=" * 100)
    lines.append(f"WORKFLOW: {wf.get('name')}  (id={wf.get('id')}, active={wf.get('active')}) file={os.path.basename(path)}")
    settings = wf.get("settings") or {}
    if settings:
        lines.append(f"settings: {json.dumps(settings, ensure_ascii=False)[:300]}")
    tags = wf.get("tags")
    if tags:
        lines.append(f"tags: {json.dumps(tags, ensure_ascii=False)[:300]}")
    lines.append("=" * 100)
    # connections summary
    conns = wf.get("connections") or {}
    edges = []
    for src, outs in conns.items():
        for otype, outlist in outs.items():
            for oi, targets in enumerate(outlist or []):
                for t in targets or []:
                    edges.append(f"{src} -[{otype}{oi}]-> {t.get('node')}")
    if edges:
        lines.append("--- CONNECTIONS ---")
        lines.extend("  " + e for e in edges)
    for n in wf.get("nodes", []):
        ntype = n.get("type", "")
        name = n.get("name", "")
        params = n.get("parameters", {}) or {}
        creds = n.get("credentials")
        low = ntype.lower()
        disabled = " DISABLED" if n.get("disabled") else ""
        credstr = f" creds={json.dumps({k: v.get('name') for k, v in creds.items()}, ensure_ascii=False)}" if creds else ""
        if "respondtowebhook" in low:
            lines.append(f"--- RESPOND [{name}]{disabled} ---")
            lines.append(json.dumps(params, ensure_ascii=False)[:600])
        elif low.endswith("webhook"):
            lines.append(f"--- WEBHOOK [{name}]{disabled} method={params.get('httpMethod','GET')} path={params.get('path')} auth={params.get('authentication')} opts={json.dumps(params.get('options',{}), ensure_ascii=False)[:200]}{credstr} ---")
        elif "postgres" in low:
            lines.append(f"--- POSTGRES [{name}]{disabled} op={params.get('operation')} schema={json.dumps(params.get('schema'),ensure_ascii=False)} table={json.dumps(params.get('table'),ensure_ascii=False)}{credstr} ---")
            q = params.get("query", "")
            if q:
                lines.append(q)
            other = {k: v for k, v in params.items() if k not in ("query",)}
            if other and not q:
                lines.append(json.dumps(other, ensure_ascii=False)[:1500])
            elif params.get("options"):
                lines.append("options: " + json.dumps(params.get("options"), ensure_ascii=False)[:500])
        elif low.endswith(".code"):
            code = params.get("jsCode", "") or params.get("pythonCode", "")
            if "Инлайн саб-воркфлоу «Rabbit MQ logger»" in code and code.lstrip().startswith("//"):
                m = re.search(r"const input = \{(.*?)\n\};", code, re.S)
                fields = {}
                if m:
                    for k in ("serviceName","action","entityType","entityId","description","eventType","objectId","objectName","resource","success","logFormat"):
                        mm = re.search(r'"%s":\s*(.*?),?\n' % k, m.group(1))
                        if mm: fields[k] = mm.group(1).strip()[:160]
                lines.append(f"--- CODE [{name}]{disabled} (RabbitMQ logger inline) fields={json.dumps(fields, ensure_ascii=False)} ---")
            else:
                lines.append(f"--- CODE [{name}]{disabled} mode={params.get('mode')} ---")
                lines.append(collapse(code))
        elif "httprequest" in low:
            lines.append(f"--- HTTP REQUEST [{name}]{disabled} url={params.get('url')} method={params.get('method','GET')} auth={params.get('authentication')} genericAuth={params.get('genericAuthType')} nodeCred={params.get('nodeCredentialType')}{credstr} ---")
            for k in ("sendQuery", "queryParameters", "sendHeaders", "headerParameters", "sendBody", "contentType", "specifyBody", "bodyParameters", "jsonBody", "body", "options"):
                if k in params:
                    lines.append(f"  {k}: {json.dumps(params[k], ensure_ascii=False)[:2500]}")
        elif "executeworkflow" in low:
            lines.append(f"--- EXEC SUBWORKFLOW [{name}]{disabled} ---")
            lines.append(json.dumps(params, ensure_ascii=False)[:1200])
        elif low.endswith(".set"):
            lines.append(f"--- SET [{name}]{disabled} ---")
            lines.append(json.dumps(params, ensure_ascii=False)[:3000])
        elif low.endswith(".if") or low.endswith(".switch") or low.endswith(".filter"):
            lines.append(f"--- BRANCH [{name}]{disabled} type={ntype} ---")
            lines.append(json.dumps(params, ensure_ascii=False)[:2500])
        elif "trigger" in low or "cron" in low or "schedule" in low:
            lines.append(f"--- TRIGGER [{name}]{disabled} type={ntype} ---")
            lines.append(json.dumps(params, ensure_ascii=False)[:800])
        elif low.endswith(".jwt"):
            lines.append(f"--- JWT NODE [{name}]{disabled}{credstr} ---")
            lines.append(json.dumps(params, ensure_ascii=False)[:800])
        elif "rabbitmq" in low or "amqp" in low:
            lines.append(f"--- RABBITMQ [{name}]{disabled}{credstr} ---")
            lines.append(json.dumps(params, ensure_ascii=False)[:800])
        else:
            lines.append(f"--- OTHER [{name}]{disabled} type={ntype}{credstr} ---")
            if params:
                lines.append(json.dumps(params, ensure_ascii=False)[:1500])
    # pinData / staticData
    if wf.get("staticData"):
        lines.append("staticData: " + json.dumps(wf["staticData"], ensure_ascii=False)[:500])
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    patterns = sys.argv[1:]
    files = []
    for p in patterns:
        files.extend(sorted(glob.glob(os.path.join(WF_DIR, p))))
    outname = os.environ.get("OUTNAME", "dump.txt")
    with open(os.path.join(OUT_DIR, outname), "w", encoding="utf-8") as f:
        for fp in files:
            f.write(dump_wf(fp))
    print("wrote", os.path.join(OUT_DIR, outname), len(files), "files")
