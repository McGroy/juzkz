import { formFor, documentForms } from "saq-evga-test/src/modules/evga/forms/documentForms.ts";
import { docKinds, counterDocKinds } from "saq-evga-test/src/data/documentMatrix.ts";
const kinds = [...docKinds, ...counterDocKinds].map((d) => d.id);
const out: Record<string, unknown> = {};
for (const kind of kinds) {
  for (const auditType of ["Соответствие", "Фин. отчетность"]) {
    const form = formFor(kind, auditType);
    if (!form) { out[`${kind}|${auditType}`] = null; continue; }
    const sections = form.sections.map((s) => ({
      key: s.key, title: s.title, collection: !!s.collection, min: s.min ?? 0, attachments: !!s.attachments,
      total: s.total, tab: s.tab,
      fields: s.fields.map((f) => `${f.key}:${f.type ?? "text"}${f.required === false ? "?" : ""}${f.options ? `[${f.options.length}]` : ""}${f.when ? `{when ${f.when.key}}` : ""}${f.sourceKind ? `<${f.sourceKind}>` : ""}`),
    }));
    const nFields = form.sections.reduce((n, s) => n + s.fields.length, 0);
    const nRequired = form.sections.reduce((n, s) => n + s.fields.filter((f) => f.required !== false && f.type !== "boolean").length, 0);
    out[`${kind}|${auditType}`] = { group: !!form.group, tabs: form.tabs, sources: form.sources, nSections: form.sections.length, nCollections: form.sections.filter((s) => s.collection).length, nFields, nRequired, sections };
  }
}
console.log(JSON.stringify(out, null, 1));
