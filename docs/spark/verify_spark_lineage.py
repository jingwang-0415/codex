from pathlib import Path
from tempfile import mkdtemp
from uuid import uuid4

from pyspark.sql import SparkSession


def main():
    lab_root = Path(mkdtemp(prefix="spark-lineage-lab-")).resolve()
    lab_id = uuid4().hex[:12]
    database = f"lineage_lab_{lab_id}"
    view_name = f"lineage_view_{lab_id}"

    spark = (
        SparkSession.builder
        .master("local[2]")
        .appName("spark-lineage-boundary-lab")
        .config("spark.sql.warehouse.dir", (lab_root / "warehouse").as_uri())
        .config("spark.sql.catalogImplementation", "in-memory")
        .getOrCreate()
    )

    try:
        # 独立的新进程运行本示例，避免复用其他程序已有的 Session 配置。
        spark.sql(f"CREATE DATABASE {database}")

        # A、B、C 均为保存数据的普通 Parquet 表。
        spark.sql(f"""
            CREATE TABLE {database}.a USING parquet AS
            SELECT * FROM VALUES
                (1, 80), (2, 150), (3, 200)
            AS t(id, amount)
        """)
        spark.sql(f"""
            CREATE TABLE {database}.b USING parquet AS
            SELECT id, amount FROM {database}.a WHERE amount >= 100
        """)
        spark.sql(f"""
            CREATE TABLE {database}.c USING parquet AS
            SELECT id, amount * 2 AS doubled_amount FROM {database}.b
        """)

        print("\n[1] 重新读取落地表 B：关注 Analyzed Logical Plan 中的表关系")
        spark.sql(f"SELECT * FROM {database}.b").explain(mode="extended")

        print("\n[2] 重新读取落地表 C：不会自动把历史 CTAS 全部接进计划")
        spark.sql(f"SELECT * FROM {database}.c").explain(mode="extended")

        spark.sql(f"""
            CREATE TEMP VIEW {view_name} AS
            SELECT id, amount FROM {database}.a WHERE amount >= 100
        """)

        print("\n[3] 查询临时视图：观察视图定义内部的 A 与过滤条件")
        spark.sql(f"SELECT * FROM {view_name}").explain(mode="extended")

        print("\n[4] 连续 DataFrame 变换：观察当前定义中的 A 与过滤条件")
        df = spark.table(f"{database}.a").select("id", "amount")
        df.filter("amount >= 100").explain(mode="extended")

        actual = [
            (row.id, row.doubled_amount)
            for row in spark.sql(
                f"SELECT id, doubled_amount FROM {database}.c ORDER BY id"
            ).collect()
        ]
        assert actual == [(2, 300), (3, 400)], actual
        print("\n数据校验通过：", actual)
    finally:
        spark.stop()

    print("实验临时目录保留在：", lab_root)


if __name__ == "__main__":
    main()