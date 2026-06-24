import fs from "node:fs/promises";
import path from "node:path";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { SpreadsheetFile, Workbook } = require("@oai/artifact-tool");

const [, , inputCsv, outputXlsx, runIdFilter] = process.argv;

if (!inputCsv || !outputXlsx) {
  console.error("Usage: node export_cypher_executions_xlsx.mjs <input.csv> <output.xlsx>");
  process.exit(2);
}

const CELL_TEXT_LIMIT = 32000;
const SUMMARY_HEADERS = [
  "phase",
  "count",
  "success",
  "failure",
  "db_elapsed_avg_ms",
  "db_elapsed_min_ms",
  "db_elapsed_max_ms",
  "http_total_avg_ms",
  "client_overhead_avg_ms",
];

function parseCsv(text) {
  const rows = [];
  let row = [];
  let field = "";
  let inQuotes = false;

  for (let i = 0; i < text.length; i += 1) {
    const ch = text[i];
    const next = text[i + 1];

    if (inQuotes) {
      if (ch === '"' && next === '"') {
        field += '"';
        i += 1;
      } else if (ch === '"') {
        inQuotes = false;
      } else {
        field += ch;
      }
      continue;
    }

    if (ch === '"') {
      inQuotes = true;
    } else if (ch === ",") {
      row.push(field);
      field = "";
    } else if (ch === "\n") {
      row.push(field);
      if (row.some((value) => value !== "")) rows.push(row);
      row = [];
      field = "";
    } else if (ch !== "\r") {
      field += ch;
    }
  }

  if (field !== "" || row.length > 0) {
    row.push(field);
    if (row.some((value) => value !== "")) rows.push(row);
  }

  return rows;
}

function toRecords(rows) {
  const headers = rows[0] ?? [];
  return rows.slice(1).map((row) =>
    Object.fromEntries(headers.map((header, index) => [header, row[index] ?? ""])),
  );
}

function safeSheetName(name, usedNames) {
  const cleaned = name.replace(/[\[\]\*\/\\\?:]/g, "_").slice(0, 31) || "sheet";
  let candidate = cleaned;
  let suffix = 1;
  while (usedNames.has(candidate)) {
    const marker = `_${suffix}`;
    candidate = `${cleaned.slice(0, 31 - marker.length)}${marker}`;
    suffix += 1;
  }
  usedNames.add(candidate);
  return candidate;
}

function numeric(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n : 0;
}

function executionRows(records) {
  return records.map((record) => {
    const statement = record.cypher_statement ?? "";
    return [
      record.run_id,
      record.start_time,
      record.phase,
      record.case,
      numeric(record.sequence),
      numeric(record.units),
      numeric(record.db_elapsed_ms),
      numeric(record.http_total_ms),
      numeric(record.client_overhead_ms),
      record.status,
      statement.length > CELL_TEXT_LIMIT ? statement.slice(0, CELL_TEXT_LIMIT) : statement,
      statement.length > CELL_TEXT_LIMIT,
    ];
  });
}

function summarize(records) {
  const grouped = new Map();
  for (const record of records) {
    const phase = record.phase || "unknown";
    if (!grouped.has(phase)) {
      grouped.set(phase, {
        phase,
        count: 0,
        success: 0,
        failure: 0,
        dbTotal: 0,
        dbMin: Infinity,
        dbMax: -Infinity,
        httpTotal: 0,
        overheadTotal: 0,
      });
    }
    const item = grouped.get(phase);
    const dbElapsed = numeric(record.db_elapsed_ms);
    item.count += 1;
    if (record.status === "success") item.success += 1;
    else item.failure += 1;
    item.dbTotal += dbElapsed;
    item.dbMin = Math.min(item.dbMin, dbElapsed);
    item.dbMax = Math.max(item.dbMax, dbElapsed);
    item.httpTotal += numeric(record.http_total_ms);
    item.overheadTotal += numeric(record.client_overhead_ms);
  }

  return [...grouped.values()]
    .sort((a, b) => a.phase.localeCompare(b.phase))
    .map((item) => [
      item.phase,
      item.count,
      item.success,
      item.failure,
      item.count ? item.dbTotal / item.count : 0,
      item.dbMin === Infinity ? 0 : item.dbMin,
      item.dbMax === -Infinity ? 0 : item.dbMax,
      item.count ? item.httpTotal / item.count : 0,
      item.count ? item.overheadTotal / item.count : 0,
    ]);
}

function styleSheet(sheet, rowCount, colCount) {
  sheet.showGridLines = false;
  sheet.freezePanes.freezeRows(1);
  const used = sheet.getRangeByIndexes(0, 0, Math.max(rowCount, 1), colCount);
  used.format.font = { name: "Aptos", size: 10 };
  used.format.autofitColumns();
  used.format.autofitRows();
  sheet.getRangeByIndexes(0, 0, 1, colCount).format = {
    fill: "#1F4E79",
    font: { bold: true, color: "#FFFFFF" },
  };
  sheet.getRangeByIndexes(0, 0, Math.max(rowCount, 1), colCount).format.borders = {
    preset: "inside",
    style: "thin",
    color: "#D9E2F3",
  };
}

function setExecutionWidths(sheet, rowCount) {
  const widths = [24, 20, 28, 30, 10, 10, 15, 15, 18, 12, 80, 24];
  widths.forEach((width, index) => {
    sheet.getRangeByIndexes(0, index, Math.max(rowCount, 1), 1).format.columnWidth = width;
  });
  if (rowCount > 1) {
    sheet.getRangeByIndexes(1, 4, rowCount - 1, 5).format.numberFormat = "0.000";
    sheet.getRangeByIndexes(1, 10, rowCount - 1, 1).format.wrapText = false;
  }
}

function writeMatrix(sheet, matrix) {
  const colCount = matrix[0]?.length ?? 1;
  const chunkSize = 500;
  for (let start = 0; start < matrix.length; start += chunkSize) {
    const chunk = matrix.slice(start, start + chunkSize);
    sheet.getRangeByIndexes(start, 0, chunk.length, colCount).values = chunk;
  }
}

const csvText = await fs.readFile(inputCsv, "utf8");
const records = toRecords(parseCsv(csvText)).filter(
  (record) => !runIdFilter || record.run_id === runIdFilter,
);
if (records.length === 0) {
  console.error(`No execution rows found${runIdFilter ? ` for run_id=${runIdFilter}` : ""}.`);
  process.exit(1);
}
const workbook = Workbook.create();
const usedNames = new Set();

const summary = workbook.worksheets.add(safeSheetName("summary", usedNames));
const summaryRows = [SUMMARY_HEADERS, ...summarize(records)];
writeMatrix(summary, summaryRows);
styleSheet(summary, summaryRows.length, SUMMARY_HEADERS.length);
summary.getRangeByIndexes(1, 4, Math.max(summaryRows.length - 1, 1), 5).format.numberFormat = "0.000";

const byPhase = new Map();
for (const record of records) {
  const phase = record.phase || "unknown";
  if (!byPhase.has(phase)) byPhase.set(phase, []);
  byPhase.get(phase).push(record);
}

const executionHeaders = [
  "run_id",
  "start_time",
  "phase",
  "case",
  "sequence",
  "units",
  "db_elapsed_ms",
  "http_total_ms",
  "client_overhead_ms",
  "status",
  "cypher_statement",
  "cypher_statement_truncated",
];

for (const [phase, phaseRecords] of [...byPhase.entries()].sort(([a], [b]) => a.localeCompare(b))) {
  const sheet = workbook.worksheets.add(safeSheetName(phase, usedNames));
  const matrix = [executionHeaders, ...executionRows(phaseRecords)];
  writeMatrix(sheet, matrix);
  styleSheet(sheet, matrix.length, executionHeaders.length);
  setExecutionWidths(sheet, matrix.length);
}

const scan = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 50 },
  maxChars: 2000,
});
if (scan.ndjson && scan.ndjson.trim()) {
  console.warn(scan.ndjson);
}

await fs.mkdir(path.dirname(path.resolve(outputXlsx)), { recursive: true });
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputXlsx);
console.log(`Wrote ${outputXlsx}`);
