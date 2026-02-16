import crypto from "node:crypto";
import { createWriteStream } from "node:fs";
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import esbuild from "esbuild";
import archiver from "archiver";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const projectRoot = path.resolve(__dirname, "..");
const buildDir = path.join(projectRoot, "build");
const distDir = path.join(buildDir, "dist");
const packageDir = path.join(distDir, "package");
const packageDistDir = path.join(packageDir, "dist");

function ensureUuid32(value) {
  return typeof value === "string" && /^[a-z0-9]{32}$/.test(value.trim());
}

function createZip(sourceDir, outputPath) {
  return new Promise((resolve, reject) => {
    const output = createWriteStream(outputPath);
    const archive = archiver("zip", { zlib: { level: 9 } });

    output.on("close", resolve);
    archive.on("error", reject);

    archive.pipe(output);
    archive.directory(sourceDir, false);
    archive.finalize();
  });
}

async function build() {
  const packageJsonPath = path.join(projectRoot, "package.json");
  const extensionJsonPath = path.join(projectRoot, "extension.json");

  const packageJson = JSON.parse(await readFile(packageJsonPath, "utf8"));
  const extensionJson = JSON.parse(await readFile(extensionJsonPath, "utf8"));

  if (!ensureUuid32(extensionJson.uuid)) {
    extensionJson.uuid = crypto.randomUUID().replaceAll("-", "");
  }

  extensionJson.version = packageJson.version;
  extensionJson.entry = "./dist/index";

  // Clean build directory
  await rm(buildDir, { recursive: true, force: true });
  await mkdir(packageDistDir, { recursive: true });

  // Phase 1: Bundle with esbuild (IIFE, single file, browser platform)
  await esbuild.build({
    entryPoints: { index: path.join(projectRoot, "src", "index.js") },
    entryNames: "[name]",
    bundle: true,
    minify: false,
    outdir: packageDistDir,
    platform: "browser",
    format: "iife",
    globalName: "edaEsbuildExportName",
    treeShaking: true,
    external: ["node:fs", "node:path", "node:url", "node:crypto"],
  });

  // Phase 2: Assemble package files
  await writeFile(
    path.join(packageDir, "extension.json"),
    `${JSON.stringify(extensionJson, null, "\t")}\n`,
    "utf8"
  );

  const readmePath = path.join(projectRoot, "README.md");
  try {
    const readme = await readFile(readmePath, "utf8");
    await writeFile(path.join(packageDir, "README.md"), readme, "utf8");
  } catch {
    // README.md is optional
  }

  // Phase 3: Create .eext (zip) using archiver
  const eextPath = path.join(distDir, `${extensionJson.name}_v${extensionJson.version}.eext`);
  await createZip(packageDir, eextPath);

  process.stdout.write(`Built package: ${eextPath}\n`);
}

build().catch((error) => {
  process.stderr.write(`${error instanceof Error ? error.stack || error.message : String(error)}\n`);
  process.exitCode = 1;
});
