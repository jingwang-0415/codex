#!/usr/bin/env node

import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";

const args = process.argv.slice(2);
if (!args.length || args.includes("--help")) {
  console.log("Usage: node validate_html_deck.mjs <deck.html> [--min-slides N] [--max-slides N]");
  process.exit(args.length ? 0 : 1);
}

const file = path.resolve(args[0]);
const optionValue = (name, fallback) => {
  const index = args.indexOf(name);
  return index >= 0 ? Number(args[index + 1]) : fallback;
};
const minSlides = optionValue("--min-slides", 5);
const maxSlides = optionValue("--max-slides", 8);
const errors = [];
const warnings = [];

const fail = (message) => errors.push(message);
const warn = (message) => warnings.push(message);

if (!fs.existsSync(file)) {
  console.error(`ERROR: file not found: ${file}`);
  process.exit(1);
}

const html = fs.readFileSync(file, "utf8");
const baseDir = path.dirname(file);
const slides = [...html.matchAll(/<section\b[^>]*class=["'][^"']*\bslide\b[^"']*["'][^>]*>/gi)];
if (slides.length < minSlides || slides.length > maxSlides) {
  fail(`slide count ${slides.length} is outside ${minSlides}-${maxSlides}`);
}

const ids = [...html.matchAll(/\bid=["']([^"']+)["']/gi)].map((match) => match[1]);
const duplicateIds = [...new Set(ids.filter((id, index) => ids.indexOf(id) !== index))];
if (duplicateIds.length) fail(`duplicate ids: ${duplicateIds.join(", ")}`);

const checkCss = (css, label) => {
  let depth = 0;
  let quote = null;
  let comment = false;
  for (let index = 0; index < css.length; index += 1) {
    const current = css[index];
    const next = css[index + 1];
    if (comment) {
      if (current === "*" && next === "/") {
        comment = false;
        index += 1;
      }
      continue;
    }
    if (!quote && current === "/" && next === "*") {
      comment = true;
      index += 1;
      continue;
    }
    if (quote) {
      if (current === "\\") index += 1;
      else if (current === quote) quote = null;
      continue;
    }
    if (current === '"' || current === "'") quote = current;
    else if (current === "{") depth += 1;
    else if (current === "}") depth -= 1;
    if (depth < 0) {
      fail(`${label}: unexpected closing brace`);
      return;
    }
  }
  if (depth !== 0) fail(`${label}: unbalanced CSS braces (${depth})`);
};

for (const [index, match] of [...html.matchAll(/<style\b[^>]*>([\s\S]*?)<\/style>/gi)].entries()) {
  checkCss(match[1], `${path.basename(file)} inline style ${index + 1}`);
}

for (const match of html.matchAll(/<link\b[^>]*rel=["']stylesheet["'][^>]*href=["']([^"']+)["'][^>]*>/gi)) {
  const href = match[1];
  if (/^(?:https?:|data:|\/\/)/i.test(href)) continue;
  const cssFile = path.resolve(baseDir, href.split(/[?#]/)[0]);
  if (!fs.existsSync(cssFile)) fail(`missing stylesheet: ${href}`);
  else checkCss(fs.readFileSync(cssFile, "utf8"), href);
}

const compileScript = (source, label) => {
  try {
    new vm.Script(source, { filename: label });
  } catch (error) {
    fail(`${label}: ${error.message}`);
  }
};

for (const [index, match] of [...html.matchAll(/<script(\b[^>]*)>([\s\S]*?)<\/script>/gi)].entries()) {
  const attributes = match[1];
  const sourceMatch = attributes.match(/\bsrc=["']([^"']+)["']/i);
  if (sourceMatch) {
    const source = sourceMatch[1];
    if (/^(?:https?:|data:|\/\/)/i.test(source)) continue;
    const scriptFile = path.resolve(baseDir, source.split(/[?#]/)[0]);
    if (!fs.existsSync(scriptFile)) fail(`missing script: ${source}`);
    else compileScript(fs.readFileSync(scriptFile, "utf8"), source);
  } else if (match[2].trim()) {
    compileScript(match[2], `${path.basename(file)} inline script ${index + 1}`);
  }
}

const localReferences = new Set();
for (const match of html.matchAll(/\b(?:src|href)=["']([^"']+)["']/gi)) localReferences.add(match[1]);
for (const match of html.matchAll(/url\(\s*["']?([^"')]+)["']?\s*\)/gi)) localReferences.add(match[1]);
for (const reference of localReferences) {
  if (!reference || /^(?:#|https?:|data:|mailto:|tel:|javascript:|\/\/)/i.test(reference)) continue;
  const clean = reference.split(/[?#]/)[0];
  if (!clean) continue;
  const target = path.resolve(baseDir, clean);
  if (!fs.existsSync(target)) fail(`missing local resource: ${reference}`);
}

for (const pattern of [/【[^】]+】/g, /\bTODO\b/gi, /\[X\]/g, /待回填/g]) {
  const matches = html.match(pattern);
  if (matches?.length) warn(`unresolved placeholders: ${[...new Set(matches)].join(", ")}`);
}

console.log(`Deck: ${file}`);
console.log(`Slides: ${slides.length}`);
for (const message of warnings) console.log(`WARN: ${message}`);
for (const message of errors) console.error(`ERROR: ${message}`);
if (errors.length) process.exit(1);
console.log("Validation: OK");
