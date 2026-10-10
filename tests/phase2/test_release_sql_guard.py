"""S9 E3 (TC133): offline guard over the REAL db/phase2/001..003 SQL text (tests may read files, modules may not).

Every DDL/DCL phrase is mapped to a typed step and judged by ``classify_step``; the guard is self-tested on
planted text so it can fail. Statements that do not fit the plan's narrow set (CREATE ... IF NOT EXISTS /
CREATE OR REPLACE / GRANT / INSERT in schema living) are NOT silently allowed: each has an explicit,
named entry in ``KNOWN_EXTRA`` below, and the test asserts that table is exactly what the files contain.
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
    (r"GRANT\b(?!.*\bTO\s+(?!living_|%I|PUBLIC)).*", K.GRANT, O.PRIVILEGE, True),
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
_DROP_TRIGGER = re.compile(r"DROP TRIGGER IF EXISTS (\w+) ON living\.(\w+)")
_CREATE_TRIGGER = re.compile(r"CREATE TRIGGER (\w+) \w+ .* ON living\.(\w+)")
_DROP_POLICY = re.compile(r"DROP POLICY IF EXISTS (\w+) ON living\.(\w+|%I)")
_DROP_LEGACY_FN = "DROP FUNCTION living.record_migration(text,text[])"
_ALLOWED_POLICY_NAMES = {"tenant_scope", "scope_isolation", "owner_all"}
_QUAL_ALIASES = {"NEW", "OLD", "att", "lat", "n"}  # row/alias names, not relations

DENYLIST = [
    r"\bDROP\s+(TABLE|SCHEMA|COLUMN|INDEX|TYPE|ROLE|VIEW|SEQUENCE|DATABASE|OWNED|CONSTRAINT)\b",
    r"\bTRUNCATE\s+TABLE\b", r"\bDELETE\s+FROM\b", r"\bRENAME\b",
    r"\bALTER\s+TABLE\b[^;]*\b(DROP|ALTER\s+COLUMN|TYPE)\b", r"\bpublic\.", r"\bDROP\s+SCHEMA\b",
]


def strip_comments(text):
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
        out.append(ch)
        i += 1
    return "".join(out)


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


def analyse(text):
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
            else:
                problems.append(f"policy:{p[:60]}")
            i += 1
            continue
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
    steps, problems, _ = analyse(real(name))
    assert problems == []
    assert steps, "the guard found nothing to judge: the scanner is broken"


@pytest.mark.parametrize("name", FILES)
def test_every_typed_step_of_the_real_files_classifies_additive(name):
    steps, _, _ = analyse(real(name))
    assert {classify_step(s) for s in steps} == {StepClass.ADDITIVE}


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


def test_files_exist_and_are_utf8():
    for name in FILES:
        assert real(name).strip()
