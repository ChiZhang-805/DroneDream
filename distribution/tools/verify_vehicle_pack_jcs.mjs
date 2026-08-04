#!/usr/bin/env node

import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const scriptDirectory = dirname(fileURLToPath(import.meta.url));
const repositoryRoot = resolve(scriptDirectory, "..", "..");

function rejectLoneSurrogates(value, label) {
  for (let index = 0; index < value.length; index += 1) {
    const code = value.charCodeAt(index);
    if (code >= 0xd800 && code <= 0xdbff) {
      const next = value.charCodeAt(index + 1);
      if (!(next >= 0xdc00 && next <= 0xdfff)) {
        throw new Error(`${label} contains an unpaired high surrogate`);
      }
      index += 1;
    } else if (code >= 0xdc00 && code <= 0xdfff) {
      throw new Error(`${label} contains an unpaired low surrogate`);
    }
  }
}

function canonicalize(value, label = "$") {
  if (value === null || typeof value === "boolean") {
    return JSON.stringify(value);
  }
  if (typeof value === "number") {
    if (!Number.isFinite(value)) {
      throw new Error(`${label} contains a non-finite number`);
    }
    return JSON.stringify(value);
  }
  if (typeof value === "string") {
    rejectLoneSurrogates(value, label);
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) {
    return `[${value.map((item, index) => canonicalize(item, `${label}[${index}]`)).join(",")}]`;
  }
  if (typeof value === "object") {
    return `{${Object.keys(value)
      .sort()
      .map((key) => {
        rejectLoneSurrogates(key, `${label} key`);
        return `${JSON.stringify(key)}:${canonicalize(value[key], `${label}.${key}`)}`;
      })
      .join(",")}}`;
  }
  throw new Error(`${label} contains an unsupported JSON value`);
}

function sha256(value) {
  return createHash("sha256").update(value, "utf8").digest("hex");
}

function parseJson(path) {
  return JSON.parse(readFileSync(path, "utf8"));
}

function verifySharedVector() {
  const inputPath = resolve(repositoryRoot, "runtime", "tests", "fixtures", "jcs-release-vector.input.json");
  const expectedPath = resolve(
    repositoryRoot,
    "runtime",
    "tests",
    "fixtures",
    "jcs-release-vector.sha256",
  );
  const actual = sha256(canonicalize(parseJson(inputPath)));
  const expected = readFileSync(expectedPath, "utf8").trim();
  if (actual !== expected) {
    throw new Error(`JCS implementation drifted from shared Rust vector: ${actual}`);
  }
}

function vehiclePayload(document, path) {
  if (document?.kind !== "dronedream-vehicle-pack" || document?.schemaVersion !== 1) {
    throw new Error(`${path} is not a version 1 Vehicle Pack`);
  }
  if (document?.integrity?.canonicalization !== "RFC8785-JCS") {
    throw new Error(`${path} does not declare RFC8785-JCS`);
  }
  const payload = { ...document };
  delete payload.integrity;
  return payload;
}

function main(argv) {
  const calculateOnly = argv[0] === "--calculate";
  const paths = calculateOnly ? argv.slice(1) : argv;
  if (paths.length === 0) {
    throw new Error("provide at least one Vehicle Pack manifest path");
  }
  verifySharedVector();
  for (const rawPath of paths) {
    const path = resolve(rawPath);
    const document = parseJson(path);
    const actual = sha256(canonicalize(vehiclePayload(document, rawPath)));
    if (calculateOnly) {
      process.stdout.write(`${rawPath} ${actual}\n`);
      continue;
    }
    if (document.integrity.payloadSha256 !== actual) {
      throw new Error(`${rawPath} payload SHA-256 mismatch: ${actual}`);
    }
  }
}

try {
  main(process.argv.slice(2));
} catch (error) {
  process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
  process.exitCode = 1;
}
