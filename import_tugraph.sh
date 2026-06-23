#!/bin/bash

set -e

# ========== 可修改参数 ==========
LGRAPH_IMPORT=${LGRAPH_IMPORT:-lgraph_import}

DATA_DIR=${1:-output}
DB_DIR=${2:-./tugraph_db}
GRAPH_NAME=${3:-lineage_graph}
USER=${4:-admin}
PASSWORD=${5:-73@TuGraph}

CONFIG_FILE=${DATA_DIR}/import.config

VERTEX_DIR=${DATA_DIR}/vertices
EDGE_DIR=${DATA_DIR}/edges

# ========== 检查文件 ==========
check_file() {
  if [ ! -f "$1" ]; then
    echo "文件不存在: $1"
    exit 1
  fi
}

check_file "${VERTEX_DIR}/Dataset.csv"
check_file "${VERTEX_DIR}/DatasetVersion.csv"
check_file "${VERTEX_DIR}/Job.csv"
check_file "${VERTEX_DIR}/JobVersion.csv"
check_file "${VERTEX_DIR}/JobRun.csv"

check_file "${EDGE_DIR}/HAS_DVERSION.csv"
check_file "${EDGE_DIR}/HAS_JVERSION.csv"
check_file "${EDGE_DIR}/HAS_RUN.csv"
check_file "${EDGE_DIR}/CONSUMES_BY.csv"
check_file "${EDGE_DIR}/PRODUCES.csv"
check_file "${EDGE_DIR}/LINEAGE.csv"

# LINEAGE.csv 同时包含 dataset -> job 和 job -> dataset 两种方向。
# TuGraph 的每个导入文件只能声明一种起止标签，因此先按真实主键拆分。
LINEAGE_DATASET_JOB=${EDGE_DIR}/LINEAGE_DATASET_JOB.csv
LINEAGE_JOB_DATASET=${EDGE_DIR}/LINEAGE_JOB_DATASET.csv

awk -F',' \
  -v dataset_file="${VERTEX_DIR}/Dataset.csv" \
  -v job_file="${VERTEX_DIR}/Job.csv" \
  -v lineage_file="${EDGE_DIR}/LINEAGE.csv" \
  -v dataset_job="${LINEAGE_DATASET_JOB}" \
  -v job_dataset="${LINEAGE_JOB_DATASET}" '
  FILENAME == dataset_file { if (FNR > 1) datasets[$2] = 1; next }
  FILENAME == job_file { if (FNR > 1) jobs[$2] = 1; next }
  FILENAME == lineage_file && FNR == 1 {
    print $0 > dataset_job
    print $0 > job_dataset
    next
  }
  datasets[$2] && jobs[$3] { print $0 > dataset_job; next }
  jobs[$2] && datasets[$3] { print $0 > job_dataset; next }
  { print "无法识别 LINEAGE 关系方向: " $0 > "/dev/stderr"; invalid = 1 }
  END { exit invalid }
' "${VERTEX_DIR}/Dataset.csv" "${VERTEX_DIR}/Job.csv" "${EDGE_DIR}/LINEAGE.csv"

# ========== 生成 import.config ==========
cat > "${CONFIG_FILE}" <<EOF
{
  "schema": [
    {
      "label": "dataset",
      "type": "VERTEX",
      "primary": "gid",
      "properties": [
        { "name": "gid", "type": "INT64" },
        { "name": "id", "type": "STRING", "index": true },
        { "name": "namespace", "type": "STRING", "optional": true },
        { "name": "name", "type": "STRING", "index": true },
        { "name": "current_version", "type": "STRING", "optional": true },
        { "name": "created_at", "type": "INT64", "optional": true },
        { "name": "updated_at", "type": "INT64", "optional": true },
        { "name": "owner", "type": "STRING", "optional": true }
      ]
    },
    {
      "label": "datasetversion",
      "type": "VERTEX",
      "primary": "gid",
      "properties": [
        { "name": "gid", "type": "INT64" },
        { "name": "id", "type": "STRING", "index": true },
        { "name": "dataset_uuid", "type": "STRING", "index": true },
        { "name": "facets", "type": "STRING", "optional": true },
        { "name": "created_at", "type": "INT64", "optional": true },
        { "name": "owner", "type": "STRING", "optional": true }
      ]
    },
    {
      "label": "job",
      "type": "VERTEX",
      "primary": "gid",
      "properties": [
        { "name": "gid", "type": "INT64" },
        { "name": "id", "type": "STRING", "index": true },
        { "name": "namespace", "type": "STRING", "optional": true },
        { "name": "name", "type": "STRING", "index": true },
        { "name": "current_version", "type": "STRING", "optional": true },
        { "name": "current_run", "type": "STRING", "optional": true },
        { "name": "created_at", "type": "INT64", "optional": true },
        { "name": "updated_at", "type": "INT64", "optional": true },
        { "name": "owner", "type": "STRING", "optional": true }
      ]
    },
    {
      "label": "jobversion",
      "type": "VERTEX",
      "primary": "gid",
      "properties": [
        { "name": "gid", "type": "INT64" },
        { "name": "id", "type": "STRING", "index": true },
        { "name": "job_uuid", "type": "STRING", "index": true },
        { "name": "facets", "type": "STRING", "optional": true },
        { "name": "owner", "type": "STRING", "optional": true }
      ]
    },
    {
      "label": "jobrun",
      "type": "VERTEX",
      "primary": "gid",
      "properties": [
        { "name": "gid", "type": "INT64" },
        { "name": "id", "type": "STRING", "index": true },
        { "name": "state", "type": "STRING", "optional": true },
        { "name": "namespace", "type": "STRING", "optional": true },
        { "name": "facets", "type": "STRING", "optional": true },
        { "name": "created_at", "type": "INT64", "optional": true },
        { "name": "updated_at", "type": "INT64", "optional": true },
        { "name": "owner", "type": "STRING", "optional": true },
        { "name": "jobversion_id", "type": "STRING", "index": true }
      ]
    },

    {
      "label": "has_dversion",
      "type": "EDGE",
      "properties": [
        { "name": "created_at", "type": "INT64", "optional": true }
      ],
      "constraints": [["dataset", "datasetversion"]]
    },
    {
      "label": "has_jversion",
      "type": "EDGE",
      "properties": [
        { "name": "created_at", "type": "INT64", "optional": true }
      ],
      "constraints": [["job", "jobversion"]]
    },
    {
      "label": "has_run",
      "type": "EDGE",
      "properties": [
        { "name": "created_at", "type": "INT64", "optional": true }
      ],
      "constraints": [["jobversion", "jobrun"]]
    },
    {
      "label": "consumes_by",
      "type": "EDGE",
      "properties": [
        { "name": "created_at", "type": "INT64", "optional": true }
      ],
      "constraints": [["datasetversion", "jobrun"]]
    },
    {
      "label": "produces",
      "type": "EDGE",
      "properties": [
        { "name": "created_at", "type": "INT64", "optional": true }
      ],
      "constraints": [["jobrun", "datasetversion"]]
    },
    {
      "label": "lineage",
      "type": "EDGE",
      "properties": [],
      "constraints": [
        ["dataset", "job"],
        ["job", "dataset"]
      ]
    }
  ],

  "files": [
    {
      "path": "${VERTEX_DIR}/Dataset.csv",
      "header": 1,
      "format": "CSV",
      "label": "dataset",
      "columns": ["SKIP", "gid", "id", "namespace", "name", "current_version", "created_at", "updated_at", "owner"]
    },
    {
      "path": "${VERTEX_DIR}/DatasetVersion.csv",
      "header": 1,
      "format": "CSV",
      "label": "datasetversion",
      "columns": ["SKIP", "gid", "id", "dataset_uuid", "facets", "created_at", "owner"]
    },
    {
      "path": "${VERTEX_DIR}/Job.csv",
      "header": 1,
      "format": "CSV",
      "label": "job",
      "columns": ["SKIP", "gid", "id", "namespace", "name", "current_version", "current_run", "created_at", "updated_at", "owner"]
    },
    {
      "path": "${VERTEX_DIR}/JobVersion.csv",
      "header": 1,
      "format": "CSV",
      "label": "jobversion",
      "columns": ["SKIP", "gid", "id", "job_uuid", "facets", "owner"]
    },
    {
      "path": "${VERTEX_DIR}/JobRun.csv",
      "header": 1,
      "format": "CSV",
      "label": "jobrun",
      "columns": ["SKIP", "gid", "id", "state", "namespace", "facets", "created_at", "updated_at", "owner", "jobversion_id"]
    },

    {
      "path": "${EDGE_DIR}/HAS_DVERSION.csv",
      "header": 1,
      "format": "CSV",
      "label": "has_dversion",
      "SRC_ID": "dataset",
      "DST_ID": "datasetversion",
      "columns": ["SKIP", "SRC_ID", "DST_ID", "created_at"]
    },
    {
      "path": "${EDGE_DIR}/HAS_JVERSION.csv",
      "header": 1,
      "format": "CSV",
      "label": "has_jversion",
      "SRC_ID": "job",
      "DST_ID": "jobversion",
      "columns": ["SKIP", "SRC_ID", "DST_ID", "created_at"]
    },
    {
      "path": "${EDGE_DIR}/HAS_RUN.csv",
      "header": 1,
      "format": "CSV",
      "label": "has_run",
      "SRC_ID": "jobversion",
      "DST_ID": "jobrun",
      "columns": ["SKIP", "SRC_ID", "DST_ID", "created_at"]
    },
    {
      "path": "${EDGE_DIR}/CONSUMES_BY.csv",
      "header": 1,
      "format": "CSV",
      "label": "consumes_by",
      "SRC_ID": "datasetversion",
      "DST_ID": "jobrun",
      "columns": ["SKIP", "SRC_ID", "DST_ID", "created_at"]
    },
    {
      "path": "${EDGE_DIR}/PRODUCES.csv",
      "header": 1,
      "format": "CSV",
      "label": "produces",
      "SRC_ID": "jobrun",
      "DST_ID": "datasetversion",
      "columns": ["SKIP", "SRC_ID", "DST_ID", "created_at"]
    },
    {
      "path": "${LINEAGE_DATASET_JOB}",
      "header": 1,
      "format": "CSV",
      "label": "lineage",
      "SRC_ID": "dataset",
      "DST_ID": "job",
      "columns": ["SKIP", "SRC_ID", "DST_ID"]
    },
    {
      "path": "${LINEAGE_JOB_DATASET}",
      "header": 1,
      "format": "CSV",
      "label": "lineage",
      "SRC_ID": "job",
      "DST_ID": "dataset",
      "columns": ["SKIP", "SRC_ID", "DST_ID"]
    }
  ]
}
EOF

echo "import.config 已生成: ${CONFIG_FILE}"

# ========== 执行导入 ==========
echo "开始导入 TuGraph..."
echo "Graph: ${GRAPH_NAME}"
echo "DB_DIR: ${DB_DIR}"
echo "DATA_DIR: ${DATA_DIR}"

${LGRAPH_IMPORT} \
  --online false \
  -c "${CONFIG_FILE}" \
  -d "${DB_DIR}" \
  -g "${GRAPH_NAME}" \
  -u "${USER}" \
  -p "${PASSWORD}" \
  --overwrite true \
  --delimiter ","

echo "TuGraph 导入完成"
