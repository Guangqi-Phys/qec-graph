#!/usr/bin/env python3
"""Small, inspectable QEC knowledge-base example. Python 3.11+.

Uses only the standard library unless --json-schema is requested.
Finite enumeration is deliberately limited to n <= 20. No Lean claims are made.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "derived" / "index.sqlite"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path):
    def unique_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate JSON key: {key} in {path}")
            result[key] = value
        return result
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_keys)


def local_path(value: str) -> Path:
    path = (ROOT / value).resolve()
    if not path.is_relative_to(ROOT):
        raise ValueError(f"Asset path escapes repository: {value}")
    return path


def load_records(full_schema: bool = False) -> dict:
    records = {}
    schema = read_json(ROOT / "schemas" / "record.schema.json")
    validator = None
    matrix_validator = None
    if full_schema:
        try:
            from jsonschema import Draft202012Validator
        except ImportError as exc:
            raise RuntimeError("--json-schema requires the optional jsonschema package") from exc
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema)
        matrix_schema = read_json(ROOT / "schemas" / "matrix.schema.json")
        Draft202012Validator.check_schema(matrix_schema)
        matrix_validator = Draft202012Validator(matrix_schema)
    required = {"schema_version", "id", "kind", "title", "review_status", "refs", "assets", "data"}
    for path in sorted((ROOT / "records").rglob("*.json")):
        record = read_json(path)
        if required - record.keys():
            raise ValueError(f"Missing fields: {path}")
        if record["schema_version"] != "0.1.0":
            raise ValueError(f"Unsupported schema: {path}")
        if record["id"] in records:
            raise ValueError(f"Duplicate entity ID: {record['id']}")
        if validator:
            validator.validate(record)
        for asset in record["assets"]:
            asset_path = local_path(asset["path"])
            if digest(asset_path) != asset["sha256"]:
                raise ValueError(f"Asset checksum mismatch: {asset['path']}")
            if "canonical_sha256" in asset:
                value = read_json(asset_path)
                encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
                if hashlib.sha256(encoded).hexdigest() != asset["canonical_sha256"]:
                    raise ValueError(f"Canonical checksum mismatch: {asset['path']}")
                if matrix_validator:
                    matrix_validator.validate(value)
        records[record["id"]] = record
    for record in records.values():
        for ref in record["refs"]:
            if ref["target_id"] not in records:
                raise ValueError(f"Broken reference in {record['id']}: {ref}")
    visiting, finished = set(), set()

    def check_dag(entity_id):
        if entity_id in visiting:
            raise ValueError(f"Cycle in depends_on edges at {entity_id}")
        if entity_id in finished:
            return
        visiting.add(entity_id)
        for ref in records[entity_id]["refs"]:
            if ref["relation"] == "depends_on":
                check_dag(ref["target_id"])
        visiting.remove(entity_id)
        finished.add(entity_id)

    for entity_id in records:
        check_dag(entity_id)
    return records


def matrix(path: Path) -> list[list[int]]:
    value = read_json(path)
    if (value["field"], value["format"], value["index_base"]) != ("GF(2)", "coordinate-ones-v1", 0):
        raise ValueError("Unexpected matrix convention")
    m, n = value["shape"]
    if type(m) is not int or type(n) is not int or m < 0 or n < 0:
        raise ValueError("Invalid matrix shape")
    coords = value["ones"]
    if coords != sorted(coords) or len({tuple(x) for x in coords}) != len(coords):
        raise ValueError("Coordinates must be sorted, with no duplicates")
    result = [[0] * n for _ in range(m)]
    for i, j in coords:
        if type(i) is not int or type(j) is not int or not (0 <= i < m and 0 <= j < n):
            raise ValueError("Invalid coordinate")
        result[i][j] = 1
    return result


def transpose(a):
    return [list(column) for column in zip(*a)]


def identity(n):
    return [[int(i == j) for j in range(n)] for i in range(n)]


def kron(a, b):
    return [[a[i][j] * b[k][l] for j in range(len(a[0])) for l in range(len(b[0]))]
            for i in range(len(a)) for k in range(len(b))]


def hcat(a, b):
    if len(a) != len(b):
        raise ValueError("Block row mismatch")
    return [x + y for x, y in zip(a, b)]


def row_bits(a):
    return [sum(value << i for i, value in enumerate(row)) for row in a]


def rank_gf2(rows):
    pivots = {}
    for row in rows:
        while row:
            pivot = row.bit_length() - 1
            if pivot not in pivots:
                pivots[pivot] = row
                break
            row ^= pivots[pivot]
    return len(pivots)


def row_space(rows):
    space = {0}
    for row in rows:
        space |= {value ^ row for value in space}
    return space


def parity(a, b):
    return (a & b).bit_count() & 1


def logical_minimum(n, opposite_checks, same_stabilizers):
    if n > 20:
        raise ValueError("Demo exhaustive enumeration only supports n <= 20")
    trivial = row_space(same_stabilizers)
    candidates = [v for v in range(1, 1 << n)
                  if v not in trivial and all(parity(v, row) == 0 for row in opposite_checks)]
    if not candidates:
        return None, None
    witness = min(candidates, key=lambda v: (v.bit_count(), v))
    return witness.bit_count(), [i for i in range(n) if witness >> i & 1]


def verify_demo(records):
    presentation = records["check_matrix:rep3-hgp:standard"]["data"]
    mats = {key: matrix(local_path(path)) for key, path in presentation["matrices"].items()}
    h1, h2 = mats["H1"], mats["H2"]
    m1, n1, m2, n2 = len(h1), len(h1[0]), len(h2), len(h2[0])
    hx = hcat(kron(h1, identity(n2)), kron(identity(m1), transpose(h2)))
    hz = hcat(kron(identity(n1), h2), kron(transpose(h1), identity(m2)))
    if hx != mats["HX"] or hz != mats["HZ"]:
        raise ValueError("Stored matrices disagree with the ordinary HGP construction")
    xr, zr = row_bits(hx), row_bits(hz)
    if any(parity(x, z) for x in xr for z in zr):
        raise ValueError("CSS commutation failed")
    n = len(hx[0])
    rank_x, rank_z = rank_gf2(xr), rank_gf2(zr)
    dx, wx = logical_minimum(n, zr, xr)
    dz, wz = logical_minimum(n, xr, zr)
    lx, lz = row_bits(mats["LX"]), row_bits(mats["LZ"])
    if len(lx) != 1 or len(lz) != 1 or len(mats["LX"][0]) != n or len(mats["LZ"][0]) != n:
        raise ValueError("Demo expects one full-length logical pair")
    if any(parity(lx[0], z) for z in zr) or any(parity(lz[0], x) for x in xr):
        raise ValueError("Logical operators fail syndrome check")
    if parity(lx[0], lz[0]) != 1 or lx[0] in row_space(xr) or lz[0] in row_space(zr):
        raise ValueError("Logical pair fails independence/pairing check")
    result = {
        "instance_id": "quantum_code:rep3-hgp:13", "n": n, "k": n - rank_x - rank_z,
        "rank_HX_gf2": rank_x, "rank_HZ_gf2": rank_z,
        "HX_HZ_transpose_zero": True, "dX": dx, "dZ": dz,
        "X_distance_witness_support": wx, "Z_distance_witness_support": wz,
        "HX_row_weights": [sum(row) for row in hx], "HZ_row_weights": [sum(row) for row in hz],
        "logical_pairing_identity": True, "vectors_in_search_space": 1 << n,
        "method": "exhaustive_binary_enumeration", "formalization_status": "not_started"
    }
    parameters = records["quantum_code:rep3-hgp:13"]["data"]["parameters"]
    claim = records["claim:rep3-hgp:distance"]["data"]
    if (parameters["n"], parameters["k"]) != (result["n"], result["k"]):
        raise ValueError("Stored code parameters disagree with computation")
    if claim["lower_bound"] != min(dx, dz) or claim["upper_bound"] != min(dx, dz):
        raise ValueError("Stored distance bounds disagree with exhaustive computation")
    if claim["verification_level"] != "computed_exact":
        raise ValueError("Demo must not be described as Lean verified")
    recorded = read_json(ROOT / "evidence" / "demo_validation.json")
    if result != recorded["results"]:
        raise ValueError("Archived evidence report differs from current recomputation")
    return result


def fingerprint():
    paths = set((ROOT / "records").rglob("*.json"))
    paths |= set((ROOT / "assets").rglob("*.json"))
    paths |= set((ROOT / "schemas").rglob("*.json"))
    paths |= set((ROOT / "evidence").rglob("*.json"))
    paths.add(Path(__file__))
    entries = [(str(p.relative_to(ROOT)), digest(p)) for p in sorted(paths)]
    return hashlib.sha256(json.dumps(entries, separators=(",", ":")).encode()).hexdigest()


def build_index(records):
    verify_demo(records)
    DB.parent.mkdir(parents=True, exist_ok=True)
    temporary = DB.with_suffix(".new.sqlite")
    if temporary.exists():
        temporary.unlink()
    con = sqlite3.connect(temporary)
    try:
        con.execute("PRAGMA foreign_keys = ON")
        con.executescript("""
            CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE entities (id TEXT PRIMARY KEY, kind TEXT NOT NULL,
                title TEXT NOT NULL, review_status TEXT NOT NULL, payload TEXT NOT NULL);
            CREATE TABLE edges (source_id TEXT NOT NULL REFERENCES entities(id),
                relation TEXT NOT NULL, target_id TEXT NOT NULL REFERENCES entities(id));
            CREATE VIRTUAL TABLE entity_fts USING fts5(id UNINDEXED, title, search_text);
            CREATE TABLE code_parameters (id TEXT PRIMARY KEY REFERENCES entities(id),
                construction_family TEXT NOT NULL, n INTEGER NOT NULL, k INTEGER NOT NULL,
                d_lower INTEGER, d_upper INTEGER, verification_level TEXT,
                evidence_id TEXT NOT NULL REFERENCES entities(id));
        """)
        for entity in records.values():
            payload = json.dumps(entity, ensure_ascii=False)
            con.execute("INSERT INTO entities VALUES (?, ?, ?, ?, ?)",
                        (entity["id"], entity["kind"], entity["title"], entity["review_status"], payload))
            con.execute("INSERT INTO entity_fts VALUES (?, ?, ?)",
                        (entity["id"], entity["title"], entity["data"].get("search_text", payload)))
        for entity in records.values():
            con.executemany("INSERT INTO edges VALUES (?, ?, ?)",
                            [(entity["id"], x["relation"], x["target_id"]) for x in entity["refs"]])
        code = records["quantum_code:rep3-hgp:13"]["data"]
        claim = records["claim:rep3-hgp:distance"]["data"]
        construction = records[code["construction_id"]]["data"]
        con.execute("INSERT INTO code_parameters VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    ("quantum_code:rep3-hgp:13", construction["construction_kind"], code["parameters"]["n"],
                     code["parameters"]["k"], claim["lower_bound"], claim["upper_bound"],
                     claim["verification_level"], claim["evidence_ids"][0]))
        con.execute("INSERT INTO metadata VALUES ('input_fingerprint', ?)", (fingerprint(),))
        con.commit()
    finally:
        con.close()
    temporary.replace(DB)
    return {"database": str(DB.relative_to(ROOT)), "entities": len(records),
            "input_fingerprint": fingerprint(), "note": "Rebuildable single-user demonstration index"}


def open_current_index():
    if not DB.exists():
        raise RuntimeError("Run: python tools/qec_kb.py index")
    con = sqlite3.connect(DB.as_uri() + "?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    stored = con.execute("SELECT value FROM metadata WHERE key='input_fingerprint'").fetchone()[0]
    if stored != fingerprint():
        con.close()
        raise RuntimeError("Index is stale. Run: python tools/qec_kb.py index")
    return con


def context(records, entity_id, depth):
    if entity_id not in records:
        raise ValueError(f"Unknown entity: {entity_id}")
    included, todo = {}, [(entity_id, 0)]
    while todo:
        current, level = todo.pop(0)
        if current in included:
            continue
        included[current] = records[current]
        if level < depth:
            todo.extend((ref["target_id"], level + 1) for ref in records[current]["refs"])
    return {"root_id": entity_id, "dependency_depth": depth, "input_fingerprint": fingerprint(),
            "records": list(included.values()), "note": "Bounded context bundle; not a proof."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    val = commands.add_parser("verify", help="Check references, assets and the finite HGP example")
    val.add_argument("--json-schema", action="store_true")
    commands.add_parser("index", help="Rebuild the SQLite projection")
    search = commands.add_parser("search", help="FTS5 literal phrase search")
    search.add_argument("query")
    codes = commands.add_parser("codes", help="Filter by the computed demo lower bound")
    codes.add_argument("--n-min", type=int, default=1)
    codes.add_argument("--n-max", type=int, default=1000000)
    codes.add_argument("--distance-at-least", type=int, default=1)
    codes.add_argument("--construction", default="ordinary_hgp")
    ctx = commands.add_parser("context", help="Export a linked evidence/context bundle")
    ctx.add_argument("entity_id")
    ctx.add_argument("--depth", type=int, default=2)
    args = parser.parse_args()
    if args.command in {"verify", "index", "context"}:
        records = load_records(getattr(args, "json_schema", False))
        if args.command == "verify":
            output = {"passed": True, "record_count": len(records), "results": verify_demo(records),
                      "json_schema_checked": args.json_schema, "python": platform.python_version()}
        elif args.command == "index":
            output = build_index(records)
        else:
            if not 0 <= args.depth <= 8:
                raise ValueError("depth must be between 0 and 8")
            output = context(records, args.entity_id, args.depth)
    else:
        con = open_current_index()
        try:
            if args.command == "search":
                query = '"' + args.query.replace('"', '""') + '"'
                rows = con.execute("SELECT id, title, bm25(entity_fts) AS score FROM entity_fts "
                                   "WHERE entity_fts MATCH ? ORDER BY score LIMIT 10", (query,))
            else:
                rows = con.execute("SELECT * FROM code_parameters WHERE n BETWEEN ? AND ? "
                                   "AND d_lower >= ? AND construction_family = ? ORDER BY n, id",
                                   (args.n_min, args.n_max, args.distance_at_least, args.construction))
            output = [dict(row) for row in rows]
        finally:
            con.close()
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError, KeyError, OSError, sqlite3.Error) as exc:
        raise SystemExit(f"ERROR: {exc}") from exc
