"""S9 E3 (TC133): offline guard over the REAL db/phase2/001..003 SQL text (tests may read files, modules may not).

Every DDL/DCL phrase is mapped to a typed step and judged by ``classify_step``; the guard is self-tested on
planted text so it can fail. Statements that do not fit the plan's narrow set (CREATE ... IF NOT EXISTS /
CREATE OR REPLACE / GRANT / INSERT in schema living) are NOT silently allowed: each has an explicit,
named entry in ``KNOWN_EXTRA`` below, and the test asserts that table is exactly what the files contain.

Documented limit (G2): the guard maps real SQL to typed steps ITSELF (a real ``REVOKE`` becomes
``HARDEN_PRIVILEGES`` here, not by a caller's say-so), but ``classify_step`` treats ``HARDEN_PRIVILEGES``,
``SET_OWNER``, ``ENABLE_RLS`` and ``REPLACE_*`` as ADDITIVE although they narrow access. A caller who TYPES a
migration step by hand (``plan_rehearsal``) can therefore describe a REVOKE as ``HARDEN_PRIVILEGES``; only this
text guard over the real files is able to see the SQL. A rollback plan refuses ``HARDEN_PRIVILEGES`` altogether.
"""
import re
from pathlib import Path

import pytest

from business_ai_gateway.phase2.release_migration import (
    MigrationStep,
    ObjectClass,
    Phase,
    SchemaName,
    StepClass,
    StepKind,
    classify_step,
)

_DB = Path(__file__).resolve().parents[2] / "db" / "phase2"
FILES = ["001_living_registry.sql", "002_job_cursor_functions.sql", "003_security_hardening.sql"]
K, O = StepKind, ObjectClass

# Phrases are DDL/DCL statements at a statement start (after ; ' $ ( or THEN/BEGIN/LOOP/ELSE/DECLARE).
_START = re.compile(r"\b(CREATE|DROP|ALTER|GRANT|REVOKE|TRUNCATE|DELETE\s+FROM|COMMENT\s+ON|RENAME)\b")
_PREV_WORDS = {"THEN", "BEGIN", "LOOP", "ELSE", "DECLARE"}

# (regex anchored at phrase start, StepKind, ObjectClass, plan_fit). plan_fit False = not in the plan's
# narrow set, reported explicitly through KNOWN_EXTRA.
_RULES = [
    (r"CREATE SCHEMA IF NOT EXISTS living\b", K.CREATE_SCHEMA, O.SCHEMA, True),
    (r"CREATE TABLE IF NOT EXISTS living\.\w+", K.CREATE_TABLE, O.TABLE, True),
    (r"CREATE (UNIQUE )?INDEX IF NOT EXISTS \w+ ON living\.\w+", K.CREATE_INDEX, O.INDEX, True),
    (r"CREATE OR REPLACE FUNCTION living\.\w+", K.ADD_FUNCTION, O.FUNCTION, True),
    # --- not in the plan's narrow set ---
    (r"CREATE FUNCTION living\.record_migration\(", K.ADD_FUNCTION, O.FUNCTION, False),
    (r"CREATE TRIGGER \w+ (BEFORE|AFTER) [A-Z ]+ ON living\.\w+", K.ADD_TRIGGER, O.TRIGGER, False),
    (r"CREATE POLICY \w+ ON living\.(\w+|%I)", K.ADD_POLICY, O.POLICY, False),
    (r"ALTER TABLE living\.(\w+|%I) (ENABLE|FORCE) ROW LEVEL SECURITY", K.ENABLE_RLS, O.TABLE, False),
    (r"ALTER TABLE living\.\w+ ADD COLUMN IF NOT EXISTS \w+ ", K.ADD_DEFAULTED_COLUMN, O.COLUMN, False),
    (r"ALTER TABLE %s OWNER TO living_owner", K.SET_OWNER, O.TABLE, False),
    (r"ALTER FUNCTION %s OWNER TO living_owner", K.SET_OWNER, O.FUNCTION, False),
    (r"ALTER FUNCTION %s SECURITY DEFINER SET search_path = pg_catalog, pg_temp", K.HARDEN_FUNCTION,
     O.FUNCTION, False),
    (r"CREATE ROLE %I NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE", K.ADD_ROLE, O.ROLE, False),
    (r"REVOKE\b.*\bliving\b.*", K.HARDEN_PRIVILEGES, O.PRIVILEGE, False),
    (r"ALTER DEFAULT PRIVILEGES FOR ROLE living_owner ", K.HARDEN_PRIVILEGES, O.PRIVILEGE, False),
]
_GRANT_ROLE = re.compile(r"living_\w+|%I")
# the one role-membership grant of the real files: the bootstrap gives living_owner to the migrating user
_MEMBERSHIP_ALLOWED = {"GRANT living_owner TO %I"}
# policies dropped in one file and re-created elsewhere in the SAME file (not immediately): explicit and named
_POLICY_REPLACED_LATER = {("003_security_hardening.sql", "tenant_scope"), ("003_security_hardening.sql", "scope_isolation")}
_DROP_TRIGGER = re.compile(r"DROP TRIGGER IF EXISTS (\w+) ON living\.(\w+)")
_CREATE_TRIGGER = re.compile(r"CREATE TRIGGER (\w+) \w+ .* ON living\.(\w+)")
_DROP_POLICY = re.compile(r"DROP POLICY IF EXISTS (\w+) ON living\.(\w+|%I)")
_CREATE_POLICY = re.compile(r"CREATE POLICY (\w+) ON living\.(\w+|%I)")
_DROP_LEGACY_FN = "DROP FUNCTION living.record_migration(text,text[])"
_ALLOWED_POLICY_NAMES = {"tenant_scope", "scope_isolation", "owner_all"}
_QUAL_ALIASES = {"NEW", "OLD", "att", "lat", "n"}  # row/alias names, not relations

DENYLIST = [
    r"\bDROP\s+(TABLE|SCHEMA|COLUMN|INDEX|TYPE|ROLE|VIEW|SEQUENCE|DATABASE|OWNED|CONSTRAINT)\b",
    r"\bTRUNCATE\s+(TABLE\s+)?(ONLY\s+)?(living|public|r1)\.", r"\bDELETE\s+FROM\b", r"\bRENAME\b",
    r"\bALTER\s+TABLE\b[^;]*\b(DROP|ALTER\s+COLUMN|TYPE)\b", r"\bpublic\.", r"\bDROP\s+SCHEMA\b",
]


def strip_comments(text):
    """Remove ``--`` and (nested, like PostgreSQL) ``/* */`` comments outside single-quoted strings.

    Dollar-quoted bodies are CODE (function bodies), so comments inside them are comments too, while quotes keep
    their meaning inside them. An unterminated ``/*`` swallows the rest, exactly like the server would refuse it.
    A comment is replaced by one space so that it can never glue two tokens together.
    """
    out, i, in_sq = [], 0, False
    while i < len(text):
        ch = text[i]
        if in_sq:
            in_sq = ch != "'"
        elif ch == "'":
            in_sq = True
        elif text.startswith("--", i):
            j = text.find("\n", i)
            if j < 0:
                break
            i = j
            continue
        elif text.startswith("/*", i):
            depth, i = 1, i + 2
            while i < len(text) and depth:
                if text.startswith("/*", i):
                    depth, i = depth + 1, i + 2
                elif text.startswith("*/", i):
                    depth, i = depth - 1, i + 2
                else:
                    i += 1
            out.append(" ")
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def grant_problems(stmt):
    """Judge one GRANT: only roles living_*, only objects of schema living, no PUBLIC, no unknown membership grant."""
    stmt = " ".join(stmt.split("'")[0].split())
    found = []
    to = re.search(r"\bTO\s+(.*?)(?:\s+WITH\b.*)?$", stmt)
    roles = [r.strip() for r in to.group(1).split(",")] if to else []
    if not roles or any(_GRANT_ROLE.fullmatch(r) is None for r in roles):
        found.append(f"grant-to-role:{stmt[:60]}")  # PUBLIC, r1_*, unknown roles
    if re.search(r"\bWITH\s+(GRANT|ADMIN)\s+OPTION\b", stmt):
        found.append(f"grant-option:{stmt[:60]}")
    if re.search(r"\bON\b", stmt) is None:  # role membership: GRANT role TO role
        if stmt not in _MEMBERSHIP_ALLOWED:
            found.append(f"grant-membership:{stmt[:60]}")
    else:
        target = stmt.split(" ON ", 1)[1] if " ON " in stmt else ""
        target = re.split(r"\s+TO\s+", target)[0]
        schemas = re.split(r"\s*,\s*", target.split("SCHEMA ", 1)[1].strip()) if "SCHEMA " in target else []
        if any(n != "living" for n in schemas) or not re.search(
                r"\bSCHEMA\s+living\b|\bliving\.", target):
            found.append(f"grant-outside-living:{stmt[:60]}")
    return found


def default_privileges_problems(stmt):
    """ALTER DEFAULT PRIVILEGES may only REVOKE (narrow); any GRANT form is a problem."""
    stmt = " ".join(stmt.split())
    if re.search(r"\bGRANT\b", stmt) or re.search(r"\bREVOKE\b", stmt) is None or re.search(r"\bTO\s+PUBLIC\b", stmt, re.IGNORECASE):
        return [f"default-privileges:{stmt[:60]}"]
    return []


def phrases(text):
    found = []
    for m in _START.finditer(text):
        k = m.start() - 1
        while k >= 0 and text[k].isspace():
            k -= 1
        ok = k < 0 or text[k] in ";'$("
        if not ok:
            j = k
            while j >= 0 and (text[j].isalnum() or text[j] == "_"):
                j -= 1
            ok = text[j + 1:k + 1].upper() in _PREV_WORDS
        if ok:
            end = text.find(";", m.start())
            seg = text[m.start(): end if end >= 0 else m.start() + 600]
            found.append(" ".join(seg.split()))
    return found


def analyse(text, name=None):
    """Return (steps, problems, extras). steps are typed MigrationSteps; problems are guard violations."""
    clean = strip_comments(text)
    steps, problems, extras = [], [], []
    for pattern in DENYLIST:
        for m in re.finditer(pattern, clean):
            problems.append(f"denylist:{m.group(0)[:40]}")
    ph = phrases(clean)
    i = 0
    while i < len(ph):
        p = ph[i]
        m = _DROP_TRIGGER.match(p)
        if m:  # must be immediately re-created with the same name on the same living table
            nxt = _CREATE_TRIGGER.match(ph[i + 1]) if i + 1 < len(ph) else None
            if nxt and nxt.groups() == m.groups():
                steps.append(MigrationStep(Phase.EXPAND, K.REPLACE_TRIGGER, SchemaName.LIVING, O.TRIGGER))
                extras.append("DROP TRIGGER IF EXISTS + CREATE TRIGGER (replace)")
                i += 2
                continue
            problems.append(f"unpaired:{p[:60]}")
            i += 1
            continue
        m = _DROP_POLICY.match(p)
        if m:
            if m.group(1) in _ALLOWED_POLICY_NAMES:
                steps.append(MigrationStep(Phase.EXPAND, K.REPLACE_POLICY, SchemaName.LIVING, O.POLICY))
                extras.append("DROP POLICY IF EXISTS (replace)")
                # H4: the CREATE POLICY with the same name and table must follow the run of DROP POLICY statements
                j = i
                while j < len(ph) and _DROP_POLICY.match(ph[j]):
                    j += 1
                created = set()
                while j < len(ph) and (mc := _CREATE_POLICY.match(ph[j])):
                    created.add((mc.group(1), mc.group(2)))
                    j += 1
                if (m.group(1), m.group(2)) not in created and (name, m.group(1)) not in _POLICY_REPLACED_LATER:
                    problems.append(f"unpaired-policy:{p[:60]}")
            else:
                problems.append(f"policy:{p[:60]}")
            i += 1
            continue
        if p.startswith("GRANT"):
            found = grant_problems(p)
            problems.extend(found)
            steps.append(MigrationStep(Phase.EXPAND, K.GRANT, SchemaName.LIVING, O.PRIVILEGE))
            i += 1
            continue
        if p.startswith("ALTER DEFAULT PRIVILEGES"):
            problems.extend(default_privileges_problems(p))
        # H3: a NOT NULL / CHECK / UNIQUE column without a DEFAULT is not "defaulted": it can fail on a filled table
        if (re.match(r"ALTER TABLE living\.\w+ ADD COLUMN IF NOT EXISTS \w+ ", p)
                and re.search(r"\b(NOT NULL|CHECK|UNIQUE|PRIMARY KEY|REFERENCES)\b", p)
                and re.search(r"\bDEFAULT\b", p) is None):
            problems.append(f"column-without-default:{p[:60]}")
        if p == _DROP_LEGACY_FN:
            steps.append(MigrationStep(Phase.EXPAND, K.REPLACE_FUNCTION, SchemaName.LIVING, O.FUNCTION))
            extras.append("DROP FUNCTION living.record_migration (legacy replace)")
            i += 1
            continue
        for regex, kind, oc, fit in _RULES:
            if re.match(regex, p):
                steps.append(MigrationStep(Phase.EXPAND, kind, SchemaName.LIVING, oc))
                if not fit:
                    extras.append(p.split(" ON ")[0][:60] if p.startswith(("REVOKE", "GRANT")) is False
                                  else p[:25])
                break
        else:
            problems.append(f"unmapped:{p[:70]}")
        i += 1
    for m in re.finditer(r"\bINSERT\s+INTO\s+([\w.%\"]+)", clean):
        if not m.group(1).startswith("living."):
            problems.append(f"insert-target:{m.group(1)}")
    for m in re.finditer(r"\bUPDATE\s+([\w.%\"]+)(?:\s+\w+)?\s+SET\b", clean):
        if not m.group(1).startswith("living."):
            problems.append(f"update-target:{m.group(1)}")
    for m in re.finditer(
            r"\b(FROM|JOIN|UPDATE|INTO|REFERENCES|TABLE|ON|FUNCTION|SCHEMA)\s+"
            r"(?:IF\s+(?:NOT\s+)?EXISTS\s+)?([A-Za-z_]\w*)\.[A-Za-z_%]", clean):
        schema = m.group(2)
        if schema == "living" or schema in _QUAL_ALIASES:
            continue
        if schema == "pg_catalog" and m.group(1).upper() in ("FROM", "JOIN"):
            continue  # read-only catalog lookups
        problems.append(f"foreign-ref:{m.group(1)} {schema}")
    for m in re.finditer(r"nspname\s*=\s*'(\w+)'", clean):
        if m.group(1) != "living":
            problems.append(f"nspname:{m.group(1)}")
    for stmt in ph:
        if stmt.startswith(("GRANT", "REVOKE", "ALTER DEFAULT PRIVILEGES")) and "living" not in stmt:
            problems.append(f"grant-without-living:{stmt[:50]}")
    return steps, problems, extras


def real(name):
    return (_DB / name).read_text(encoding="utf-8")


# ---- the real files -------------------------------------------------------------------------------

@pytest.mark.parametrize("name", FILES)
def test_real_migration_has_no_problem_statement(name):
    steps, problems, _ = analyse(real(name), name)
    assert problems == []
    assert steps, "the guard found nothing to judge: the scanner is broken"


@pytest.mark.parametrize("name", FILES)
def test_scanner_mapping_is_internally_consistent_with_classify_step(name):
    """NOT evidence about the SQL: every step the scanner builds is ADDITIVE by construction of ``_RULES``.

    It only proves the mapping table and ``classify_step`` still agree (a rule mapped to a kind that classify_step
    would deny would show up here). The SQL itself is judged by the ``problems`` list and the structural tests below.
    """
    steps, _, _ = analyse(real(name), name)
    assert {classify_step(s) for s in steps} == {StepClass.ADDITIVE}


def test_the_guard_functions_still_raise_and_the_immutability_triggers_cover_update_and_delete():
    """H4: the safety behaviour of the real SQL, not the typing of it."""
    text = strip_comments("\n".join(real(n) for n in FILES))
    reject = re.findall(r"CREATE OR REPLACE FUNCTION living\.reject_immutable_mutation\(\).*?END \$fn\$;", text, re.DOTALL)
    assert reject and all("RAISE EXCEPTION 'IMMUTABLE_LEDGER'" in b for b in reject)
    guards = re.findall(r"CREATE OR REPLACE FUNCTION living\.accepted_heads_guard\(\).*?\$fn\$;", text, re.DOTALL)
    assert len(guards) == 2 and all(g.count("RAISE EXCEPTION 'HEAD_CHANGE_FORBIDDEN'") >= 2 for g in guards)
    events = {}
    for m in re.finditer(r"CREATE TRIGGER (\w+) BEFORE ([A-Z ]+?) ON living\.(\w+)\s+FOR EACH (ROW|STATEMENT) "
                         r"EXECUTE FUNCTION living\.reject_immutable_mutation\(\)", text):
        events.setdefault(m.group(3), set()).update(m.group(2).split(" OR "))
    for table in ("observations", "acceptance_events"):
        assert {"UPDATE", "DELETE", "TRUNCATE"} <= events[table], table
    assert {"DELETE", "TRUNCATE"} <= events["attestations"]  # UPDATE has its own guard that allows revocation only
    assert re.search(r"CREATE TRIGGER attestations_immutable BEFORE UPDATE ON living\.attestations", text)
    assert "TRUNCATE" in events["outbox"]


def test_scanner_sees_the_real_statement_population():
    counts = {k: 0 for k in StepKind}
    for name in FILES:
        for s in analyse(real(name))[0]:
            counts[s.kind] += 1
    assert counts[K.CREATE_SCHEMA] == 1 and counts[K.CREATE_TABLE] == 12
    assert counts[K.ADD_FUNCTION] >= 40 and counts[K.GRANT] >= 10 and counts[K.REPLACE_TRIGGER] >= 10
    assert counts[K.ADD_ROLE] == 1 and counts[K.ADD_DEFAULTED_COLUMN] == 3
    for kind in DESTRUCTIVE:
        assert counts[kind] == 0


DESTRUCTIVE = [K.DROP_TABLE, K.DROP_COLUMN, K.DROP_INDEX, K.DROP_FUNCTION, K.DROP_TRIGGER, K.DROP_POLICY,
               K.DROP_SCHEMA, K.DROP_ROLE, K.TRUNCATE, K.ALTER_TYPE, K.RENAME, K.REVOKE, K.DELETE_ROWS,
               K.UPDATE_ROWS, K.NARROW_CONSTRAINT]


def test_known_extra_statement_kinds_are_exactly_the_documented_set():
    """Statements outside the plan's narrow set. If a file gains a new kind this test must be edited."""
    seen = set()
    for name in FILES:
        for p in phrases(strip_comments(real(name))):
            if p.startswith("GRANT"):
                continue
            for regex, kind, _, fit in _RULES:
                if re.match(regex, p):
                    if not fit:
                        seen.add(kind)
                    break
    assert seen == {K.ADD_FUNCTION, K.ADD_TRIGGER, K.ADD_POLICY, K.ENABLE_RLS, K.ADD_DEFAULTED_COLUMN,
                    K.SET_OWNER, K.HARDEN_FUNCTION, K.ADD_ROLE, K.HARDEN_PRIVILEGES}


def test_dropped_policies_are_recreated_somewhere_in_the_set():
    text = strip_comments("\n".join(real(n) for n in FILES))
    created = set(re.findall(r"CREATE POLICY (\w+) ON", text))
    dropped = set(re.findall(r"DROP POLICY IF EXISTS (\w+) ON", text))
    assert dropped <= _ALLOWED_POLICY_NAMES and dropped
    assert created >= {"scope_isolation", "owner_all"} and "tenant_scope" in created


def test_role_creation_covers_only_living_roles():
    text = strip_comments(real("003_security_hardening.sql"))
    arr = re.search(r"FOREACH r IN ARRAY ARRAY\[(.*?)\]", text, re.DOTALL).group(1)
    roles = re.findall(r"'(\w+)'", arr)
    assert roles and all(r.startswith("living_") for r in roles)


def test_legacy_function_drop_is_only_the_guarded_living_record_migration():
    text = strip_comments(real("001_living_registry.sql"))
    assert text.count("DROP FUNCTION") == 1
    assert "DROP FUNCTION living.record_migration(text,text[])" in text
    assert "<> 'boolean'::regtype" in text  # only reached for an old void-returning version


def test_default_privileges_statement_is_not_schema_scoped_but_pinned_to_the_new_owner_role():
    """Honest finding: the first ALTER DEFAULT PRIVILEGES has no IN SCHEMA; it is bounded by FOR ROLE living_owner."""
    stmts = [p for p in phrases(strip_comments(real("003_security_hardening.sql")))
             if p.startswith("ALTER DEFAULT PRIVILEGES")]
    assert len(stmts) == 2
    assert all("FOR ROLE living_owner" in s for s in stmts)
    assert sum("IN SCHEMA living" in s for s in stmts) == 1


# ---- self-tests: planted text must be caught ------------------------------------------------------

def planted(sql):
    return analyse("BEGIN;\n" + sql + "\nCOMMIT;")


@pytest.mark.parametrize("sql", [
    "DROP TABLE living.jobs;", "DROP SCHEMA living CASCADE;", "TRUNCATE living.jobs;",
    "TRUNCATE TABLE living.jobs;", "ALTER TABLE living.jobs DROP COLUMN payload;",
    "ALTER TABLE living.jobs RENAME TO jobs2;", "ALTER TABLE living.jobs ALTER COLUMN state TYPE int;",
    "DELETE FROM living.jobs;", "DROP INDEX living.jobs_one_running_per_source;",
    "DROP ROLE living_owner;", "DROP TRIGGER IF EXISTS t ON living.jobs;",
    "DROP POLICY IF EXISTS other ON living.jobs;",
    "CREATE TABLE public.invoices(id int);", "CREATE TABLE IF NOT EXISTS public.x(id int);",
    "CREATE TABLE living.t(id int);",  # not IF NOT EXISTS
    "INSERT INTO public.invoices VALUES (1);", "UPDATE public.invoices SET a = 1;",
    "GRANT SELECT ON public.invoices TO someone;", "REVOKE ALL ON public.invoices FROM PUBLIC;",
    "SELECT 1 FROM public.invoices;", "SELECT 1 FROM r1.invoices;",
    "ALTER TABLE r1.invoices ADD COLUMN IF NOT EXISTS x text;",
    "CREATE OR REPLACE FUNCTION public.f() RETURNS int LANGUAGE sql AS 'select 1';",
    "COMMENT ON TABLE living.jobs IS 'x';", "ALTER SCHEMA living RENAME TO other;",
    "SELECT 1 FROM pg_catalog.pg_class WHERE nspname='public';",
    "CREATE ROLE r1_admin LOGIN;",
])
def test_guard_flags_planted_statement(sql):
    _, problems, _ = planted(sql)
    assert problems, sql


def test_guard_accepts_a_minimal_clean_migration_and_types_it_additive():
    steps, problems, _ = planted(
        "CREATE SCHEMA IF NOT EXISTS living;\nCREATE TABLE IF NOT EXISTS living.t(id int);\n"
        "CREATE UNIQUE INDEX IF NOT EXISTS t_idx ON living.t(id);\n"
        "CREATE OR REPLACE FUNCTION living.f() RETURNS int LANGUAGE sql AS 'select 1';\n"
        "GRANT SELECT ON living.t TO living_reader;")
    assert problems == [] and len(steps) == 5
    assert {classify_step(s) for s in steps} == {StepClass.ADDITIVE}


def test_planted_drop_maps_to_a_destructive_or_unclassified_typed_step():
    drop = MigrationStep(Phase.EXPAND, K.DROP_TABLE, SchemaName.LIVING, O.TABLE)
    r1 = MigrationStep(Phase.EXPAND, K.CREATE_TABLE, SchemaName.R1, O.R1_TABLE)
    assert classify_step(drop) is StepClass.DESTRUCTIVE
    assert classify_step(r1) is StepClass.UNCLASSIFIED


def test_comments_do_not_hide_or_fake_statements():
    steps, problems, _ = planted("-- DROP TABLE living.jobs;\nCREATE TABLE IF NOT EXISTS living.t(id int);")
    assert problems == [] and len(steps) == 1
    _, problems2, _ = planted("CREATE TABLE IF NOT EXISTS living.t(id int); -- ok\nDROP TABLE living.t;")
    assert problems2


def test_guard_flags_a_drop_hidden_in_a_dollar_quoted_body():
    _, problems, _ = planted("DO $x$ BEGIN EXECUTE 'DROP TABLE living.jobs'; END $x$;")
    assert problems


@pytest.mark.parametrize("sql", [
    "/* x */ TRUNCATE living.jobs;", "/* a /* nested */ still comment */ TRUNCATE living.jobs;",
    "/* x */ DROP TABLE living.jobs;", "SELECT 1; /* x */ DELETE FROM living.jobs;", "/**/TRUNCATE living.jobs;",
    "TRUNCATE living.jobs, living.cursors;", "/* c */ TRUNCATE ONLY living.jobs;",
    "DROP FUNCTION living.reject_immutable_mutation();", "/* c */ DROP FUNCTION living.f(text);",
    ("DROP TRIGGER IF EXISTS t ON living.jobs;\nCREATE TRIGGER other BEFORE UPDATE ON living.jobs FOR EACH ROW "
     "EXECUTE FUNCTION living.f();"),
    ("DROP TRIGGER IF EXISTS t ON living.jobs;\nCREATE TRIGGER t BEFORE UPDATE ON living.cursors FOR EACH ROW "
     "EXECUTE FUNCTION living.f();"),
    "DROP POLICY IF EXISTS owner_all ON living.jobs;",
    "DROP POLICY IF EXISTS owner_all ON living.jobs;\nCREATE POLICY scope_isolation ON living.jobs FOR ALL USING (true);",
    "DROP POLICY IF EXISTS owner_all ON living.jobs;\nCREATE POLICY owner_all ON living.cursors USING (true);",
])
def test_guard_flags_block_comment_and_unpaired_drop_variants(sql):
    _, problems, _ = planted(sql)
    assert problems, sql


def test_block_comments_do_not_hide_text_in_strings_and_do_not_eat_code():
    steps, problems, _ = planted("/* DROP TABLE living.jobs; */ CREATE TABLE IF NOT EXISTS living.t(id int);")
    assert problems == [] and len(steps) == 1
    # a /* inside a string literal is not a comment: the DROP after it is still seen
    _, problems2, _ = planted("SELECT '/*'; DROP TABLE living.t; SELECT '*/';")
    assert problems2
    assert strip_comments("a/*x*/b") == "a b"


def test_a_paired_policy_replace_is_accepted():
    _, problems, _ = planted("DROP POLICY IF EXISTS owner_all ON living.jobs;\n"
                             "CREATE POLICY owner_all ON living.jobs FOR ALL USING (true);")
    assert problems == []


@pytest.mark.parametrize("sql", [
    "GRANT SELECT ON ALL TABLES IN SCHEMA r1 TO living_reader;",
    "GRANT r1_admin TO living_worker;",
    "GRANT living_owner TO living_worker;",
    "ALTER DEFAULT PRIVILEGES FOR ROLE living_owner GRANT ALL ON TABLES TO PUBLIC;",
    "ALTER DEFAULT PRIVILEGES FOR ROLE living_owner IN SCHEMA living GRANT SELECT ON TABLES TO living_reader;",
    "GRANT SELECT ON living.jobs TO PUBLIC;",
    "GRANT SELECT ON living.jobs TO living_reader, PUBLIC;",
    "GRANT SELECT ON living.jobs TO r1_reader;",
    "GRANT SELECT ON living.jobs TO living_reader WITH GRANT OPTION;",
    "GRANT ALL ON SCHEMA public TO living_reader;",
    "GRANT SELECT ON ALL TABLES IN SCHEMA living, r1 TO living_reader;",
    "GRANT EXECUTE ON FUNCTION r1.f() TO living_reader;",
])
def test_guard_flags_planted_dangerous_grants(sql):
    _, problems, _ = planted(sql)
    assert problems, sql


@pytest.mark.parametrize("sql", [
    "GRANT SELECT ON living.jobs, living.cursors TO living_reader, living_worker;",
    "GRANT USAGE ON SCHEMA living TO living_worker;",
    "GRANT SELECT ON ALL TABLES IN SCHEMA living TO living_reader;",
    "GRANT EXECUTE ON FUNCTION living.f(text), living.g() TO living_worker;",
    "ALTER DEFAULT PRIVILEGES FOR ROLE living_owner IN SCHEMA living REVOKE ALL ON TABLES FROM PUBLIC;",
])
def test_guard_accepts_the_narrow_grant_and_revoke_forms(sql):
    _, problems, _ = planted(sql)
    assert problems == [], sql


@pytest.mark.parametrize("sql", [
    "ALTER TABLE living.t ADD COLUMN IF NOT EXISTS x text NOT NULL;",
    "ALTER TABLE living.t ADD COLUMN IF NOT EXISTS x int CHECK(x>0);",
    "ALTER TABLE living.t ADD COLUMN IF NOT EXISTS x text UNIQUE;",
])
def test_add_column_that_can_fail_on_a_filled_table_is_flagged(sql):
    _, problems, _ = planted(sql)
    assert problems, sql


@pytest.mark.parametrize("sql", [
    "ALTER TABLE living.t ADD COLUMN IF NOT EXISTS x text;",
    "ALTER TABLE living.t ADD COLUMN IF NOT EXISTS x bigint NOT NULL DEFAULT 0 CHECK(x>=0);",
])
def test_defaulted_or_nullable_add_column_is_accepted(sql):
    _, problems, _ = planted(sql)
    assert problems == [], sql


def test_real_default_privileges_only_revoke_and_real_grants_are_narrow():
    for name in FILES:
        for p in phrases(strip_comments(real(name))):
            if p.startswith("GRANT"):
                assert grant_problems(p) == [], p
            if p.startswith("ALTER DEFAULT PRIVILEGES"):
                assert default_privileges_problems(p) == [], p


def test_files_exist_and_are_utf8():
    for name in FILES:
        assert real(name).strip()
