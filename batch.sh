#!/bin/bash
set -euo pipefail

API_URL=${API_URL:-http://127.0.0.1:7070}
GRAPH=${GRAPH:-lineage_graph}
DB_USER=${DB_USER:-admin}
PASS=${PASS:-73@TuGraph}

SINGLE_TIMES=${SINGLE_TIMES:-100}
CONCURRENT_THREADS=${CONCURRENT_THREADS:-20}
CONCURRENT_TOTAL=${CONCURRENT_TOTAL:-1000}
BATCH_TIMES=${BATCH_TIMES:-10}
BATCH_SIZE=${BATCH_SIZE:-100}
QUERY_TIMES=${QUERY_TIMES:-100}

REPORT_FILE=${REPORT_FILE:-perf_report.txt}
RUN_ID=$(date +%s)
RUN_KEY=$(date '+%Y%m%d_%H%M%S')_$$
EXECUTION_FILE=${EXECUTION_FILE:-${REPORT_FILE%.*}_cypher_executions.csv}
QUERY_SUFFIX=""
TOKEN=""

now_ms() {
  python3 -c 'import time; print(time.time_ns() // 1000000)'
}

make_suffix() {
  local sequence="$1"
  printf '%s%06d' "${RUN_ID}" "${sequence}"
}

login() {
  local payload
  payload=$(jq -n --arg user "${DB_USER}" --arg password "${PASS}" \
    '{user: $user, password: $password}')

  TOKEN=$(curl -fsS -X POST "${API_URL}/login" \
    -H 'Content-Type: application/json' \
    --data-binary "${payload}" | jq -er '.jwt')
}

run_cypher() {
  local cypher="$1"
  local payload response metadata body http_code seconds cypher_cost_ms http_cost_ms

  payload=$(jq -n --arg graph "${GRAPH}" --arg script "${cypher}" \
    '{graph: $graph, script: $script}')

  response=$(curl -sS -w $'\n%{http_code},%{time_total}' \
    -X POST "${API_URL}/cypher" \
    -H 'Content-Type: application/json' \
    -H "Authorization: Bearer ${TOKEN}" \
    --data-binary "${payload}")

  metadata=${response##*$'\n'}
  body=${response%$'\n'*}
  http_code=${metadata%%,*}
  seconds=${metadata#*,}
  http_cost_ms=$(awk -v seconds="${seconds}" 'BEGIN { printf "%.3f", seconds * 1000 }')

  if [ "${http_code}" -ge 200 ] && [ "${http_code}" -lt 300 ]; then
    cypher_cost_ms=$(printf '%s' "${body}" | jq -er '.elapsed * 1000')
    printf '%.3f %.3f' "${cypher_cost_ms}" "${http_cost_ms}"
    return 0
  fi

  printf '0 %.3f' "${http_cost_ms}"
  printf 'Cypher failed (HTTP %s): %s\n' "${http_code}" "${body}" >&2
  return 1
}

timed_cypher() {
  local case_name="$1"
  local sequence="$2"
  local units="$3"
  local cypher="$4"
  local started_at timing cypher_cost_ms http_cost_ms status cypher_csv

  started_at=$(date '+%Y-%m-%d %H:%M:%S')
  status=success
  if ! timing=$(run_cypher "${cypher}"); then
    status=failure
  fi
  read -r cypher_cost_ms http_cost_ms <<< "${timing}"

  cypher_csv=$(jq -rn --arg cypher "${cypher}" \
    '$cypher | gsub("\\r"; "") | gsub("\\n"; "\\n") | gsub("\""; "\"\"")')
  printf '%s,%s,%s,%s,%s,%s,%s,%s,"%s"\n' \
    "${RUN_KEY}" "${started_at}" "${case_name}" "${sequence}" \
    "${units}" "${cypher_cost_ms}" "${http_cost_ms}" "${status}" \
    "${cypher_csv}" >> "${EXECUTION_FILE}"

  [ "${status}" = success ]
}

record_case() {
  local name="$1"
  local total="$2"
  local start="$3"
  local end="$4"
  local detail_case="$5"

  local cost=$((end - start))
  local qps=0
  local cypher_stats cypher_count cypher_total cypher_avg cypher_min cypher_max

  if [ "$cost" -gt 0 ]; then
    qps=$((total * 1000 / cost))
  fi

  cypher_stats=$(awk -F',' -v run_id="${RUN_KEY}" -v case_name="${detail_case}" '
    $1 == run_id && $3 == case_name && $8 == "success" {
      count++
      total += $6
      if (count == 1 || $6 < min) min = $6
      if (count == 1 || $6 > max) max = $6
    }
    END {
      avg = count ? total / count : 0
      printf "%d %.3f %.3f %.3f %.3f", count, total, avg, min, max
    }
  ' "${EXECUTION_FILE}")
  read -r cypher_count cypher_total cypher_avg cypher_min cypher_max <<< "${cypher_stats}"

  {
    echo "[$name]"
    echo "total=${total}"
    echo "wall_cost_ms=${cost}"
    echo "qps=${qps}"
    echo "cypher_statement_count=${cypher_count}"
    echo "cypher_total_cost_ms=${cypher_total}"
    echo "cypher_avg_cost_ms=${cypher_avg}"
    echo "cypher_min_cost_ms=${cypher_min}"
    echo "cypher_max_cost_ms=${cypher_max}"
    echo
  } >> "${REPORT_FILE}"
}

single_report_cypher() {
  local s="$1"
  local alias=${2:-}
  local ts
  ts=$(now_ms)

  cat <<EOF
CREATE (inDs${alias}:dataset {
  gid: ${s}001,
  id: "ds_in_${s}",
  namespace: "perf",
  name: "table_in_${s}",
  current_version: "dv_in_${s}",
  created_at: ${ts},
  updated_at: ${ts},
  owner: "perf_user"
})
CREATE (inDv${alias}:datasetversion {
  gid: ${s}002,
  id: "dv_in_${s}",
  dataset_uuid: "ds_in_${s}",
  facets: "{}",
  created_at: ${ts},
  owner: "perf_user"
})
CREATE (outDs${alias}:dataset {
  gid: ${s}003,
  id: "ds_out_${s}",
  namespace: "perf",
  name: "table_out_${s}",
  current_version: "dv_out_${s}",
  created_at: ${ts},
  updated_at: ${ts},
  owner: "perf_user"
})
CREATE (outDv${alias}:datasetversion {
  gid: ${s}004,
  id: "dv_out_${s}",
  dataset_uuid: "ds_out_${s}",
  facets: "{}",
  created_at: ${ts},
  owner: "perf_user"
})
CREATE (job${alias}:job {
  gid: ${s}005,
  id: "job_${s}",
  namespace: "perf",
  name: "job_${s}",
  current_version: "jv_${s}",
  current_run: "run_${s}",
  created_at: ${ts},
  updated_at: ${ts},
  owner: "perf_user"
})
CREATE (jv${alias}:jobversion {
  gid: ${s}006,
  id: "jv_${s}",
  job_uuid: "job_${s}",
  facets: "{}",
  owner: "perf_user"
})
CREATE (run${alias}:jobrun {
  gid: ${s}007,
  id: "run_${s}",
  state: "SUCCESS",
  namespace: "perf",
  facets: "{}",
  created_at: ${ts},
  updated_at: ${ts},
  owner: "perf_user",
  jobversion_id: "jv_${s}"
})
CREATE (inDs${alias})-[:has_dversion {created_at: ${ts}}]->(inDv${alias})
CREATE (outDs${alias})-[:has_dversion {created_at: ${ts}}]->(outDv${alias})
CREATE (job${alias})-[:has_jversion {created_at: ${ts}}]->(jv${alias})
CREATE (jv${alias})-[:has_run {created_at: ${ts}}]->(run${alias})
CREATE (inDv${alias})-[:consumes_by {created_at: ${ts}}]->(run${alias})
CREATE (run${alias})-[:produces {created_at: ${ts}}]->(outDv${alias})
CREATE (inDs${alias})-[:lineage]->(job${alias})
CREATE (job${alias})-[:lineage]->(outDs${alias})
RETURN run${alias}.id;
EOF
}

batch_report_cypher() {
  local batch="$1"
  local cypher=""
  for i in $(seq 1 "${BATCH_SIZE}"); do
    local s report
    s=$(make_suffix "$((batch + i))")
    report=$(single_report_cypher "$s" "_${i}")
    cypher="${cypher}
$(printf '%s\n' "${report}" | sed '$d')
"
  done

  printf '%s\nRETURN %d AS created;\n' "$cypher" "${BATCH_SIZE}"
}

query_dataset_neighbor() {
  local name="$1"
  local hop="$2"
  local pattern=""

  for i in $(seq 1 "${hop}"); do
    pattern="${pattern}-[:lineage]->(j${i}:job)-[:lineage]->(n${i}:dataset)"
  done

  cat <<EOF
MATCH p = (d:dataset {name: "${name}"})${pattern}
RETURN ${hop} AS hop, n${hop}.id AS target_id, n${hop}.name AS target_name
LIMIT 100;
EOF
}

query_dataset_dataset_path() {
  local src="$1"
  local dst="$2"
  local hop="$3"

  cat <<EOF
MATCH p = (src:dataset {name: "${src}"})-[:lineage*1..${hop}]->(dst:dataset {name: "${dst}"})
RETURN length(p) AS hop, src.id AS src_id, dst.id AS dst_id, nodes(p) AS path_nodes, relationships(p) AS path_edges
ORDER BY hop
LIMIT 1;
EOF
}

query_dataset_job_path() {
  local dataset="$1"
  local job="$2"
  local hop="$3"

  cat <<EOF
MATCH p = (d:dataset {name: "${dataset}"})-[:lineage*1..${hop}]->(j:job {name: "${job}"})
RETURN length(p) AS hop, d.id AS dataset_id, j.id AS job_id, nodes(p) AS path_nodes, relationships(p) AS path_edges
ORDER BY hop
LIMIT 1;
EOF
}

run_single_report_test() {
  echo "Running single report test..."
  local start end s

  start=$(now_ms)
  for i in $(seq 1 "${SINGLE_TIMES}"); do
    s=$(make_suffix "${i}")
    if [ -z "${QUERY_SUFFIX}" ]; then
      QUERY_SUFFIX="${s}"
    fi
    timed_cypher "single_report" "${i}" 1 "$(single_report_cypher "$s")"
  done
  end=$(now_ms)

  record_case "single_report" "${SINGLE_TIMES}" "$start" "$end" "single_report"
}

run_concurrent_report_test() {
  echo "Running concurrent report test..."

  local per_thread=$((CONCURRENT_TOTAL / CONCURRENT_THREADS))
  local start end

  start=$(now_ms)

  for t in $(seq 1 "${CONCURRENT_THREADS}"); do
    (
      for i in $(seq 1 "${per_thread}"); do
        s=$(make_suffix "$((100000 + (t - 1) * per_thread + i))")
        timed_cypher "concurrent_report" "$(( (t - 1) * per_thread + i ))" 1 \
          "$(single_report_cypher "$s")"
      done
    ) &
  done

  wait
  end=$(now_ms)

  record_case "concurrent_${CONCURRENT_THREADS}_report" \
    "$((per_thread * CONCURRENT_THREADS))" "$start" "$end" "concurrent_report"
}

run_batch_report_test() {
  echo "Running batch report test..."

  local start end s

  start=$(now_ms)
  for i in $(seq 1 "${BATCH_TIMES}"); do
    s=$((200000 + (i - 1) * BATCH_SIZE))
    timed_cypher "batch_report" "${i}" "${BATCH_SIZE}" "$(batch_report_cypher "$s")"
  done
  end=$(now_ms)

  record_case "batch_${BATCH_SIZE}_report" "$((BATCH_TIMES * BATCH_SIZE))" \
    "$start" "$end" "batch_report"
}

run_neighbor_query_test() {
  echo "Running dataset neighbor query test..."

  local start end total=0

  for hop in 1 2 3 4 5; do
    start=$(now_ms)

    for i in $(seq 1 "${QUERY_TIMES}"); do
      timed_cypher "dataset_neighbor_${hop}_hop" "${i}" 1 \
        "$(query_dataset_neighbor "table_in_${QUERY_SUFFIX}" "${hop}")"
      total=$((total + 1))
    done

    end=$(now_ms)
    record_case "dataset_neighbor_${hop}_hop" "${QUERY_TIMES}" "$start" "$end" \
      "dataset_neighbor_${hop}_hop"
  done
}

run_dataset_dataset_path_test() {
  echo "Running dataset->dataset path test..."

  local start end

  for hop in 1 2 3 4 5; do
    start=$(now_ms)

    for i in $(seq 1 "${QUERY_TIMES}"); do
      timed_cypher "dataset_dataset_path_${hop}_hop" "${i}" 1 \
        "$(query_dataset_dataset_path "table_in_${QUERY_SUFFIX}" "table_out_${QUERY_SUFFIX}" "${hop}")"
    done

    end=$(now_ms)
    record_case "dataset_dataset_path_${hop}_hop" "${QUERY_TIMES}" "$start" "$end" \
      "dataset_dataset_path_${hop}_hop"
  done
}

run_dataset_job_path_test() {
  echo "Running dataset->job path test..."

  local start end

  for hop in 1 2 3 4 5; do
    start=$(now_ms)

    for i in $(seq 1 "${QUERY_TIMES}"); do
      timed_cypher "dataset_job_path_${hop}_hop" "${i}" 1 \
        "$(query_dataset_job_path "table_in_${QUERY_SUFFIX}" "job_${QUERY_SUFFIX}" "${hop}")"
    done

    end=$(now_ms)
    record_case "dataset_job_path_${hop}_hop" "${QUERY_TIMES}" "$start" "$end" \
      "dataset_job_path_${hop}_hop"
  done
}

main() {
  local script_start script_end script_cost run_cypher_stats

  command -v curl >/dev/null
  command -v jq >/dev/null
  command -v python3 >/dev/null
  login

  script_start=$(now_ms)

  if [ ! -f "${EXECUTION_FILE}" ]; then
    echo "run_id,start_time,case,sequence,units,cypher_cost_ms,http_cost_ms,status,cypher_statement" > "${EXECUTION_FILE}"
  fi

  {
    echo "============================================================"
    echo "TuGraph Perf Test Report"
    echo "run_id=${RUN_KEY}"
    echo "graph=${GRAPH}"
    echo "start_time=$(date '+%Y-%m-%d %H:%M:%S')"
    echo
  } >> "${REPORT_FILE}"

  run_single_report_test
  run_concurrent_report_test
  run_batch_report_test

  run_neighbor_query_test
  run_dataset_dataset_path_test
  run_dataset_job_path_test

  script_end=$(now_ms)
  script_cost=$((script_end - script_start))
  run_cypher_stats=$(awk -F',' -v run_id="${RUN_KEY}" '
    $1 == run_id && $8 == "success" { count++; total += $6 }
    END { printf "%d %.3f %.3f", count, total, (count ? total / count : 0) }
  ' "${EXECUTION_FILE}")
  {
    echo "[run_summary]"
    echo "total_cost_ms=${script_cost}"
    read -r count total avg <<< "${run_cypher_stats}"
    echo "cypher_statement_count=${count}"
    echo "cypher_total_cost_ms=${total}"
    echo "cypher_avg_cost_ms=${avg}"
    echo "execution_detail=${EXECUTION_FILE}"
    echo "end_time=$(date '+%Y-%m-%d %H:%M:%S')"
    echo
  } >> "${REPORT_FILE}"

  echo "Done. Report: ${REPORT_FILE}"
  echo "Execution detail: ${EXECUTION_FILE}"
  sed -n "/run_id=${RUN_KEY}/,\$p" "${REPORT_FILE}"
}

main "$@"
