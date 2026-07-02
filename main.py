import argparse
import json
import random
import shutil
import sys
import time
from pathlib import Path
from datetime import datetime


# =========================
# CSV 输出规则
# =========================

def format_csv_value(v):
    if v is None:
        return ""

    if isinstance(v, bool):
        return str(v).lower()

    if isinstance(v, (int, float)):
        return str(v)

    s = str(v)

    if s.startswith("[") or s.startswith("{"):
        return '"' + s.replace('"', '""') + '"'

    return '"""' + s.replace('"', '""') + '"""'


class ProgressBar:
    def __init__(self, enabled=True, width=30, min_interval=1.0):
        self.enabled = enabled
        self.width = width
        self.min_interval = min_interval
        self.phase = ""
        self.start_percent = 0.0
        self.end_percent = 0.0
        self.percent = 0.0
        self.last_print = 0.0

    def set_phase(self, phase, start_percent, end_percent):
        self.phase = phase
        self.start_percent = start_percent
        self.end_percent = end_percent
        self.update(0, 1, force=True)

    def update(self, current, total, force=False):
        if not self.enabled:
            return

        now = time.monotonic()
        if not force and now - self.last_print < self.min_interval:
            return

        ratio = 1.0 if total <= 0 else min(1.0, max(0.0, current / total))
        self.percent = self.start_percent + (self.end_percent - self.start_percent) * ratio
        filled = int(self.width * self.percent / 100)
        bar = "#" * filled + "-" * (self.width - filled)
        sys.stderr.write(f"\r[{bar}] {self.percent:6.2f}% {self.phase}")
        sys.stderr.flush()
        self.last_print = now

    def finish(self):
        if not self.enabled:
            return
        self.percent = 100.0
        bar = "#" * self.width
        sys.stderr.write(f"\r[{bar}] 100.00% 完成\n")
        sys.stderr.flush()


def write_csv(path, headers, rows, progress=None, phase=None, start_percent=None, end_percent=None):
    path.parent.mkdir(parents=True, exist_ok=True)

    if progress and phase is not None:
        progress.set_phase(phase, start_percent, end_percent)

    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(",".join(headers))
        f.write("\n")

        buffer = []
        total = len(rows)
        for idx, row in enumerate(rows, 1):
            buffer.append(",".join(format_csv_value(row.get(h)) for h in headers) + "\n")
            if len(buffer) >= 10000:
                f.writelines(buffer)
                buffer.clear()
                if progress:
                    progress.update(idx, total)

        if buffer:
            f.writelines(buffer)

        if progress:
            progress.update(total, total, force=True)


def json_str(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def time_millis(base_millis, offset):
    return base_millis + offset * 1000


# =========================
# ID 生成器
# =========================

class GraphIdGenerator:
    def __init__(self):
        self.value = 0

    def next(self):
        self.value += 1
        return self.value


class BizIdGenerator:
    def __init__(self):
        self.dataset = 0
        self.dataset_version = 0
        self.job = 0
        self.job_version = 0
        self.run = 0

    def next_dataset(self):
        self.dataset += 1
        return f"ds_{self.dataset:08d}"

    def next_dataset_version(self):
        self.dataset_version += 1
        return f"dv_{self.dataset_version:08d}"

    def next_job(self):
        self.job += 1
        return f"job_{self.job:08d}"

    def next_job_version(self):
        self.job_version += 1
        return f"jv_{self.job_version:08d}"

    def next_run(self):
        self.run += 1
        return f"run_{self.run:08d}"


# =========================
# 边控制器
# =========================

class EdgeController:
    def __init__(self, target_avg_degree, max_degree, total_edges=None):
        self.target_avg_degree = target_avg_degree
        self.max_degree = max_degree
        self.total_edges = total_edges
        self.degree = {}
        self.edge_set = set()
        self.edge_count = 0
        self.edge_budget = None

    def set_node_count(self, node_count):
        if self.total_edges is not None:
            self.edge_budget = self.total_edges
        else:
            self.edge_budget = int(node_count * self.target_avg_degree / 2)

    def can_add(self, label, start_id, end_id, ignore_budget=False):
        key = (label, start_id, end_id)

        if key in self.edge_set:
            return False

        if not ignore_budget and self.edge_budget is not None:
            if self.edge_count >= self.edge_budget:
                return False

        if self.degree.get(start_id, 0) >= self.max_degree:
            return False

        if self.degree.get(end_id, 0) >= self.max_degree:
            return False

        return True

    def add_edge(self, edge_list, label, start_id, end_id, ignore_budget=False, **props):
        label = label.lower()

        if not self.can_add(label, start_id, end_id, ignore_budget):
            return False

        edge_list.append({
            ":LABEL": label,
            ":START_ID": start_id,
            ":END_ID": end_id,
            **props
        })

        self.edge_set.add((label, start_id, end_id))
        self.degree[start_id] = self.degree.get(start_id, 0) + 1
        self.degree[end_id] = self.degree.get(end_id, 0) + 1
        self.edge_count += 1

        return True

    def avg_degree(self, node_count):
        if node_count == 0:
            return 0
        return self.edge_count * 2 / node_count

    def max_degree_value(self):
        return max(self.degree.values()) if self.degree else 0


# =========================
# 深度分配
# =========================

def assign_dataset_depths(total_dataset, root_dataset, max_depth, target_avg_depth):
    """
    给 Dataset 分配深度：
    - root Dataset 深度为 0
    - 非 root Dataset 深度为 1~max_depth
    - 尽量让平均深度接近 target_avg_depth
    """
    root_dataset = min(root_dataset, total_dataset)

    depths = [0] * root_dataset
    remain = total_dataset - root_dataset

    if remain <= 0:
        return depths

    min_sum = remain * 1
    max_sum = remain * max_depth

    target_sum = round(total_dataset * target_avg_depth)
    target_sum = max(min_sum, min(target_sum, max_sum))

    remain_sum = target_sum
    remain_count = remain

    for _ in range(remain):
        low = max(1, remain_sum - (remain_count - 1) * max_depth)
        high = min(max_depth, remain_sum - (remain_count - 1) * 1)

        d = round(target_avg_depth + random.choice([-1, 0, 0, 1]))
        d = max(low, min(d, high))

        depths.append(d)

        remain_sum -= d
        remain_count -= 1

    random.shuffle(depths)
    return depths


# =========================
# graph_index.json
# =========================

def build_graph_index(out, vertex_groups, edge_groups, progress=None):
    nodes = {}
    name_index = {}
    biz_id_index = {}
    label_index = {}
    edges = []
    adjacency = {}
    total_rows = sum(len(rows) for rows in vertex_groups.values()) + sum(len(rows) for rows in edge_groups.values())
    done_rows = 0

    if progress:
        progress.set_phase("构建 graph_index.json", 98, 99.5)

    for label, rows in vertex_groups.items():
        for row in rows:
            node_id = str(row[":ID"])
            node = dict(row)
            node[":ID"] = str(node[":ID"])
            node["__label"] = label

            nodes[node_id] = node

            node_label = str(row.get(":LABEL", label)).lower()
            label_index.setdefault(node_label, []).append(node_id)

            name = row.get("name")
            if name:
                name_index.setdefault(str(name).lower(), []).append(node_id)

            biz_id = row.get("id")
            if biz_id:
                biz_id_index.setdefault(str(biz_id).lower(), []).append(node_id)

            done_rows += 1
            if progress:
                progress.update(done_rows, total_rows)

    for label, rows in edge_groups.items():
        for row in rows:
            start_id = str(row[":START_ID"])
            end_id = str(row[":END_ID"])

            edge = dict(row)
            edge[":START_ID"] = start_id
            edge[":END_ID"] = end_id
            edge["__label"] = label

            edges.append(edge)
            adjacency.setdefault(start_id, []).append(edge)
            adjacency.setdefault(end_id, []).append(edge)

            done_rows += 1
            if progress:
                progress.update(done_rows, total_rows)

    index = {
        "nodes": nodes,
        "name_index": name_index,
        "biz_id_index": biz_id_index,
        "label_index": label_index,
        "edges": edges,
        "adjacency": adjacency
    }

    index_path = Path(out) / "graph_index.json"
    if progress:
        progress.set_phase("写入 graph_index.json", 99.5, 99.8)
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, separators=(",", ":"))
    if progress:
        progress.update(1, 1, force=True)

    print(f"索引文件已生成: {index_path.resolve()}")


# =========================
# 主生成逻辑
# =========================

def main():
    parser = argparse.ArgumentParser()

    parser.add_argument("--dataset", type=int, default=1000, help="Dataset 总数")
    parser.add_argument("--root-dataset", type=int, default=5000, help="根 Dataset 数")
    parser.add_argument("--max-depth", type=int, default=10, help="Dataset 最大跳数")
    parser.add_argument("--target-avg-depth", type=float, default=6.0, help="目标平均跳数")

    parser.add_argument("--target-avg-degree", type=float, default=8.0, help="目标平均度")
    parser.add_argument("--total-edges", type=int, default=None, help="目标总边数，指定后优先于 target-avg-degree")
    parser.add_argument("--max-degree", type=int, default=20, help="单点最大度")

    parser.add_argument("--dataset-version-per-dataset", type=int, default=2, help="单个 Dataset 的 DatasetVersion 最大数量，实际随机 1~该值")
    parser.add_argument("--job-version-per-job", type=int, default=3, help="单个 Job 的 JobVersion 最大数量，实际随机 1~该值")
    parser.add_argument("--run-per-job-version", type=int, default=2, help="单个 JobVersion 的 JobRun 最大数量，实际随机 1~该值")

    parser.add_argument("--out", type=str, default="output")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--clean", action="store_true")
    parser.add_argument("--skip-index", action="store_true", help="跳过 graph_index.json 生成，适合大批量数据")
    parser.add_argument("--no-progress", action="store_true", help="关闭进度条")
    parser.add_argument("--progress-interval", type=float, default=1.0, help="进度条最小刷新间隔，单位秒")

    args = parser.parse_args()
    random.seed(args.seed)

    if args.total_edges is not None and args.total_edges < 0:
        raise ValueError("--total-edges 不能小于 0")

    if args.dataset_version_per_dataset < 1:
        raise ValueError("--dataset-version-per-dataset 必须大于等于 1")

    if args.job_version_per_job < 1:
        raise ValueError("--job-version-per-job 必须大于等于 1")

    if args.run_per_job_version < 1:
        raise ValueError("--run-per-job-version 必须大于等于 1")

    progress = ProgressBar(
        enabled=not args.no_progress,
        min_interval=max(0.1, args.progress_interval)
    )

    out = Path(args.out)
    if args.clean and out.exists():
        shutil.rmtree(out)

    vertex_dir = out / "vertices"
    edge_dir = out / "edges"

    graph_id_gen = GraphIdGenerator()
    biz_id_gen = BizIdGenerator()

    edge_ctl = EdgeController(
        target_avg_degree=args.target_avg_degree,
        max_degree=args.max_degree,
        total_edges=args.total_edges
    )

    base_time = int(datetime(2026, 1, 1, 0, 0, 0).timestamp() * 1000)
    offset = 0

    # 点
    datasets = []
    dataset_versions = []
    jobs = []
    job_versions = []
    job_runs = []

    # 边
    has_dversion = []
    has_jversion = []
    has_run = []
    consumes_by = []
    produces = []
    lineage = []

    # 映射
    dataset_gid = {}
    dataset_version_gid = {}
    job_gid = {}
    job_version_gid = {}
    run_gid = {}

    dataset_to_versions = {}
    dataset_depth = {}
    depth_to_datasets = {}

    job_to_input_dataset = {}
    job_to_output_dataset = {}

    # =========================
    # 1. 生成 Dataset 深度
    # =========================

    depths = assign_dataset_depths(
        total_dataset=args.dataset,
        root_dataset=args.root_dataset,
        max_depth=args.max_depth,
        target_avg_depth=args.target_avg_depth
    )
    progress.set_phase("生成 Dataset / DatasetVersion", 0, 20)

    # =========================
    # 2. 生成 Dataset / DatasetVersion 点
    # =========================

    for ds_idx, d in enumerate(depths, 1):
        ds_biz_id = biz_id_gen.next_dataset()
        ds_gid = graph_id_gen.next()

        dataset_gid[ds_biz_id] = ds_gid
        dataset_depth[ds_biz_id] = d
        depth_to_datasets.setdefault(d, []).append(ds_biz_id)
        dataset_to_versions[ds_biz_id] = []

        current_dv = None
        dataset_version_count = random.randint(1, args.dataset_version_per_dataset)

        for i in range(dataset_version_count):
            dv_biz_id = biz_id_gen.next_dataset_version()
            dv_gid = graph_id_gen.next()

            dataset_version_gid[dv_biz_id] = dv_gid
            dataset_to_versions[ds_biz_id].append(dv_biz_id)
            current_dv = dv_biz_id

            created_at = time_millis(base_time, offset)
            offset += 1

            dataset_versions.append({
                ":LABEL": "datasetversion",
                ":ID": dv_gid,
                "id": dv_biz_id,
                "dataset_uuid": ds_biz_id,
                "facets": json_str({
                    "version_index": str(i + 1),
                    "depth": str(d)
                }),
                "created_at": created_at,
                "owner": f"user_{random.randint(1, 20)}"
            })

        created_at = time_millis(base_time, offset)
        updated_at = created_at
        offset += 1

        datasets.append({
            ":LABEL": "dataset",
            ":ID": ds_gid,
            "id": ds_biz_id,
            "namespace": "default",
            "name": f"dataset_{biz_id_gen.dataset:08d}",
            "current_version": current_dv,
            "created_at": created_at,
            "updated_at": updated_at,
            "owner": f"user_{random.randint(1, 20)}"
        })
        progress.update(ds_idx, len(depths))

    # =========================
    # 3. 为每个非根 Dataset 生成一个 Job 链路
    # =========================

    non_root_datasets = [
        ds for ds in dataset_gid.keys()
        if dataset_depth[ds] > 0
    ]
    progress.set_phase("生成 Job / JobVersion / JobRun", 20, 45)

    for job_idx, output_ds in enumerate(non_root_datasets, 1):
        output_depth = dataset_depth[output_ds]

        candidate_inputs = []
        for d in range(output_depth - 1, -1, -1):
            candidate_inputs.extend(depth_to_datasets.get(d, []))
            if candidate_inputs:
                break

        if not candidate_inputs:
            continue

        input_ds = random.choice(candidate_inputs)

        job_biz_id = biz_id_gen.next_job()
        job_graph_id = graph_id_gen.next()

        job_gid[job_biz_id] = job_graph_id
        job_to_input_dataset[job_biz_id] = input_ds
        job_to_output_dataset[job_biz_id] = output_ds

        current_jv = None
        current_run = None
        job_version_count = random.randint(1, args.job_version_per_job)

        for jv_idx in range(job_version_count):
            jv_biz_id = biz_id_gen.next_job_version()
            jv_graph_id = graph_id_gen.next()

            job_version_gid[jv_biz_id] = jv_graph_id
            current_jv = jv_biz_id

            job_versions.append({
                ":LABEL": "jobversion",
                ":ID": jv_graph_id,
                "id": jv_biz_id,
                "job_uuid": job_biz_id,
                "facets": json_str({
                    "version_index": str(jv_idx + 1),
                    "depth": str(output_depth)
                }),
                "owner": f"user_{random.randint(1, 20)}"
            })

            run_count = random.randint(1, args.run_per_job_version)

            for run_idx in range(run_count):
                run_biz_id = biz_id_gen.next_run()
                run_graph_id = graph_id_gen.next()

                run_gid[run_biz_id] = run_graph_id
                current_run = run_biz_id

                created_at = time_millis(base_time, offset)
                updated_at = created_at
                offset += 1

                job_runs.append({
                    ":LABEL": "jobrun",
                    ":ID": run_graph_id,
                    "id": run_biz_id,
                    "state": random.choice(["SUCCESS", "FAILED", "RUNNING"]),
                    "namespace": "default",
                    "facets": json_str({
                        "run_index": str(run_idx + 1),
                        "depth": str(output_depth)
                    }),
                    "created_at": created_at,
                    "updated_at": updated_at,
                    "owner": f"user_{random.randint(1, 20)}",
                    "jobversion_id": jv_biz_id
                })

        created_at = time_millis(base_time, offset)
        updated_at = created_at
        offset += 1

        jobs.append({
            ":LABEL": "job",
            ":ID": job_graph_id,
            "id": job_biz_id,
            "namespace": "default",
            "name": f"job_{biz_id_gen.job:08d}",
            "current_version": current_jv,
            "current_run": current_run,
            "created_at": created_at,
            "updated_at": updated_at,
            "owner": f"user_{random.randint(1, 20)}"
        })
        progress.update(job_idx, len(non_root_datasets))

    # =========================
    # 4. 设置边预算
    # =========================

    node_count = (
        len(datasets)
        + len(dataset_versions)
        + len(jobs)
        + len(job_versions)
        + len(job_runs)
    )

    required_edge_count = (
        len(dataset_versions)
        + len(job_versions)
        + len(job_runs)
        + len(jobs) * 4
    )

    if args.total_edges is not None and args.total_edges < required_edge_count:
        raise ValueError(
            f"--total-edges 不能小于必要结构边数 {required_edge_count}，"
            f"当前参数下至少需要这些边来保持基础血缘结构完整"
        )

    edge_ctl.set_node_count(node_count)

    # =========================
    # 5. 结构边
    # =========================

    structure_total = len(dataset_to_versions) + len(job_versions)
    structure_done = 0
    progress.set_phase("生成结构边", 45, 60)

    for ds_biz_id, dv_list in dataset_to_versions.items():
        ds_gid = dataset_gid[ds_biz_id]

        for dv_biz_id in dv_list:
            dv_gid = dataset_version_gid[dv_biz_id]
            created_at = time_millis(base_time, offset)
            offset += 1

            edge_ctl.add_edge(
                has_dversion,
                "has_dversion",
                ds_gid,
                dv_gid,
                ignore_budget=True,
                created_at=created_at
            )
        structure_done += 1
        progress.update(structure_done, structure_total)

    jv_to_runs = {}
    for jr in job_runs:
        jv_to_runs.setdefault(jr["jobversion_id"], []).append(jr["id"])

    for jv in job_versions:
        job_biz_id = jv["job_uuid"]
        jv_biz_id = jv["id"]

        created_at = time_millis(base_time, offset)
        offset += 1

        edge_ctl.add_edge(
            has_jversion,
            "has_jversion",
            job_gid[job_biz_id],
            job_version_gid[jv_biz_id],
            ignore_budget=True,
            created_at=created_at
        )

        for run_biz_id in jv_to_runs.get(jv_biz_id, []):
            created_at = time_millis(base_time, offset)
            offset += 1

            edge_ctl.add_edge(
                has_run,
                "has_run",
                job_version_gid[jv_biz_id],
                run_gid[run_biz_id],
                ignore_budget=True,
                created_at=created_at
            )
        structure_done += 1
        progress.update(structure_done, structure_total)

    # =========================
    # 6. 明细血缘 + 强制生成直连 LINEAGE
    # =========================

    progress.set_phase("生成血缘边", 60, 72)

    for job_idx, job in enumerate(jobs, 1):
        job_biz_id = job["id"]
        input_ds = job_to_input_dataset[job_biz_id]
        output_ds = job_to_output_dataset[job_biz_id]

        input_dv = random.choice(dataset_to_versions[input_ds])
        output_dv = random.choice(dataset_to_versions[output_ds])

        run_biz_id = job["current_run"]

        input_ds_gid = dataset_gid[input_ds]
        output_ds_gid = dataset_gid[output_ds]
        job_graph_id = job_gid[job_biz_id]
        run_graph_id = run_gid[run_biz_id]
        input_dv_gid = dataset_version_gid[input_dv]
        output_dv_gid = dataset_version_gid[output_dv]

        created_at = time_millis(base_time, offset)
        offset += 1

        ok1 = edge_ctl.add_edge(
            consumes_by,
            "consumes_by",
            input_dv_gid,
            run_graph_id,
            ignore_budget=True,
            created_at=created_at
        )

        ok2 = edge_ctl.add_edge(
            produces,
            "produces",
            run_graph_id,
            output_dv_gid,
            ignore_budget=True,
            created_at=created_at
        )

        if ok1 and ok2:
            edge_ctl.add_edge(
                lineage,
                "lineage",
                input_ds_gid,
                job_graph_id,
                ignore_budget=True
            )

            edge_ctl.add_edge(
                lineage,
                "lineage",
                job_graph_id,
                output_ds_gid,
                ignore_budget=True
            )
        progress.update(job_idx, len(jobs))

    # =========================
    # 7. 尝试补齐平均度
    # =========================

    lower_datasets_by_depth = {}
    lower_pool = []
    actual_max_depth_for_pool = max(depth_to_datasets.keys()) if depth_to_datasets else 0
    for d in range(actual_max_depth_for_pool + 1):
        lower_datasets_by_depth[d] = lower_pool[:]
        lower_pool.extend(depth_to_datasets.get(d, []))

    jobs_shuffled = jobs[:]
    random.shuffle(jobs_shuffled)
    fill_start_count = edge_ctl.edge_count
    fill_target_count = edge_ctl.edge_budget or edge_ctl.edge_count
    progress.set_phase("补齐目标边数", 72, 82)

    while edge_ctl.edge_budget is not None and edge_ctl.edge_count < edge_ctl.edge_budget:
        changed = False

        for job in jobs_shuffled:
            if edge_ctl.edge_count >= edge_ctl.edge_budget:
                break

            job_biz_id = job["id"]
            output_ds = job_to_output_dataset[job_biz_id]
            output_depth = dataset_depth[output_ds]

            lower_datasets = lower_datasets_by_depth.get(output_depth, [])
            if not lower_datasets:
                continue

            input_ds = random.choice(lower_datasets)
            input_dv = random.choice(dataset_to_versions[input_ds])

            input_ds_gid = dataset_gid[input_ds]
            input_dv_gid = dataset_version_gid[input_dv]
            job_graph_id = job_gid[job_biz_id]
            run_graph_id = run_gid[job["current_run"]]

            created_at = time_millis(base_time, offset)
            offset += 1

            ok = edge_ctl.add_edge(
                consumes_by,
                "consumes_by",
                input_dv_gid,
                run_graph_id,
                created_at=created_at
            )

            if ok:
                edge_ctl.add_edge(
                    lineage,
                    "lineage",
                    input_ds_gid,
                    job_graph_id
                )
                changed = True
                progress.update(edge_ctl.edge_count - fill_start_count, fill_target_count - fill_start_count)

        if not changed:
            break

    progress.update(fill_target_count - fill_start_count, fill_target_count - fill_start_count, force=True)

    # =========================
    # 8. 写 CSV
    # =========================

    write_csv(
        vertex_dir / "Dataset.csv",
        [":LABEL", ":ID", "id", "namespace", "name", "current_version", "created_at", "updated_at", "owner"],
        datasets,
        progress=progress,
        phase="写入 Dataset.csv",
        start_percent=82,
        end_percent=84
    )

    write_csv(
        vertex_dir / "DatasetVersion.csv",
        [":LABEL", ":ID", "id", "dataset_uuid", "facets", "created_at", "owner"],
        dataset_versions,
        progress=progress,
        phase="写入 DatasetVersion.csv",
        start_percent=84,
        end_percent=86
    )

    write_csv(
        vertex_dir / "Job.csv",
        [":LABEL", ":ID", "id", "namespace", "name", "current_version", "current_run", "created_at", "updated_at", "owner"],
        jobs,
        progress=progress,
        phase="写入 Job.csv",
        start_percent=86,
        end_percent=88
    )

    write_csv(
        vertex_dir / "JobVersion.csv",
        [":LABEL", ":ID", "id", "job_uuid", "facets", "owner"],
        job_versions,
        progress=progress,
        phase="写入 JobVersion.csv",
        start_percent=88,
        end_percent=90
    )

    write_csv(
        vertex_dir / "JobRun.csv",
        [":LABEL", ":ID", "id", "state", "namespace", "facets", "created_at", "updated_at", "owner", "jobversion_id"],
        job_runs,
        progress=progress,
        phase="写入 JobRun.csv",
        start_percent=90,
        end_percent=92
    )

    write_csv(edge_dir / "HAS_DVERSION.csv", [":LABEL", ":START_ID", ":END_ID", "created_at"], has_dversion, progress, "写入 HAS_DVERSION.csv", 92, 93)
    write_csv(edge_dir / "HAS_JVERSION.csv", [":LABEL", ":START_ID", ":END_ID", "created_at"], has_jversion, progress, "写入 HAS_JVERSION.csv", 93, 94)
    write_csv(edge_dir / "HAS_RUN.csv", [":LABEL", ":START_ID", ":END_ID", "created_at"], has_run, progress, "写入 HAS_RUN.csv", 94, 95)
    write_csv(edge_dir / "CONSUMES_BY.csv", [":LABEL", ":START_ID", ":END_ID", "created_at"], consumes_by, progress, "写入 CONSUMES_BY.csv", 95, 96)
    write_csv(edge_dir / "PRODUCES.csv", [":LABEL", ":START_ID", ":END_ID", "created_at"], produces, progress, "写入 PRODUCES.csv", 96, 97)
    write_csv(edge_dir / "LINEAGE.csv", [":LABEL", ":START_ID", ":END_ID"], lineage, progress, "写入 LINEAGE.csv", 97, 98)

    # =========================
    # 9. 生成索引
    # =========================

    if args.skip_index:
        progress.set_phase("跳过索引文件", 98, 99)
        progress.update(1, 1, force=True)
        print("已跳过索引文件生成")
    else:
        build_graph_index(
            out,
            vertex_groups={
                "dataset": datasets,
                "datasetversion": dataset_versions,
                "job": jobs,
                "jobversion": job_versions,
                "jobrun": job_runs
            },
            edge_groups={
                "has_dversion": has_dversion,
                "has_jversion": has_jversion,
                "has_run": has_run,
                "consumes_by": consumes_by,
                "produces": produces,
                "lineage": lineage
            },
            progress=progress
        )

    # =========================
    # 10. 统计
    # =========================

    progress.finish()

    actual_avg_depth = sum(dataset_depth.values()) / len(dataset_depth) if dataset_depth else 0
    actual_max_depth = max(dataset_depth.values()) if dataset_depth else 0

    print("生成完成")
    print(f"输出目录: {out.resolve()}")
    print()
    print("点统计:")
    print(f"Dataset: {len(datasets)}")
    print(f"DatasetVersion: {len(dataset_versions)}")
    print(f"Job: {len(jobs)}")
    print(f"JobVersion: {len(job_versions)}")
    print(f"JobRun: {len(job_runs)}")
    print(f"Total Nodes: {node_count}")
    print()
    print("边统计:")
    print(f"HAS_DVERSION: {len(has_dversion)}")
    print(f"HAS_JVERSION: {len(has_jversion)}")
    print(f"HAS_RUN: {len(has_run)}")
    print(f"CONSUMES_BY: {len(consumes_by)}")
    print(f"PRODUCES: {len(produces)}")
    print(f"LINEAGE: {len(lineage)}")
    print(f"Total Edges: {edge_ctl.edge_count}")
    print()
    print("约束统计:")
    print(f"目标最大跳数: {args.max_depth}")
    print(f"实际最大跳数: {actual_max_depth}")
    print(f"目标平均跳数: {args.target_avg_depth}")
    print(f"实际平均跳数: {actual_avg_depth:.2f}")
    if args.total_edges is not None:
        print(f"目标总边数: {args.total_edges}")
    else:
        print(f"目标平均度: {args.target_avg_degree}")
    print(f"实际平均度: {edge_ctl.avg_degree(node_count):.2f}")
    print(f"目标最大度: {args.max_degree}")
    print(f"实际最大度: {edge_ctl.max_degree_value()}")

    if args.total_edges is not None and edge_ctl.edge_count < args.total_edges:
        print()
        print("提示：实际总边数低于目标总边数，说明受最大度或去重约束影响，已无法继续补边。")
        print("建议提高 --max-degree 或降低 --total-edges。")
    elif args.total_edges is None and edge_ctl.avg_degree(node_count) > args.target_avg_degree + 0.5:
        print()
        print("提示：实际平均度高于目标平均度，说明必要结构边已经超过边预算。")
        print("建议降低 dataset-version-per-dataset / job-version-per-job / run-per-job-version。")


if __name__ == "__main__":
    main()
