# Specification-only Gherkin: steps deliberately NOT implemented, product results NOT_RUN.
Feature: Phase 2 acceptance specifications

  @not_implemented @R2TC001
  Scenario: R2-TC-001 R1 unchanged
    Given a scoped test environment for R2-US-001
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate R1 unchanged

  @not_implemented @R2TC002
  Scenario: R2-TC-002 R1 defects cannot be hidden in the future backlog
    Given a scoped test environment for R2-US-001
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate R1 defects cannot be hidden in the future backlog

  @not_implemented @R2TC003
  Scenario: R2-TC-003 moving HEAD is not reported as deployment evidence
    Given a scoped test environment for R2-US-001
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate moving HEAD is not reported as deployment evidence

  @not_implemented @R2TC004
  Scenario: R2-TC-004 pin file path/SHA/license
    Given a scoped test environment for R2-US-002
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate pin file path/SHA/license

  @not_implemented @R2TC005
  Scenario: R2-TC-005 an empty placeholder is not ready
    Given a scoped test environment for R2-US-002
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate an empty placeholder is not ready

  @not_implemented @R2TC006
  Scenario: R2-TC-006 donor write APIs are not exposed
    Given a scoped test environment for R2-US-002
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate donor write APIs are not exposed

  @not_implemented @R2TC007
  Scenario: R2-TC-007 typed scope and provenance
    Given a scoped test environment for R2-US-003
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate typed scope and provenance

  @not_implemented @R2TC008
  Scenario: R2-TC-008 arbitrary URL/SQL/command denied
    Given a scoped test environment for R2-US-003
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate arbitrary URL/SQL/command denied

  @not_implemented @R2TC009
  Scenario: R2-TC-009 unsupported change feed maps to SNAPSHOT_ONLY
    Given a scoped test environment for R2-US-003
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate unsupported change feed maps to SNAPSHOT_ONLY

  @not_implemented @R2TC010
  Scenario: R2-TC-010 permitted company read
    Given a scoped test environment for R2-US-004
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate permitted company read

  @not_implemented @R2TC011
  Scenario: R2-TC-011 cross-tenant FK/API denied
    Given a scoped test environment for R2-US-004
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate cross-tenant FK/API denied

  @not_implemented @R2TC012
  Scenario: R2-TC-012 company-only grant does not authorize global metadata
    Given a scoped test environment for R2-US-004
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate company-only grant does not authorize global metadata

  @not_implemented @R2TC013
  Scenario: R2-TC-013 revoke blocks jobs/bumps epoch
    Given a scoped test environment for R2-US-005
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate revoke blocks jobs/bumps epoch

  @not_implemented @R2TC014
  Scenario: R2-TC-014 revoke before disclosure denies result
    Given a scoped test environment for R2-US-005
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate revoke before disclosure denies result

  @not_implemented @R2TC015
  Scenario: R2-TC-015 reconnect never restores revoked grants
    Given a scoped test environment for R2-US-005
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate reconnect never restores revoked grants

  @not_implemented @R2TC016
  Scenario: R2-TC-016 no secrets in logs/arguments
    Given a scoped test environment for R2-US-006
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate no secrets in logs/arguments

  @not_implemented @R2TC017
  Scenario: R2-TC-017 missing credential pair fails preflight without gateway shutdown
    Given a scoped test environment for R2-US-006
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate missing credential pair fails preflight without gateway shutdown

  @not_implemented @R2TC018
  Scenario: R2-TC-018 rotation uses the new version
    Given a scoped test environment for R2-US-006
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate rotation uses the new version

  @not_implemented @R2TC019
  Scenario: R2-TC-019 complete coverage/digests
    Given a scoped test environment for R2-US-007
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate complete coverage/digests

  @not_implemented @R2TC020
  Scenario: R2-TC-020 direct SQL forbidden
    Given a scoped test environment for R2-US-007
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate direct SQL forbidden

  @not_implemented @R2TC021
  Scenario: R2-TC-021 changing source yields partial/consistency warning
    Given a scoped test environment for R2-US-007
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate changing source yields partial/consistency warning

  @not_implemented @R2TC022
  Scenario: R2-TC-022 whitespace-only structural hash unchanged
    Given a scoped test environment for R2-US-008
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate whitespace-only structural hash unchanged

  @not_implemented @R2TC023
  Scenario: R2-TC-023 type/scale change causes diff
    Given a scoped test environment for R2-US-008
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate type/scale change causes diff

  @not_implemented @R2TC024
  Scenario: R2-TC-024 namespaces do not collide
    Given a scoped test environment for R2-US-008
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate namespaces do not collide

  @not_implemented @R2TC025
  Scenario: R2-TC-025 timeout does not create a new schema
    Given a scoped test environment for R2-US-009
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate timeout does not create a new schema

  @not_implemented @R2TC026
  Scenario: R2-TC-026 partial scan cannot delete objects
    Given a scoped test environment for R2-US-009
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate partial scan cannot delete objects

  @not_implemented @R2TC027
  Scenario: R2-TC-027 recovery without false version or automatic trust
    Given a scoped test environment for R2-US-009
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate recovery without false version or automatic trust

  @not_implemented @R2TC028
  Scenario: R2-TC-028 append/projection order
    Given a scoped test environment for R2-US-010
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate append/projection order

  @not_implemented @R2TC029
  Scenario: R2-TC-029 SQL roles deny UPDATE/DELETE
    Given a scoped test environment for R2-US-010
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate SQL roles deny UPDATE/DELETE

  @not_implemented @R2TC030
  Scenario: R2-TC-030 identical replay
    Given a scoped test environment for R2-US-010
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate identical replay

  @not_implemented @R2TC031
  Scenario: R2-TC-031 correct two-time views
    Given a scoped test environment for R2-US-011
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate correct two-time views

  @not_implemented @R2TC032
  Scenario: R2-TC-032 unknown effective time is not replaced by poll timestamp
    Given a scoped test environment for R2-US-011
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate unknown effective time is not replaced by poll timestamp

  @not_implemented @R2TC033
  Scenario: R2-TC-033 late supersession preserves earlier knowledge
    Given a scoped test environment for R2-US-011
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate late supersession preserves earlier knowledge

  @not_implemented @R2TC034
  Scenario: R2-TC-034 SNAPSHOT_ONLY interval
    Given a scoped test environment for R2-US-012
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate SNAPSHOT_ONLY interval

  @not_implemented @R2TC035
  Scenario: R2-TC-035 A–B–A changes are not invented
    Given a scoped test environment for R2-US-012
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate A–B–A changes are not invented

  @not_implemented @R2TC036
  Scenario: R2-TC-036 lost cursor causes controlled resnapshot and gap
    Given a scoped test environment for R2-US-012
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate lost cursor causes controlled resnapshot and gap

  @not_implemented @R2TC037
  Scenario: R2-TC-037 scoped candidate edges
    Given a scoped test environment for R2-US-013
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate scoped candidate edges

  @not_implemented @R2TC038
  Scenario: R2-TC-038 LLM cannot validate
    Given a scoped test environment for R2-US-013
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate LLM cannot validate

  @not_implemented @R2TC039
  Scenario: R2-TC-039 versioned semantics preserve old links
    Given a scoped test environment for R2-US-013
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate versioned semantics preserve old links

  @not_implemented @R2TC040
  Scenario: R2-TC-040 exact scoped reference match
    Given a scoped test environment for R2-US-014
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate exact scoped reference match

  @not_implemented @R2TC041
  Scenario: R2-TC-041 same name across companies never merges
    Given a scoped test environment for R2-US-014
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate same name across companies never merges

  @not_implemented @R2TC042
  Scenario: R2-TC-042 ambiguity requires human resolution
    Given a scoped test environment for R2-US-014
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate ambiguity requires human resolution

  @not_implemented @R2TC043
  Scenario: R2-TC-043 affected tool blocked
    Given a scoped test environment for R2-US-015
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate affected tool blocked

  @not_implemented @R2TC044
  Scenario: R2-TC-044 unknown graph denied conservatively
    Given a scoped test environment for R2-US-015
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate unknown graph denied conservatively

  @not_implemented @R2TC045
  Scenario: R2-TC-045 remove/recreate is not a rename
    Given a scoped test environment for R2-US-015
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate remove/recreate is not a rename

  @not_implemented @R2TC046
  Scenario: R2-TC-046 evidence plus expected-head commit
    Given a scoped test environment for R2-US-016
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate evidence plus expected-head commit

  @not_implemented @R2TC047
  Scenario: R2-TC-047 stale reviewer yields conflict (409)
    Given a scoped test environment for R2-US-016
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate stale reviewer yields conflict (409)

  @not_implemented @R2TC048
  Scenario: R2-TC-048 incompatible rollback denied
    Given a scoped test environment for R2-US-016
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate incompatible rollback denied

  @not_implemented @R2TC049
  Scenario: R2-TC-049 exactly one lease/fence
    Given a scoped test environment for R2-US-017
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate exactly one lease/fence

  @not_implemented @R2TC050
  Scenario: R2-TC-050 stale worker cannot commit
    Given a scoped test environment for R2-US-017
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate stale worker cannot commit

  @not_implemented @R2TC051
  Scenario: R2-TC-051 crash reclaim without duplicates
    Given a scoped test environment for R2-US-017
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate crash reclaim without duplicates

  @not_implemented @R2TC052
  Scenario: R2-TC-052 atomic page/cursor
    Given a scoped test environment for R2-US-018
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate atomic page/cursor

  @not_implemented @R2TC053
  Scenario: R2-TC-053 crash replay without loss
    Given a scoped test environment for R2-US-018
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate crash replay without loss

  @not_implemented @R2TC054
  Scenario: R2-TC-054 same ID with different digest is conflict
    Given a scoped test environment for R2-US-018
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate same ID with different digest is conflict

  @not_implemented @R2TC055
  Scenario: R2-TC-055 budget shared across source aliases
    Given a scoped test environment for R2-US-019
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate budget shared across source aliases

  @not_implemented @R2TC056
  Scenario: R2-TC-056 bounded overload
    Given a scoped test environment for R2-US-019
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate bounded overload

  @not_implemented @R2TC057
  Scenario: R2-TC-057 interactive/background fairness
    Given a scoped test environment for R2-US-019
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate interactive/background fairness

  @not_implemented @R2TC058
  Scenario: R2-TC-058 pause prevents new jobs
    Given a scoped test environment for R2-US-020
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate pause prevents new jobs

  @not_implemented @R2TC059
  Scenario: R2-TC-059 poisoned source isolated
    Given a scoped test environment for R2-US-020
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate poisoned source isolated

  @not_implemented @R2TC060
  Scenario: R2-TC-060 resume rechecks scope/cursor
    Given a scoped test environment for R2-US-020
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate resume rechecks scope/cursor

  @not_implemented @R2TC061
  Scenario: R2-TC-061 original artifact/manifest is UNATTESTED
    Given a scoped test environment for R2-US-021
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate original artifact/manifest is UNATTESTED

  @not_implemented @R2TC062
  Scenario: R2-TC-062 partial screenshot is incomplete
    Given a scoped test environment for R2-US-021
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate partial screenshot is incomplete

  @not_implemented @R2TC063
  Scenario: R2-TC-063 edited XLSX digest rejected
    Given a scoped test environment for R2-US-021
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate edited XLSX digest rejected

  @not_implemented @R2TC064
  Scenario: R2-TC-064 manual/UI evidence equivalence
    Given a scoped test environment for R2-US-022
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate manual/UI evidence equivalence

  @not_implemented @R2TC065
  Scenario: R2-TC-065 wrong database denied
    Given a scoped test environment for R2-US-022
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate wrong database denied

  @not_implemented @R2TC066
  Scenario: R2-TC-066 selector/modal drift fails without guessed clicks
    Given a scoped test environment for R2-US-022
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate selector/modal drift fails without guessed clicks

  @not_implemented @R2TC067
  Scenario: R2-TC-067 qualified native-object provenance
    Given a scoped test environment for R2-US-023
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate qualified native-object provenance

  @not_implemented @R2TC068
  Scenario: R2-TC-068 empty COM output is not zero
    Given a scoped test environment for R2-US-023
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate empty COM output is not zero

  @not_implemented @R2TC069
  Scenario: R2-TC-069 untrusted EPF denied
    Given a scoped test environment for R2-US-023
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate untrusted EPF denied

  @not_implemented @R2TC070
  Scenario: R2-TC-070 exact scope/window/mode admission
    Given a scoped test environment for R2-US-024
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate exact scope/window/mode admission

  @not_implemented @R2TC071
  Scenario: R2-TC-071 production default OFF and expired permit denied
    Given a scoped test environment for R2-US-024
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate production default OFF and expired permit denied

  @not_implemented @R2TC072
  Scenario: R2-TC-072 identical idempotency key with changed parameters returns conflict (409)
    Given a scoped test environment for R2-US-024
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate identical idempotency key with changed parameters returns conflict (409)

  @not_implemented @R2TC073
  Scenario: R2-TC-073 no business writes and complete coverage
    Given a scoped test environment for R2-US-025
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate no business writes and complete coverage

  @not_implemented @R2TC074
  Scenario: R2-TC-074 administrator/posting rights disqualify
    Given a scoped test environment for R2-US-025
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate administrator/posting rights disqualify

  @not_implemented @R2TC075
  Scenario: R2-TC-075 reset/write probes denied in production
    Given a scoped test environment for R2-US-025
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate reset/write probes denied in production

  @not_implemented @R2TC076
  Scenario: R2-TC-076 opaque artifact version and digest
    Given a scoped test environment for R2-US-026
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate opaque artifact version and digest

  @not_implemented @R2TC077
  Scenario: R2-TC-077 nonexistent blob/hash is not evidence
    Given a scoped test environment for R2-US-026
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate nonexistent blob/hash is not evidence

  @not_implemented @R2TC078
  Scenario: R2-TC-078 historical artifact remains subject to current ACL
    Given a scoped test environment for R2-US-026
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate historical artifact remains subject to current ACL

  @not_implemented @R2TC079
  Scenario: R2-TC-079 values-only parsing
    Given a scoped test environment for R2-US-027
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate values-only parsing

  @not_implemented @R2TC080
  Scenario: R2-TC-080 macros/entities/zip bombs denied
    Given a scoped test environment for R2-US-027
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate macros/entities/zip bombs denied

  @not_implemented @R2TC081
  Scenario: R2-TC-081 timeout/memory bounded with no partial-data PASS
    Given a scoped test environment for R2-US-027
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate timeout/memory bounded with no partial-data PASS

  @not_implemented @R2TC082
  Scenario: R2-TC-082 attestation binds exact revision and policy
    Given a scoped test environment for R2-US-028
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate attestation binds exact revision and policy

  @not_implemented @R2TC083
  Scenario: R2-TC-083 self-signing/fabricated PASS denied
    Given a scoped test environment for R2-US-028
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate self-signing/fabricated PASS denied

  @not_implemented @R2TC084
  Scenario: R2-TC-084 revocation ends current validity but preserves history
    Given a scoped test environment for R2-US-028
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate revocation ends current validity but preserves history

  @not_implemented @R2TC085
  Scenario: R2-TC-085 scoped EVALUATION_ONLY
    Given a scoped test environment for R2-US-029
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate scoped EVALUATION_ONLY

  @not_implemented @R2TC086
  Scenario: R2-TC-086 unauthorized evaluation runner denied
    Given a scoped test environment for R2-US-029
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate unauthorized evaluation runner denied

  @not_implemented @R2TC087
  Scenario: R2-TC-087 canonical replay after acceptance
    Given a scoped test environment for R2-US-029
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate canonical replay after acceptance

  @not_implemented @R2TC088
  Scenario: R2-TC-088 all required measures MATCH
    Given a scoped test environment for R2-US-030
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate all required measures MATCH

  @not_implemented @R2TC089
  Scenario: R2-TC-089 wrong opening/turnover causes MISMATCH despite equal closing balance
    Given a scoped test environment for R2-US-030
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate wrong opening/turnover causes MISMATCH despite equal closing balance

  @not_implemented @R2TC090
  Scenario: R2-TC-090 compare contract debit/credit sides separately from netting
    Given a scoped test environment for R2-US-030
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate compare contract debit/credit sides separately from netting

  @not_implemented @R2TC091
  Scenario: R2-TC-091 qualified ledger strategy
    Given a scoped test environment for R2-US-031
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate qualified ledger strategy

  @not_implemented @R2TC092
  Scenario: R2-TC-092 missing settlement register never invented
    Given a scoped test environment for R2-US-031
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate missing settlement register never invented

  @not_implemented @R2TC093
  Scenario: R2-TC-093 a balance alone does not establish aging
    Given a scoped test environment for R2-US-031
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate a balance alone does not establish aging

  @not_implemented @R2TC094
  Scenario: R2-TC-094 correct identity/company/Posted status
    Given a scoped test environment for R2-US-032
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate correct identity/company/Posted status

  @not_implemented @R2TC095
  Scenario: R2-TC-095 exclude unposted/deleted
    Given a scoped test environment for R2-US-032
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate exclude unposted/deleted

  @not_implemented @R2TC096
  Scenario: R2-TC-096 complete pagination and alias proof
    Given a scoped test environment for R2-US-032
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate complete pagination and alias proof

  @not_implemented @R2TC097
  Scenario: R2-TC-097 immutable snapshot proven
    Given a scoped test environment for R2-US-033
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate immutable snapshot proven

  @not_implemented @R2TC098
  Scenario: R2-TC-098 concurrent correction is INCONCLUSIVE
    Given a scoped test environment for R2-US-033
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate concurrent correction is INCONCLUSIVE

  @not_implemented @R2TC099
  Scenario: R2-TC-099 backdated rerun supersedes without overwrite
    Given a scoped test environment for R2-US-033
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate backdated rerun supersedes without overwrite

  @not_implemented @R2TC100
  Scenario: R2-TC-100 claim/evidence coverage
    Given a scoped test environment for R2-US-034
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate claim/evidence coverage

  @not_implemented @R2TC101
  Scenario: R2-TC-101 ten duplicate cases denied
    Given a scoped test environment for R2-US-034
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate ten duplicate cases denied

  @not_implemented @R2TC102
  Scenario: R2-TC-102 purchases validation does not enable AP or alter R1
    Given a scoped test environment for R2-US-034
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate purchases validation does not enable AP or alter R1

  @not_implemented @R2TC103
  Scenario: R2-TC-103 scoped access proven
    Given a scoped test environment for R2-US-035
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate scoped access proven

  @not_implemented @R2TC104
  Scenario: R2-TC-104 folder/new-child permission proof
    Given a scoped test environment for R2-US-035
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate folder/new-child permission proof

  @not_implemented @R2TC105
  Scenario: R2-TC-105 broad OAuth is not claimed to be folder isolation
    Given a scoped test environment for R2-US-035
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate broad OAuth is not claimed to be folder isolation

  @not_implemented @R2TC106
  Scenario: R2-TC-106 start token before baseline + catchup
    Given a scoped test environment for R2-US-036
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate start token before baseline + catchup

  @not_implemented @R2TC107
  Scenario: R2-TC-107 shared-drive namespaces
    Given a scoped test environment for R2-US-036
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate shared-drive namespaces

  @not_implemented @R2TC108
  Scenario: R2-TC-108 lost cursor causes gap/resnapshot
    Given a scoped test environment for R2-US-036
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate lost cursor causes gap/resnapshot

  @not_implemented @R2TC109
  Scenario: R2-TC-109 new revision UNATTESTED while previous PASS remains historical
    Given a scoped test environment for R2-US-037
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate new revision UNATTESTED while previous PASS remains historical

  @not_implemented @R2TC110
  Scenario: R2-TC-110 shortcut/move cannot escape scope
    Given a scoped test environment for R2-US-037
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate shortcut/move cannot escape scope

  @not_implemented @R2TC111
  Scenario: R2-TC-111 deletion does not invent a replacement
    Given a scoped test environment for R2-US-037
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate deletion does not invent a replacement

  @not_implemented @R2TC112
  Scenario: R2-TC-112 invalid grant becomes AUTH_REQUIRED
    Given a scoped test environment for R2-US-038
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate invalid grant becomes AUTH_REQUIRED

  @not_implemented @R2TC113
  Scenario: R2-TC-113 notifications are hints only
    Given a scoped test environment for R2-US-038
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate notifications are hints only

  @not_implemented @R2TC114
  Scenario: R2-TC-114 polling works without watch
    Given a scoped test environment for R2-US-038
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate polling works without watch

  @not_implemented @R2TC115
  Scenario: R2-TC-115 row/fragment/owner/delta
    Given a scoped test environment for R2-US-039
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate row/fragment/owner/delta

  @not_implemented @R2TC116
  Scenario: R2-TC-116 original numbers immutable
    Given a scoped test environment for R2-US-039
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate original numbers immutable

  @not_implemented @R2TC117
  Scenario: R2-TC-117 new evidence creates a new run
    Given a scoped test environment for R2-US-039
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate new evidence creates a new run

  @not_implemented @R2TC118
  Scenario: R2-TC-118 explicit knowledge/effective-time labels
    Given a scoped test environment for R2-US-040
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate explicit knowledge/effective-time labels

  @not_implemented @R2TC119
  Scenario: R2-TC-119 historical is not live-green
    Given a scoped test environment for R2-US-040
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate historical is not live-green

  @not_implemented @R2TC120
  Scenario: R2-TC-120 diff and evidence remain scoped
    Given a scoped test environment for R2-US-040
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate diff and evidence remain scoped

  @not_implemented @R2TC121
  Scenario: R2-TC-121 safe reason/annotation
    Given a scoped test environment for R2-US-041
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate safe reason/annotation

  @not_implemented @R2TC122
  Scenario: R2-TC-122 CSRF/idempotency enforcement (403/409)
    Given a scoped test environment for R2-US-041
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate CSRF/idempotency enforcement (403/409)

  @not_implemented @R2TC123
  Scenario: R2-TC-123 raw COM/DC cannot bypass denial
    Given a scoped test environment for R2-US-041
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate raw COM/DC cannot bypass denial

  @not_implemented @R2TC124
  Scenario: R2-TC-124 exact-scope capture/comparison
    Given a scoped test environment for R2-US-042
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate exact-scope capture/comparison

  @not_implemented @R2TC125
  Scenario: R2-TC-125 dev PASS does not grant production approval
    Given a scoped test environment for R2-US-042
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate dev PASS does not grant production approval

  @not_implemented @R2TC126
  Scenario: R2-TC-126 kill switch owns running jobs
    Given a scoped test environment for R2-US-042
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate kill switch owns running jobs

  @not_implemented @R2TC127
  Scenario: R2-TC-127 sessions-vs-active grid
    Given a scoped test environment for R2-US-043
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate sessions-vs-active grid

  @not_implemented @R2TC128
  Scenario: R2-TC-128 denied profiles excluded from throughput
    Given a scoped test environment for R2-US-043
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate denied profiles excluded from throughput

  @not_implemented @R2TC129
  Scenario: R2-TC-129 background interference and budget
    Given a scoped test environment for R2-US-043
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate background interference and budget

  @not_implemented @R2TC130
  Scenario: R2-TC-130 audit failure is fail-closed
    Given a scoped test environment for R2-US-044
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate audit failure is fail-closed

  @not_implemented @R2TC131
  Scenario: R2-TC-131 replica/network 429 without duplicates
    Given a scoped test environment for R2-US-044
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate replica/network 429 without duplicates

  @not_implemented @R2TC132
  Scenario: R2-TC-132 alarm fires and resolves
    Given a scoped test environment for R2-US-044
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate alarm fires and resolves

  @not_implemented @R2TC133
  Scenario: R2-TC-133 additive shadow regression
    Given a scoped test environment for R2-US-045
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate additive shadow regression

  @not_implemented @R2TC134
  Scenario: R2-TC-134 destructive rollback denied
    Given a scoped test environment for R2-US-045
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate destructive rollback denied

  @not_implemented @R2TC135
  Scenario: R2-TC-135 switchover rollback never resurrects revoked grants
    Given a scoped test environment for R2-US-045
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate switchover rollback never resurrects revoked grants

  @not_implemented @R2TC136
  Scenario: R2-TC-136 restored foreign keys/digests/heads
    Given a scoped test environment for R2-US-046
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate restored foreign keys/digests/heads

  @not_implemented @R2TC137
  Scenario: R2-TC-137 export masking/tenant/formula safety
    Given a scoped test environment for R2-US-046
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate export masking/tenant/formula safety

  @not_implemented @R2TC138
  Scenario: R2-TC-138 legal hold and no unauthorized deletion
    Given a scoped test environment for R2-US-046
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate legal hold and no unauthorized deletion

  @not_implemented @R2TC139
  Scenario: R2-TC-139 adapter contract qualification
    Given a scoped test environment for R2-US-047
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate adapter contract qualification

  @not_implemented @R2TC140
  Scenario: R2-TC-140 personal corpus expansion denied
    Given a scoped test environment for R2-US-047
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate personal corpus expansion denied

  @not_implemented @R2TC141
  Scenario: R2-TC-141 pinned upgrade triggers retesting
    Given a scoped test environment for R2-US-047
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate pinned upgrade triggers retesting

  @not_implemented @R2TC142
  Scenario: R2-TC-142 complete manifest, IDs and actual results
    Given a scoped test environment for R2-US-048
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate complete manifest, IDs and actual results

  @not_implemented @R2TC143
  Scenario: R2-TC-143 NOT_RUN cannot become release PASS
    Given a scoped test environment for R2-US-048
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate NOT_RUN cannot become release PASS

  @not_implemented @R2TC144
  Scenario: R2-TC-144 separate user/admin/production UAT
    Given a scoped test environment for R2-US-048
    When the relevant Phase 2 capability is exercised
    Then the product must demonstrate separate user/admin/production UAT
