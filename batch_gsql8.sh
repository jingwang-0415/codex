#!/bin/bash
set -euo pipefail

GSQL_BIN=${GSQL_BIN:-gsql}
GSQL_ARGS=${GSQL_ARGS:--d postgres -p 7999 -r}
PROGRESS=${PROGRESS:-1}
GRAPH_PATH=${GRAPH_PATH:-test_dl3kw}

SINGLE_TIMES=${SINGLE_TIMES:-100}
CONCURRENT_THREADS=${CONCURRENT_THREADS:-20}
CONCURRENT_DURATION_SECONDS=${CONCURRENT_DURATION_SECONDS:-10}
CONCURRENT_BATCH_SIZE=${CONCURRENT_BATCH_SIZE:-100}
BATCH_TIMES=${BATCH_TIMES:-10}
BATCH_SIZE=${BATCH_SIZE:-100}
QUERY_TIMES=${QUERY_TIMES:-100}
QUERY_MAX_HOP=${QUERY_MAX_HOP:-10}
QUERY_LIMITS=${QUERY_LIMITS:-"1 10 100"}
QUERY_LIMIT_SKIP_SECONDS=${QUERY_LIMIT_SKIP_SECONDS:-60}
QUERY_UNLIMITED_MAX_HOP=${QUERY_UNLIMITED_MAX_HOP:-7}
QUERY_SAMPLE_SIZE=${QUERY_SAMPLE_SIZE:-1000}

REPORT_FILE=${REPORT_FILE:-perf_report.txt}
LOG_FILE=${LOG_FILE:-${REPORT_FILE%.*}.log}
RUN_ID=$(date +%s)
RUN_KEY=$(date '+%Y%m%d_%H%M%S')_$$
EXECUTION_FILE=${EXECUTION_FILE:-${REPORT_FILE%.*}_cypher_executions.csv}
EXECUTION_HEADER="run_id,start_time,phase,case,sequence,units,db_elapsed_ms,gsql_total_ms,client_overhead_ms,status,cypher_statement"
EXECUTION_LOCK_DIR=""
EXPORT_XLSX=${EXPORT_XLSX:-1}
XLSX_FILE=${XLSX_FILE:-${EXECUTION_FILE%.*}.xlsx}
NODE_BIN=${NODE_BIN:-/Users/a747/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node}
ARTIFACT_TOOL_NODE_MODULES=${ARTIFACT_TOOL_NODE_MODULES:-/Users/a747/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules}
DATASET_GIDS=()
JOB_GIDS=()

now_ms() {
  python3 -c 'import time; print(time.time_ns() // 1000000)'
}

make_suffix() {
  local sequence="$1"
  printf '%s%06d' "${RUN_ID}" "${sequence}"
}

check_gsql_bin() {
  local output gsql_args=()

  if [ -n "${GSQL_ARGS}" ]; then
    # Split simple command-line args such as: -d postgres -p 7999 -r
    read -r -a gsql_args <<< "${GSQL_ARGS}"
  fi

  if ! output=$("${GSQL_BIN}" "${gsql_args[@]}" --help 2>&1); then
    printf 'Failed to run gsql command: %s %s\n' "${GSQL_BIN}" "${GSQL_ARGS}" >&2
    printf '%s\n' "${output}" >&2
    return 127
  fi
}

run_gsql_file_to_output() {
  local script_file="$1"
  local output_file="$2"
  local max_time="${3:-}"
  local gsql_args=() timeout_bin status

  if [ -n "${GSQL_ARGS}" ]; then
    read -r -a gsql_args <<< "${GSQL_ARGS}"
  fi

  timeout_bin=$(timeout_command)
  if [ -n "${max_time}" ] && [ -n "${timeout_bin}" ]; then
    "${timeout_bin}" "${max_time}" "${GSQL_BIN}" "${gsql_args[@]}" -f "${script_file}" \
      > >(tee -a "${LOG_FILE}" > "${output_file}") 2>&1
    status=$?
  else
    "${GSQL_BIN}" "${gsql_args[@]}" -f "${script_file}" \
      > >(tee -a "${LOG_FILE}" > "${output_file}") 2>&1
    status=$?
  fi

  return "${status}"
}

require_command() {
  local command_name="$1"

  if ! command -v "${command_name}" >/dev/null; then
    printf 'Cannot find required command: %s\n' "${command_name}" >&2
    return 127
  fi
}

timeout_command() {
  if command -v timeout >/dev/null 2>&1; then
    printf 'timeout'
  elif command -v gtimeout >/dev/null 2>&1; then
    printf 'gtimeout'
  fi
}

build_gsql_command() {
  local cypher="$1"

  printf 'set graph_path=%s; %s' "${GRAPH_PATH}" "${cypher}"
}

execute_gsql() {
  local cypher="$1"
  local max_time="${2:-}"
  local gsql_command output_file script_file status

  output_file=$(mktemp "${TMPDIR:-/tmp}/batch_gsql8.out.XXXXXX")
  gsql_command=$(build_gsql_command "${cypher}")
  script_file=$(mktemp "${TMPDIR:-/tmp}/batch_gsql8.sql.XXXXXX")
  printf '%s\n' "${gsql_command}" > "${script_file}"

  set +e
  run_gsql_file_to_output "${script_file}" "${output_file}" "${max_time}"
  status=$?
  set -e

  cat "${output_file}"
  rm -f "${script_file}" "${output_file}"
  return "${status}"
}

run_cypher() {
  local cypher="$1"
  local max_time="${2:-}"
  local start end gsql_total_ms output output_file script_file gsql_command status
  local gsql_args=() timeout_bin

  output_file=$(mktemp "${TMPDIR:-/tmp}/batch_gsql8.out.XXXXXX")
  script_file=$(mktemp "${TMPDIR:-/tmp}/batch_gsql8.sql.XXXXXX")
  gsql_command=$(build_gsql_command "${cypher}")
  printf '%s\n' "${gsql_command}" > "${script_file}"
  if [ -n "${GSQL_ARGS}" ]; then
    read -r -a gsql_args <<< "${GSQL_ARGS}"
  fi
  timeout_bin=$(timeout_command)

  status=0
  set +e
  start=$(now_ms)
  if [ -n "${max_time}" ] && [ -n "${timeout_bin}" ]; then
    "${timeout_bin}" "${max_time}" "${GSQL_BIN}" "${gsql_args[@]}" -f "${script_file}" \
      > >(tee -a "${LOG_FILE}" > "${output_file}") 2>&1
    status=$?
  else
    "${GSQL_BIN}" "${gsql_args[@]}" -f "${script_file}" \
      > >(tee -a "${LOG_FILE}" > "${output_file}") 2>&1
    status=$?
  fi
  end=$(now_ms)
  set -e

  gsql_total_ms=$(awk -v cost="$((end - start))" 'BEGIN { printf "%.3f", cost }')
  output=$(cat "${output_file}")
  rm -f "${script_file}" "${output_file}"

  if [ "${status}" -ne 0 ]; then
    printf '0 %.3f 0' "${gsql_total_ms}"
    printf 'Cypher failed through gsql8. Output:\n%s\n' "${output}" >&2
    return 1
  fi

  printf '%.3f %.3f 0' "${gsql_total_ms}" "${gsql_total_ms}"
}

phase_for_case() {
  local case_name="$1"

  case "${case_name}" in
    single_report)
      printf 'write_single_report'
      ;;
    concurrent_single_report)
      printf 'write_concurrent_single_report'
      ;;
    concurrent_batch_report)
      printf 'write_concurrent_batch_report'
      ;;
    batch_report)
      printf 'write_batch_report'
      ;;
    dataset_neighbor_*)
      printf 'query_dataset_neighbor'
      ;;
    dataset_dataset_path_*)
      printf 'query_dataset_dataset_path'
      ;;
    dataset_job_path_*)
      printf 'query_dataset_job_path'
      ;;
    *)
      printf 'unknown'
      ;;
  esac
}

append_execution_row() {
  local row="$1"

  while ! mkdir "${EXECUTION_LOCK_DIR}" 2>/dev/null; do
    sleep 0.01
  done
  printf '%s\n' "${row}" >> "${EXECUTION_FILE}"
  rmdir "${EXECUTION_LOCK_DIR}"
}

progress_log() {
  local line

  if [ "${PROGRESS}" != "1" ]; then
    return 0
  fi

  line=$(printf '[%s] %s' "$(date '+%Y-%m-%d %H:%M:%S')" "$*")
  printf '%s\n' "${line}" >&2
  printf '%s\n' "${line}" >> "${LOG_FILE}"
}

timed_cypher() {
  local case_name="$1"
  local sequence="$2"
  local units="$3"
  local cypher="$4"
  local max_time="${5:-}"
  local started_at phase timing db_elapsed_ms gsql_total_ms client_overhead_ms status cypher_csv

  started_at=$(date '+%Y-%m-%d %H:%M:%S')
  phase=$(phase_for_case "${case_name}")
  status=success
  progress_log "START phase=${phase} case=${case_name} sequence=${sequence} units=${units}"
  if ! timing=$(run_cypher "${cypher}" "${max_time}"); then
    status=failure
  fi
  read -r db_elapsed_ms gsql_total_ms client_overhead_ms <<< "${timing}"
  progress_log "END phase=${phase} case=${case_name} sequence=${sequence} status=${status} elapsed_ms=${gsql_total_ms}"

  cypher_csv=$(printf '%s' "${cypher}" | jq -Rs \
    'gsub("\\r"; "") | gsub("\\n"; "\\n") | gsub("\""; "\"\"")')
  append_execution_row "$(printf '%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,"%s"' \
    "${RUN_KEY}" "${started_at}" "${phase}" "${case_name}" "${sequence}" \
    "${units}" "${db_elapsed_ms}" "${gsql_total_ms}" "${client_overhead_ms}" "${status}" \
    "${cypher_csv}")"

  [ "${status}" = success ]
}

record_case() {
  local name="$1"
  local planned_total="$2"
  local start="$3"
  local end="$4"
  local detail_case="$5"

  local cost=$((end - start))
  local qps=0
  local cypher_stats cypher_count unit_total cypher_total cypher_avg cypher_min cypher_max

  cypher_stats=$(awk -F',' -v run_id="${RUN_KEY}" -v case_name="${detail_case}" '
    $1 == run_id && $4 == case_name && $10 == "success" {
      count++
      units += $6
      total += $7
      if (count == 1 || $7 < min) min = $7
      if (count == 1 || $7 > max) max = $7
    }
    END {
      avg = count ? total / count : 0
      printf "%d %d %.3f %.3f %.3f %.3f", count, units, total, avg, min, max
    }
  ' "${EXECUTION_FILE}")
  read -r cypher_count unit_total cypher_total cypher_avg cypher_min cypher_max <<< "${cypher_stats}"

  if [ "$cost" -gt 0 ]; then
    qps=$((unit_total * 1000 / cost))
  fi

  {
    echo "[$name]"
    echo "planned_total=${planned_total}"
    echo "total=${unit_total}"
    echo "wall_cost_ms=${cost}"
    echo "qps=${qps}"
    echo "cypher_statement_count=${cypher_count}"
    echo "db_elapsed_total_ms=${cypher_total}"
    echo "db_elapsed_avg_ms=${cypher_avg}"
    echo "db_elapsed_min_ms=${cypher_min}"
    echo "db_elapsed_max_ms=${cypher_max}"
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
  local batch_size="${2:-${BATCH_SIZE}}"
  local cypher=""
  for i in $(seq 1 "${batch_size}"); do
    local s report
    s=$(make_suffix "$((batch + i))")
    report=$(single_report_cypher "$s" "_${i}")
    cypher="${cypher}
$(printf '%s\n' "${report}" | sed '$d')
"
  done

  printf '%s\nRETURN %d AS created;\n' "$cypher" "${batch_size}"
}

cypher_string_literal() {
  jq -Rn --arg value "$1" '$value'
}

run_cypher_body() {
  local cypher="$1"

  execute_gsql "${cypher}"
}

load_query_samples() {
  local dataset_body job_body

  echo "Loading random query sample pools..."
  dataset_body=$(run_cypher_body "MATCH (d:dataset) WHERE d.gid IS NOT NULL RETURN d.gid LIMIT ${QUERY_SAMPLE_SIZE};")
  job_body=$(run_cypher_body "MATCH (j:job) WHERE j.gid IS NOT NULL RETURN j.gid LIMIT ${QUERY_SAMPLE_SIZE};")

  DATASET_GIDS=()
  while IFS= read -r gid; do
    [ -n "${gid}" ] && DATASET_GIDS+=("${gid}")
  done < <(printf '%s\n' "${dataset_body}" | awk '/^-?[0-9]+$/ { print; next } /\|/ { for (i = 1; i <= NF; i++) if ($i ~ /^-?[0-9]+$/) print $i }' | head -n "${QUERY_SAMPLE_SIZE}")

  JOB_GIDS=()
  while IFS= read -r gid; do
    [ -n "${gid}" ] && JOB_GIDS+=("${gid}")
  done < <(printf '%s\n' "${job_body}" | awk '/^-?[0-9]+$/ { print; next } /\|/ { for (i = 1; i <= NF; i++) if ($i ~ /^-?[0-9]+$/) print $i }' | head -n "${QUERY_SAMPLE_SIZE}")

  if [ "${#DATASET_GIDS[@]}" -eq 0 ] || [ "${#JOB_GIDS[@]}" -eq 0 ]; then
    printf 'Failed to load query samples: dataset_count=%d job_count=%d\n' \
      "${#DATASET_GIDS[@]}" "${#JOB_GIDS[@]}" >&2
    return 1
  fi

  printf 'Loaded query samples: dataset_count=%d job_count=%d\n' \
    "${#DATASET_GIDS[@]}" "${#JOB_GIDS[@]}"
}

random_dataset_gid() {
  printf '%s' "${DATASET_GIDS[$((RANDOM % ${#DATASET_GIDS[@]}))]}"
}

random_job_gid() {
  printf '%s' "${JOB_GIDS[$((RANDOM % ${#JOB_GIDS[@]}))]}"
}

query_dataset_neighbor() {
  local gid="$1"
  local hop="$2"
  local limit="$3"
  local limit_clause=""
  local pattern=""

  if [ "${limit}" != "all" ]; then
    limit_clause="LIMIT ${limit};"
  fi

  for i in $(seq 1 "${hop}"); do
    pattern="${pattern}-[:lineage]->(j${i}:job)-[:lineage]->(n${i}:dataset)"
  done

  cat <<EOF
MATCH p = (d:dataset {gid: ${gid}})${pattern}
RETURN ${hop} AS hop, d.gid AS source_gid, n${hop}.gid AS target_gid, n${hop}.id AS target_id, n${hop}.name AS target_name
${limit_clause}
EOF
}

query_dataset_dataset_path() {
  local src_gid="$1"
  local dst_gid="$2"
  local hop="$3"
  local limit="$4"
  local limit_clause=""

  if [ "${limit}" != "all" ]; then
    limit_clause="LIMIT ${limit};"
  fi

  cat <<EOF
MATCH p = (src:dataset {gid: ${src_gid}})-[:lineage*1..${hop}]-(dst:dataset {gid: ${dst_gid}})
RETURN length(p) AS hop, src.gid AS src_gid, dst.gid AS dst_gid, src.id AS src_id, dst.id AS dst_id, nodes(p) AS path_nodes, relationships(p) AS path_edges
ORDER BY hop
${limit_clause}
EOF
}

query_dataset_job_path() {
  local dataset_gid="$1"
  local job_gid="$2"
  local hop="$3"
  local limit="$4"
  local limit_clause=""

  if [ "${limit}" != "all" ]; then
    limit_clause="LIMIT ${limit};"
  fi

  cat <<EOF
MATCH p = (d:dataset {gid: ${dataset_gid}})-[:lineage*1..${hop}]-(j:job {gid: ${job_gid}})
RETURN length(p) AS hop, d.gid AS dataset_gid, j.gid AS job_gid, d.id AS dataset_id, j.id AS job_id, nodes(p) AS path_nodes, relationships(p) AS path_edges
ORDER BY hop
${limit_clause}
EOF
}

export_execution_xlsx() {
  local script_dir export_script node_cmd

  if [ "${EXPORT_XLSX}" != "1" ]; then
    return 0
  fi

  script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
  export_script="${script_dir}/tools/export_cypher_executions_xlsx.mjs"
  node_cmd="${NODE_BIN}"
  if [ ! -x "${node_cmd}" ]; then
    node_cmd=$(command -v node || true)
  fi

  if [ -z "${node_cmd}" ] || [ ! -f "${export_script}" ]; then
    printf 'Skip xlsx export: node or export script is unavailable.\n' >&2
    return 0
  fi

  NODE_PATH="${ARTIFACT_TOOL_NODE_MODULES}" "${node_cmd}" "${export_script}" \
    "${EXECUTION_FILE}" "${XLSX_FILE}" "${RUN_KEY}"
}

run_single_report_test() {
  echo "Running single report test..."
  local start end s

  start=$(now_ms)
  for i in $(seq 1 "${SINGLE_TIMES}"); do
    s=$(make_suffix "${i}")
    timed_cypher "single_report" "${i}" 1 "$(single_report_cypher "$s")"
  done
  end=$(now_ms)

  record_case "single_report" "${SINGLE_TIMES}" "$start" "$end" "single_report"
}

run_concurrent_single_report_test() {
  echo "Running concurrent single report test..."

  local start end deadline planned_total=0

  start=$(now_ms)
  deadline=$((start + CONCURRENT_DURATION_SECONDS * 1000))

  for t in $(seq 1 "${CONCURRENT_THREADS}"); do
    (
      local i=1 sequence s
      while [ "$(now_ms)" -lt "${deadline}" ]; do
        sequence=$((100000 + (t - 1) * 5000 + i))
        s=$(make_suffix "${sequence}")
        timed_cypher "concurrent_single_report" "${sequence}" 1 \
          "$(single_report_cypher "$s")" || true
        i=$((i + 1))
      done
    ) &
  done

  wait
  end=$(now_ms)

  record_case "concurrent_${CONCURRENT_THREADS}_single_report_${CONCURRENT_DURATION_SECONDS}s" \
    "${planned_total}" "$start" "$end" "concurrent_single_report"
}

run_concurrent_batch_report_test() {
  echo "Running concurrent batch report test..."

  local start end deadline planned_total=0

  start=$(now_ms)
  deadline=$((start + CONCURRENT_DURATION_SECONDS * 1000))

  for t in $(seq 1 "${CONCURRENT_THREADS}"); do
    (
      local i=1 sequence batch_start
      while [ "$(now_ms)" -lt "${deadline}" ]; do
        sequence=$((300000 + (t - 1) * 5000 + i))
        batch_start=$((400000 + (t - 1) * 25000 + (i - 1) * CONCURRENT_BATCH_SIZE))
        timed_cypher "concurrent_batch_report" "${sequence}" "${CONCURRENT_BATCH_SIZE}" \
          "$(batch_report_cypher "${batch_start}" "${CONCURRENT_BATCH_SIZE}")" || true
        i=$((i + 1))
      done
    ) &
  done

  wait
  end=$(now_ms)

  record_case "concurrent_${CONCURRENT_THREADS}_batch_${CONCURRENT_BATCH_SIZE}_report_${CONCURRENT_DURATION_SECONDS}s" \
    "${planned_total}" "$start" "$end" "concurrent_batch_report"
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

  local start end cost total=0

  for hop in $(seq 1 "${QUERY_MAX_HOP}"); do
    local limits_for_hop="${QUERY_LIMITS}"
    if [ "${hop}" -le "${QUERY_UNLIMITED_MAX_HOP}" ]; then
      limits_for_hop="${limits_for_hop} all"
    fi

    for limit in ${limits_for_hop}; do
      start=$(now_ms)
      local limit_timed_out=0

      for i in $(seq 1 "${QUERY_TIMES}"); do
        local dataset_gid
        dataset_gid=$(random_dataset_gid)
        timed_cypher "dataset_neighbor_${hop}_hop_limit_${limit}" "${i}" 1 \
          "$(query_dataset_neighbor "${dataset_gid}" "${hop}" "${limit}")" \
          "${QUERY_LIMIT_SKIP_SECONDS}" || true
        total=$((total + 1))
        cost=$(($(now_ms) - start))
        if [ "${cost}" -gt "$((QUERY_LIMIT_SKIP_SECONDS * 1000))" ]; then
          limit_timed_out=1
          echo "Stop dataset_neighbor ${hop} hop limit ${limit}: partial cost ${cost}ms exceeded ${QUERY_LIMIT_SKIP_SECONDS}s"
          break
        fi
      done

      end=$(now_ms)
      cost=$((end - start))
      record_case "dataset_neighbor_${hop}_hop_limit_${limit}" "${QUERY_TIMES}" "$start" "$end" \
        "dataset_neighbor_${hop}_hop_limit_${limit}"
      if [ "${limit_timed_out}" -eq 1 ] || [ "${cost}" -gt "$((QUERY_LIMIT_SKIP_SECONDS * 1000))" ]; then
        echo "Skip remaining dataset_neighbor limits for ${hop} hop: limit ${limit} cost ${cost}ms exceeded ${QUERY_LIMIT_SKIP_SECONDS}s"
        break
      fi
    done
  done
}

run_dataset_dataset_path_test() {
  echo "Running dataset->dataset path test..."

  local start end cost

  for hop in $(seq 1 "${QUERY_MAX_HOP}"); do
    local limits_for_hop="${QUERY_LIMITS}"
    if [ "${hop}" -le "${QUERY_UNLIMITED_MAX_HOP}" ]; then
      limits_for_hop="${limits_for_hop} all"
    fi

    for limit in ${limits_for_hop}; do
      start=$(now_ms)
      local limit_timed_out=0

      for i in $(seq 1 "${QUERY_TIMES}"); do
        local src_gid dst_gid
        src_gid=$(random_dataset_gid)
        dst_gid=$(random_dataset_gid)
        timed_cypher "dataset_dataset_path_${hop}_hop_limit_${limit}" "${i}" 1 \
          "$(query_dataset_dataset_path "${src_gid}" "${dst_gid}" "${hop}" "${limit}")" \
          "${QUERY_LIMIT_SKIP_SECONDS}" || true
        cost=$(($(now_ms) - start))
        if [ "${cost}" -gt "$((QUERY_LIMIT_SKIP_SECONDS * 1000))" ]; then
          limit_timed_out=1
          echo "Stop dataset_dataset_path ${hop} hop limit ${limit}: partial cost ${cost}ms exceeded ${QUERY_LIMIT_SKIP_SECONDS}s"
          break
        fi
      done

      end=$(now_ms)
      cost=$((end - start))
      record_case "dataset_dataset_path_${hop}_hop_limit_${limit}" "${QUERY_TIMES}" "$start" "$end" \
        "dataset_dataset_path_${hop}_hop_limit_${limit}"
      if [ "${limit_timed_out}" -eq 1 ] || [ "${cost}" -gt "$((QUERY_LIMIT_SKIP_SECONDS * 1000))" ]; then
        echo "Skip remaining dataset_dataset_path limits for ${hop} hop: limit ${limit} cost ${cost}ms exceeded ${QUERY_LIMIT_SKIP_SECONDS}s"
        break
      fi
    done
  done
}

run_dataset_job_path_test() {
  echo "Running dataset->job path test..."

  local start end cost

  for hop in $(seq 1 "${QUERY_MAX_HOP}"); do
    local limits_for_hop="${QUERY_LIMITS}"
    if [ "${hop}" -le "${QUERY_UNLIMITED_MAX_HOP}" ]; then
      limits_for_hop="${limits_for_hop} all"
    fi

    for limit in ${limits_for_hop}; do
      start=$(now_ms)
      local limit_timed_out=0

      for i in $(seq 1 "${QUERY_TIMES}"); do
        local dataset_gid job_gid
        dataset_gid=$(random_dataset_gid)
        job_gid=$(random_job_gid)
        timed_cypher "dataset_job_path_${hop}_hop_limit_${limit}" "${i}" 1 \
          "$(query_dataset_job_path "${dataset_gid}" "${job_gid}" "${hop}" "${limit}")" \
          "${QUERY_LIMIT_SKIP_SECONDS}" || true
        cost=$(($(now_ms) - start))
        if [ "${cost}" -gt "$((QUERY_LIMIT_SKIP_SECONDS * 1000))" ]; then
          limit_timed_out=1
          echo "Stop dataset_job_path ${hop} hop limit ${limit}: partial cost ${cost}ms exceeded ${QUERY_LIMIT_SKIP_SECONDS}s"
          break
        fi
      done

      end=$(now_ms)
      cost=$((end - start))
      record_case "dataset_job_path_${hop}_hop_limit_${limit}" "${QUERY_TIMES}" "$start" "$end" \
        "dataset_job_path_${hop}_hop_limit_${limit}"
      if [ "${limit_timed_out}" -eq 1 ] || [ "${cost}" -gt "$((QUERY_LIMIT_SKIP_SECONDS * 1000))" ]; then
        echo "Skip remaining dataset_job_path limits for ${hop} hop: limit ${limit} cost ${cost}ms exceeded ${QUERY_LIMIT_SKIP_SECONDS}s"
        break
      fi
    done
  done
}

main() {
  local script_start script_end script_cost run_cypher_stats

  require_command jq
  require_command python3
  check_gsql_bin

  : >> "${LOG_FILE}"
  progress_log "RUN_START run_id=${RUN_KEY} report=${REPORT_FILE} log=${LOG_FILE}"
  script_start=$(now_ms)

  if [ ! -f "${EXECUTION_FILE}" ]; then
    echo "${EXECUTION_HEADER}" > "${EXECUTION_FILE}"
  elif [ "$(head -n 1 "${EXECUTION_FILE}")" != "${EXECUTION_HEADER}" ]; then
    EXECUTION_FILE="${EXECUTION_FILE%.*}_${RUN_KEY}.csv"
    echo "${EXECUTION_HEADER}" > "${EXECUTION_FILE}"
  fi
  EXECUTION_LOCK_DIR="${EXECUTION_FILE}.lock"
  rmdir "${EXECUTION_LOCK_DIR}" 2>/dev/null || true

  {
    echo "============================================================"
    echo "TuGraph Perf Test Report (gsql8)"
    echo "run_id=${RUN_KEY}"
    echo "log_file=${LOG_FILE}"
    echo "gsql_bin=${GSQL_BIN}"
    echo "gsql_args=${GSQL_ARGS}"
    echo "progress=${PROGRESS}"
    echo "graph_path=${GRAPH_PATH}"
    echo "query_limits=${QUERY_LIMITS}"
    echo "query_limit_skip_seconds=${QUERY_LIMIT_SKIP_SECONDS}"
    echo "query_unlimited_max_hop=${QUERY_UNLIMITED_MAX_HOP}"
    echo "start_time=$(date '+%Y-%m-%d %H:%M:%S')"
    echo
  } >> "${REPORT_FILE}"

  run_single_report_test
  run_concurrent_single_report_test
  run_concurrent_batch_report_test
  run_batch_report_test

  load_query_samples
  run_neighbor_query_test
  run_dataset_dataset_path_test
  run_dataset_job_path_test

  script_end=$(now_ms)
  script_cost=$((script_end - script_start))
  run_cypher_stats=$(awk -F',' -v run_id="${RUN_KEY}" '
    $1 == run_id && $10 == "success" { count++; total += $7 }
    END { printf "%d %.3f %.3f", count, total, (count ? total / count : 0) }
  ' "${EXECUTION_FILE}")
  {
    echo "[run_summary]"
    echo "total_cost_ms=${script_cost}"
    read -r count total avg <<< "${run_cypher_stats}"
    echo "cypher_statement_count=${count}"
    echo "db_elapsed_total_ms=${total}"
    echo "db_elapsed_avg_ms=${avg}"
    echo "execution_detail=${EXECUTION_FILE}"
    echo "execution_workbook=${XLSX_FILE}"
    echo "end_time=$(date '+%Y-%m-%d %H:%M:%S')"
    echo
  } >> "${REPORT_FILE}"

  export_execution_xlsx

  progress_log "RUN_END run_id=${RUN_KEY} total_cost_ms=${script_cost} report=${REPORT_FILE}"
  echo "Done. Report: ${REPORT_FILE}"
  echo "Log: ${LOG_FILE}"
  echo "Execution detail: ${EXECUTION_FILE}"
  if [ "${EXPORT_XLSX}" = "1" ]; then
    echo "Execution workbook: ${XLSX_FILE}"
  fi
  sed -n "/run_id=${RUN_KEY}/,\$p" "${REPORT_FILE}"
}

main "$@"
