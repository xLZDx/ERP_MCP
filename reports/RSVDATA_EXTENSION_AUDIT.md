# RSV Data extension audit — pending platform extraction

Assessment: 2026-10-06; ERP_MCP integration source baseline `d05c620`.

| Area | Evidence / finding |
|---|---|
| Artifact / hash | Official v1.3.0 ZIP verified; see RSVDATA_ARTIFACT_PROVENANCE.md. Built RSVData.cfe exists. |
| Platform | No 1cv8 executable found under standard Program Files roots; no matching uninstall entries; no registered ibases.v8i found under checked user/system 1CEStart locations. No suitable installer found in D:/Downloads. This is scoped discovery, not proof about every disk location. |
| Extension version | Release-labelled v1.3.0; internal extension version not extracted/verified. |
| Modules reviewed | Compiled extension modules NOT EXPORTED; RSVData_Сервер/Ядро/Справка and HTTP handlers await supported Designer extraction. |
| Tool call graph | Pinned Go bridge forwards messages to RSVData_Сервер.ОбработатьСообщение; ERP_MCP only invokes ping after inventory validation. Internal BSL call graph unknown. |
| Write path search | NOT RUN on BSL; documentation and a binary hash cannot substitute for a call-path audit. |
| Query safety | Release guide documents structured filters/fields/period/limit. Immutable company predicate, rights, nesting and side effects NOT VERIFIED. |
| execute_query safety | DENIED. Release guide accepts caller-supplied query text; strict read-only/company/runtime guarantees NOT VERIFIED. |
| Company scope | No A/B/C evidence: immutable validated predicate, proven single-company source, or company-restricted technical rights. Business dispatch remains CAPABILITY_UNSUPPORTED. |
| Privacy / reveal | Guide explicitly describes token-to-real-name de-anonymization. reveal and anonymization bypass remain DENIED. |
| Rights model | Upstream claims platform-user rights; negative company-rights tests NOT RUN. |
| Provenance mismatch | v1.3.0 tag is bb98ba4, approved source pin is 76fed8e; do not silently change approved pin or equate binaries to it. |
| Production allowlist | Current implemented boundary: ping only; help/config/describe/get_structure remain pending bounded metadata contract and audit. |
| Denylist | execute_query, reveal, arbitrary code/mutations, and all unverified business query routes. |
| Residual risks | Compiled behavior/rights/company predicate not audited; real COM disconnect/recovery untested. |
| Verdict | ARTIFACT_VERIFIED / EXTENSION_AUDIT_PENDING. No production data-route approval. |

## Next supported audit action

Use an installed suitable 1C Designer on a disposable synthetic base. Read that platform's actual
help before loading/exporting an extension; no unverified CLI flags are prescribed here.
Export XML/BSL outside Git, trace dispatcher-to-handler call paths, inspect mutation/dynamic-code/
network paths and run adversarial company/filter/privacy tests before enabling structured query.

The [official training-platform documentation](https://v8.1c.ru/podderzhka-i-obuchenie/uchebnye-versii/distributiv-1s-predpriyatie-8-3-versiya-dlya-obucheniya-programmirovaniyu/)
states that COM connections are unsupported. The [official accounting training edition](https://v8.1c.ru/podderzhka-i-obuchenie/uchebnye-versii/1s-bukhgalteriya-8-uchebnaya-versiya/)
requires questionnaire/license acceptance and also lacks external connections. It can assist UI
learning but cannot establish this bridge's COM parity. A suitable legally installed platform and
synthetic base are the precise remaining resource for this audit; independent engineering continues.
