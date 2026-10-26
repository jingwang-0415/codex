"""Teaching example: extract lineage from real Spark 3.5.6 Catalyst objects.

Supports this demo's V1 non-partitioned Parquet writes and
Project / Filter / SubqueryAlias / View / LogicalRelation nodes only.
Raises for unsupported nodes; this is not a general production collector.
"""

import argparse
import json
import platform
from pathlib import Path
from tempfile import mkdtemp
from uuid import uuid4

from pyspark.sql import SparkSession


def scala_seq(seq):
    return [seq.apply(i) for i in range(seq.size())]


def expr_id(attribute):
    # Keep the JVM UUID too: the numeric part alone is not a global identity.
    return str(attribute.exprId())


def dataset_name(catalog_table):
    ident = catalog_table.identifier()
    if not ident.database().isDefined():
        raise ValueError("Expected a qualified table in this demo")
    return f"spark_catalog.{ident.database().get()}.{ident.table()}"


def extract_lineage(analyzed, run_id):
    root_type = analyzed.getClass().getSimpleName()
    is_write = root_type == "InsertIntoHadoopFsRelationCommand"
    if is_write:
        if not analyzed.catalogTable().isDefined():
            raise ValueError("Path-only writes are outside this demo's scope")
        if analyzed.partitionColumns().size() or analyzed.staticPartitions().size():
            raise ValueError("Partitioned writes are outside this demo's scope")
        target = dataset_name(analyzed.catalogTable().get())
        target_fields = list(analyzed.catalogTable().get().schema().fieldNames())
        query = analyzed.query()
    else:
        target, target_fields, query = None, [], analyzed

    origins = {}
    dependencies = {}
    filters = []
    aliases = []
    inputs = set()

    def walk(node):
        kind = node.getClass().getSimpleName()
        if kind == "LogicalRelation":
            if not node.catalogTable().isDefined():
                raise ValueError("Expected a named V1 table")
            source = dataset_name(node.catalogTable().get())
            inputs.add(source)
            for attr in scala_seq(node.output()):
                origins[expr_id(attr)] = (source, str(attr.name()))
            return
        if kind not in {"Project", "Filter", "SubqueryAlias", "View"}:
            raise ValueError(f"Unsupported plan node: {kind}")
        for child in scala_seq(node.children()):
            walk(child)
        if kind == "Project":
            for expression in scala_seq(node.projectList()):
                output_id = expr_id(expression.toAttribute())
                refs = {
                    expr_id(attr)
                    for attr in scala_seq(expression.references().toSeq())
                }
                # Bare attributes retain their ID. Do not add a self-loop.
                if refs != {output_id}:
                    dependencies.setdefault(output_id, set()).update(refs)
                if expression.getClass().getSimpleName() == "Alias":
                    aliases.append({
                        "output": str(expression.name()),
                        "exprId": output_id,
                        "references": sorted(refs),
                        "expression": str(expression.sql()),
                    })
        elif kind == "Filter":
            filters.append({
                "expression": str(node.condition().sql()),
                "references": [
                    expr_id(attr)
                    for attr in scala_seq(node.condition().references().toSeq())
                ],
            })

    walk(query)

    def resolve(current_id, seen=None):
        seen = set() if seen is None else seen
        if current_id in seen:
            raise ValueError(f"Expression dependency cycle: {current_id}")
        if current_id in origins:
            return {origins[current_id]}
        if current_id not in dependencies:
            raise ValueError(f"Unresolved expression: {current_id}")
        result = set()
        for parent in dependencies[current_id]:
            result.update(resolve(parent, seen | {current_id}))
        return result

    def field_records(source_fields):
        return [
            {"dataset": dataset, "field": field}
            for dataset, field in sorted(source_fields)
        ]

    row_influences = set()
    for predicate in filters:
        for reference in predicate["references"]:
            row_influences.update(resolve(reference))

    output_columns = scala_seq(query.output())
    columns = {}
    if is_write:
        # This restricted INSERT INTO example writes the complete target schema
        # in positional order. Do not generalize this to all INSERT variants.
        if len(output_columns) != len(target_fields):
            raise ValueError("Target/query column count mismatch")
        for target_field, output_attr in zip(target_fields, output_columns):
            columns[str(target_field)] = {
                "inputFields": field_records(resolve(expr_id(output_attr))),
                "rowInfluences": field_records(row_influences),
            }

    return {
        "runId": run_id,
        "status": "COMPLETE",
        "inputs": sorted(inputs),
        "output": target,
        "tableEdges": [
            {"from": source, "to": target}
            for source in sorted(inputs) if is_write
        ],
        "columnLineage": columns,
        "trace": {
            "inputAttributes": {
                key: {"dataset": value[0], "field": value[1]}
                for key, value in sorted(origins.items())
            },
            "aliases": aliases,
            "filters": filters,
        },
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    warehouse = Path(mkdtemp(prefix="spark-lineage-demo-", dir="/tmp"))
    database = f"lineage_generation_lab_{uuid4().hex[:10]}"
    spark = (
        SparkSession.builder.master("local[2]")
        .appName("generate-lineage-from-catalyst")
        .config("spark.sql.warehouse.dir", warehouse.as_uri())
        .config("spark.sql.catalogImplementation", "in-memory")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("ERROR")
    try:
        if spark.version != "3.5.6":
            raise ValueError(f"This demo is pinned to Spark 3.5.6, got {spark.version}")
        spark.sql(f"CREATE DATABASE {database}")
        spark.sql(f"""CREATE TABLE {database}.a USING parquet AS
            SELECT * FROM VALUES (1, 10, 2, 'paid'), (2, 5, 3, 'unpaid'),
            (3, 7, 4, 'paid') AS t(id, price, quantity, status)""")
        spark.sql(f"CREATE TABLE {database}.b (biz_id INT, amount INT) USING parquet")
        spark.sql(f"CREATE TABLE {database}.c (customer_key INT, final_amount INT) USING parquet")
        spark.sql(f"CREATE TABLE {database}.d (biz_id INT, amount INT) USING parquet")
        runs = []

        def run(sql, label):
            result = spark.sql(sql)
            # Wait for success before recording COMPLETE. SELECT also needs an action.
            result.collect()
            analyzed = result._jdf.queryExecution().analyzed()
            (args.output_dir / f"{label}-analyzed-plan.txt").write_text(
                str(analyzed.treeString()), encoding="utf-8"
            )
            event = extract_lineage(analyzed, label)
            (args.output_dir / f"{label}-lineage.json").write_text(
                json.dumps(event, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            runs.append(event)
            return event

        r1 = run(f"""INSERT INTO {database}.b
            SELECT id AS biz_id, price * quantity AS amount
            FROM {database}.a WHERE status = 'paid'""", "R1")
        r2 = run(f"""INSERT INTO {database}.c
            SELECT biz_id, amount * 2 FROM {database}.b""", "R2")
        read_a = run(f"SELECT id FROM {database}.a", "read-a")
        read_b = run(f"SELECT biz_id FROM {database}.b", "read-b")

        view = f"lineage_v_{uuid4().hex[:8]}"
        spark.sql(f"""CREATE TEMP VIEW {view} AS
            SELECT id AS biz_id, price * quantity AS amount
            FROM {database}.a WHERE status = 'paid'""")
        view_write = run(f"INSERT INTO {database}.d SELECT * FROM {view}", "view-write")

        name = lambda table: f"spark_catalog.{database}.{table}"
        assert r1["tableEdges"] == [{"from": name("a"), "to": name("b")}]
        assert r2["tableEdges"] == [{"from": name("b"), "to": name("c")}]
        assert r2["inputs"] == [name("b")], "R2 must start from materialized B"
        assert r1["columnLineage"]["biz_id"]["inputFields"] == [
            {"dataset": name("a"), "field": "id"}
        ], "Alias names must resolve to the original source field"
        assert r1["columnLineage"]["amount"]["inputFields"] == [
            {"dataset": name("a"), "field": "price"},
            {"dataset": name("a"), "field": "quantity"},
        ], "Both operands must be tracked"
        assert r1["columnLineage"]["amount"]["rowInfluences"] == [
            {"dataset": name("a"), "field": "status"}
        ], "Filtering must be distinguished from value derivation"
        assert read_a["tableEdges"] == read_b["tableEdges"] == []
        assert view_write["tableEdges"] == [{"from": name("a"), "to": name("d")}]
        assert [(r.customer_key, r.final_amount) for r in
                spark.sql(f"SELECT * FROM {database}.c ORDER BY customer_key").collect()
                ] == [(1, 40), (3, 56)]

        table_edges = sorted({(e["from"], e["to"])
                              for r in (r1, r2) for e in r["tableEdges"]})
        assert table_edges == [(name("a"), name("b")), (name("b"), name("c"))]
        # Second-level composition uses persistent (dataset, field) identities,
        # not ExprId values from another query.
        upstream_fields = set()
        for field in r2["columnLineage"]["final_amount"]["inputFields"]:
            assert field["dataset"] == name("b")
            for upstream in r1["columnLineage"][field["field"]]["inputFields"]:
                upstream_fields.add((upstream["dataset"], upstream["field"]))
        assert upstream_fields == {(name("a"), "price"), (name("a"), "quantity")}

        summary = {
            "sparkVersion": spark.version,
            "pythonVersion": platform.python_version(),
            "javaVersion": spark._jvm.java.lang.System.getProperty("java.version"),
            "database": database,
            "checks": {
                "table_edges_from_write_plans": True,
                "renamed_column_resolves_to_source": True,
                "expression_has_two_inputs": True,
                "filter_is_separate_row_influence": True,
                "independent_reads_create_no_table_edge": True,
                "second_write_starts_at_materialized_b": True,
                "temp_view_expands_to_a": True,
                "composed_table_and_column_edges": True,
                "output_data_correct": True,
            },
            "tableEdges": [{"from": a, "to": b} for a, b in table_edges],
            "composedValueSourcesForCFinalAmount": [
                {"dataset": dataset, "field": field}
                for dataset, field in sorted(upstream_fields)
            ],
        }
        (args.output_dir / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
