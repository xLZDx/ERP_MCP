-- R2/G1 S13, simulated lane of the change ledger: Ed25519 signature VERIFICATION (RFC 8032 section 5.1) as pure
-- PL/pgSQL, no extension. Applies after 013. Apply ONLY to a verified disposable PostgreSQL database (checksum
-- precondition: living.record_migration). NON-GATING PROTOTYPE: not gate evidence. The verifier is NOT audited and NOT
-- constant-time; it is a public-input verifier (public key, message and signature are all public), so timing is not a
-- secret-leak channel here, but the code is a test-lane mechanism and must not be treated as a production crypto library.
--
-- WHAT. change_ledger.ed25519_verify(p_public_key bytea, p_message bytea, p_signature bytea) RETURNS boolean,
-- IMMUTABLE. NULL in any argument returns false (it is deliberately NOT declared STRICT: STRICT would return NULL).
-- It mirrors src/business_ai_gateway/phase2/ed25519.py verify() step by step, so the two implementations accept and
-- reject exactly the same inputs:
--   * public key must be 32 bytes and signature 64 bytes (otherwise false);
--   * the public key A and the signature point R are decompressed per RFC 8032 5.1.3: y is the 255 low bits (little
--     endian), the top bit is the sign of x; y >= p (non-canonical encoding) is rejected; x is recovered with the
--     p = 5 (mod 8) square-root trick x = (u/v)^((p+3)/8), multiplied by sqrt(-1) when needed; no root -> false;
--     x = 0 with sign bit 1 -> false;
--   * S (the last 32 bytes, little endian) must be < L (the group order), which also removes S-malleability;
--   * k = SHA-512(R || A || M) read little endian, reduced mod L (built-in sha512(bytea), PostgreSQL 11+);
--   * the COFACTORLESS check [S]B = R + [k]A, compared in projective form (no inversion needed).
--
-- HOW. All arithmetic is numeric (arbitrary precision). The field is p = 2^255 - 19, d = -121665/121666, the group
-- order L = 2^252 + 27742317777372353535851937790883648493, the base point B has y = 4/5 and an even x. Points are
-- extended homogeneous coordinates (X,Y,Z,T) held in a numeric[4]; the unified addition formula of ed25519.py is used
-- for both addition and doubling; scalar multiplication is double-and-add over the bits of the scalar; the modular
-- exponentiation helper (square and multiply) serves the field inverse (x^(p-2)) and the square root. numeric mod()
-- keeps the sign of the dividend, so every subtraction is shifted by +p before reducing.
--
-- HELPERS (all in change_ledger, all internal, none granted): ed25519_le_to_numeric, ed25519_modpow,
-- ed25519_recover_x, ed25519_decompress, ed25519_point_add, ed25519_point_mul, ed25519_point_equal.
--
-- PRIVILEGES. The function is an INTERNAL building block: this migration grants EXECUTE to no role. The wiring block
-- (last) applies the schema convention of 011: SECURITY DEFINER with search_path = pg_catalog, pg_temp, owner
-- ledger_owner, EXECUTE revoked from PUBLIC. A later migration that needs a runtime role to call it adds its own grant.
-- Every helper schema-qualifies its callees, so the hardened search_path cannot change what they resolve.
--
-- TEST. tests/phase2/test_ed25519_sql.py extracts the text between the first dollar-quote tag of the EXECUTE statement
-- and its closing tag of THIS file (the tag is spelled out only in code, never in this header), cuts it at the first line that starts with '-- ====' and contains 'wiring' (the wiring block header, which
-- must stay the LAST section and keep that header), and executes the definitions part on a BARE database
-- (CREATE SCHEMA change_ledger only). The wiring needs ledger_owner, so it is not part of the bare test.
BEGIN;
DO $mig$
BEGIN
IF living.record_migration('014', ARRAY['001','002','003','004','005','006','007','008','009','010','011','012','013']) THEN
EXECUTE $body$

-- ================================================================== helpers
-- little-endian bytea -> numeric (non-negative integer)
CREATE OR REPLACE FUNCTION change_ledger.ed25519_le_to_numeric(p_b bytea) RETURNS numeric
LANGUAGE plpgsql IMMUTABLE STRICT AS $fn$
DECLARE acc numeric := 0; i int;
BEGIN
 FOR i IN REVERSE pg_catalog.length(p_b)-1 .. 0 LOOP
  acc := acc*256 + pg_catalog.get_byte(p_b, i);
 END LOOP;
 RETURN acc;
END $fn$;

-- (base ^ exp) mod m by square and multiply; exp >= 0, m > 1, base >= 0
CREATE OR REPLACE FUNCTION change_ledger.ed25519_modpow(p_base numeric, p_exp numeric, p_mod numeric) RETURNS numeric
LANGUAGE plpgsql IMMUTABLE STRICT AS $fn$
DECLARE r numeric := 1; b numeric := pg_catalog.mod(p_base, p_mod); e numeric := p_exp;
BEGIN
 WHILE e > 0 LOOP
  IF pg_catalog.mod(e, 2) = 1 THEN r := pg_catalog.mod(r*b, p_mod); END IF;
  b := pg_catalog.mod(b*b, p_mod);
  e := pg_catalog.div(e, 2);
 END LOOP;
 RETURN r;
END $fn$;

-- RFC 8032 5.1.3 recovery of x from y and the sign bit; NULL when no valid x exists (or y is not canonical)
CREATE OR REPLACE FUNCTION change_ledger.ed25519_recover_x(p_y numeric, p_sign int) RETURNS numeric
LANGUAGE plpgsql IMMUTABLE STRICT AS $fn$
DECLARE
 p numeric := 57896044618658097711785492504343953926634992332820282019728792003956564819949;
 d numeric := 37095705934669439343138083508754565189542113879843219016388785533085940283555;
 sqrt_m1 numeric := 19681161376707505956807079304988542015446066515923890162744021073123829784752;
 x2 numeric; x numeric;
BEGIN
 IF p_y >= p THEN RETURN NULL; END IF;
 x2 := pg_catalog.mod((p_y*p_y - 1 + p) * change_ledger.ed25519_modpow(pg_catalog.mod(d*p_y*p_y + 1, p), p-2, p), p);
 IF x2 = 0 THEN
  IF p_sign = 1 THEN RETURN NULL; END IF;
  RETURN 0;
 END IF;
 x := change_ledger.ed25519_modpow(x2, pg_catalog.div(p+3, 8), p);
 IF pg_catalog.mod(x*x - x2, p) <> 0 THEN x := pg_catalog.mod(x*sqrt_m1, p); END IF;
 IF pg_catalog.mod(x*x - x2, p) <> 0 THEN RETURN NULL; END IF;
 IF pg_catalog.mod(x, 2) <> p_sign THEN x := p - x; END IF;
 RETURN x;
END $fn$;

-- 32-byte compressed point -> extended coordinates {X,Y,Z,T}; NULL when it does not decode
CREATE OR REPLACE FUNCTION change_ledger.ed25519_decompress(p_b bytea) RETURNS numeric[]
LANGUAGE plpgsql IMMUTABLE STRICT AS $fn$
DECLARE
 p numeric := 57896044618658097711785492504343953926634992332820282019728792003956564819949;
 top numeric := 57896044618658097711785492504343953926634992332820282019728792003956564819968; -- 2^255
 y numeric; sgn int; x numeric;
BEGIN
 IF pg_catalog.length(p_b) <> 32 THEN RETURN NULL; END IF;
 y := change_ledger.ed25519_le_to_numeric(p_b);
 sgn := 0;
 IF y >= top THEN sgn := 1; y := y - top; END IF;
 x := change_ledger.ed25519_recover_x(y, sgn);
 IF x IS NULL THEN RETURN NULL; END IF;
 RETURN ARRAY[x, y, 1::numeric, pg_catalog.mod(x*y, p)];
END $fn$;

-- unified extended-coordinates addition (also used for doubling), same formula as ed25519.py _add
CREATE OR REPLACE FUNCTION change_ledger.ed25519_point_add(p_p numeric[], p_q numeric[]) RETURNS numeric[]
LANGUAGE plpgsql IMMUTABLE STRICT AS $fn$
DECLARE
 p numeric := 57896044618658097711785492504343953926634992332820282019728792003956564819949;
 d numeric := 37095705934669439343138083508754565189542113879843219016388785533085940283555;
 a numeric; b numeric; c numeric; dd numeric; e numeric; f numeric; g numeric; h numeric;
BEGIN
 a := pg_catalog.mod((p_p[2] - p_p[1] + p) * (p_q[2] - p_q[1] + p), p);
 b := pg_catalog.mod((p_p[2] + p_p[1]) * (p_q[2] + p_q[1]), p);
 c := pg_catalog.mod(2 * p_p[4] * p_q[4] * d, p);
 dd := pg_catalog.mod(2 * p_p[3] * p_q[3], p);
 e := b - a + p; f := dd - c + p; g := dd + c; h := b + a;
 RETURN ARRAY[pg_catalog.mod(e*f, p), pg_catalog.mod(g*h, p), pg_catalog.mod(f*g, p), pg_catalog.mod(e*h, p)];
END $fn$;

-- scalar multiplication by double-and-add (least significant bit first), s >= 0
CREATE OR REPLACE FUNCTION change_ledger.ed25519_point_mul(p_s numeric, p_p numeric[]) RETURNS numeric[]
LANGUAGE plpgsql IMMUTABLE STRICT AS $fn$
DECLARE q numeric[] := ARRAY[0::numeric, 1::numeric, 1::numeric, 0::numeric]; pt numeric[] := p_p; s numeric := p_s;
BEGIN
 WHILE s > 0 LOOP
  IF pg_catalog.mod(s, 2) = 1 THEN q := change_ledger.ed25519_point_add(q, pt); END IF;
  s := pg_catalog.div(s, 2);
  IF s > 0 THEN pt := change_ledger.ed25519_point_add(pt, pt); END IF;
 END LOOP;
 RETURN q;
END $fn$;

-- projective equality: X1*Z2 = X2*Z1 and Y1*Z2 = Y2*Z1 (mod p)
CREATE OR REPLACE FUNCTION change_ledger.ed25519_point_equal(p_p numeric[], p_q numeric[]) RETURNS boolean
LANGUAGE plpgsql IMMUTABLE STRICT AS $fn$
DECLARE p numeric := 57896044618658097711785492504343953926634992332820282019728792003956564819949;
BEGIN
 IF pg_catalog.mod(p_p[1]*p_q[3] - p_q[1]*p_p[3], p) <> 0 THEN RETURN false; END IF;
 RETURN pg_catalog.mod(p_p[2]*p_q[3] - p_q[2]*p_p[3], p) = 0;
END $fn$;

-- ================================================================== the verifier
CREATE OR REPLACE FUNCTION change_ledger.ed25519_verify(p_public_key bytea, p_message bytea, p_signature bytea)
RETURNS boolean LANGUAGE plpgsql IMMUTABLE AS $fn$
DECLARE
 l numeric := 7237005577332262213973186563042994240857116359379907606001950938285454250989;
 base_y numeric := 46316835694926478169428394003475163141307993866256225615783033603165251855960;
 base_x numeric := 15112221349535400772501151409588531511454012693041857206046113283949847762202;
 p numeric := 57896044618658097711785492504343953926634992332820282019728792003956564819949;
 a_point numeric[]; r_point numeric[]; base numeric[]; r_bytes bytea; s numeric; k numeric;
BEGIN
 IF p_public_key IS NULL OR p_message IS NULL OR p_signature IS NULL THEN RETURN false; END IF;
 IF pg_catalog.length(p_public_key) <> 32 OR pg_catalog.length(p_signature) <> 64 THEN RETURN false; END IF;
 a_point := change_ledger.ed25519_decompress(p_public_key);
 IF a_point IS NULL THEN RETURN false; END IF;
 r_bytes := pg_catalog.substr(p_signature, 1, 32);
 r_point := change_ledger.ed25519_decompress(r_bytes);
 IF r_point IS NULL THEN RETURN false; END IF;
 s := change_ledger.ed25519_le_to_numeric(pg_catalog.substr(p_signature, 33, 32));
 IF s >= l THEN RETURN false; END IF;
 k := pg_catalog.mod(change_ledger.ed25519_le_to_numeric(pg_catalog.sha512(r_bytes || p_public_key || p_message)), l);
 base := ARRAY[base_x, base_y, 1::numeric, pg_catalog.mod(base_x*base_y, p)];
 RETURN change_ledger.ed25519_point_equal(
  change_ledger.ed25519_point_mul(s, base),
  change_ledger.ed25519_point_add(r_point, change_ledger.ed25519_point_mul(k, a_point)));
END $fn$;

-- ================================================================== wiring, ownership, privileges (keep last)
DO $fn$
DECLARE f record;
BEGIN
 FOR f IN SELECT p.oid::regprocedure AS sig FROM pg_catalog.pg_proc p
   JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='change_ledger' LOOP
  EXECUTE format('ALTER FUNCTION %s SECURITY DEFINER SET search_path = pg_catalog, pg_temp',f.sig);
  EXECUTE format('ALTER FUNCTION %s OWNER TO ledger_owner',f.sig);
 END LOOP;
END $fn$;
REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA change_ledger FROM PUBLIC;

-- no GRANT: ed25519_verify is an internal building block (a later migration adds a grant if a runtime role needs it)

$body$;
END IF;
END $mig$;
COMMIT;
