import { copyFile, cp, mkdir, access, readdir } from "node:fs/promises";
import { constants } from "node:fs";
import { dirname, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const dist = resolve(root, "dist");

const copyPairs = [
  ["pages/architecture-gallery.html", "pages/architecture-gallery.html"],
  ["pages/credential-rotation-guide.html", "pages/credential-rotation-guide.html"],
  ["pages/explainers-v4.css", "pages/explainers-v4.css"],
  ["pages/explainers-v4.html", "pages/explainers-v4.html"],
  ["pages/local-inference-guide.html", "pages/local-inference-guide.html"],
  ["pages/repo-commands.html", "pages/repo-commands.html"],
  ["pages/login.html", "pages/login.html"],
  ["pages/login.js",   "pages/login.js"],
  ["shared/explainers-docs.css", "shared/explainers-docs.css"],
  ["shared/explainers-docs.js", "shared/explainers-docs.js"]
];

const optionalPairs = [
  ["index.json", "index.json"],
  ["tasks.json", "tasks.json"]
];

const repoArtifactNames = new Set([
  "architecture-gallery.html",
  "architecture-gallery-v2.html",
  "repo-commands.html",
  "repo-commands-v2.html"
]);
const repoSkipDirs = new Set([".git", "node_modules", "repos", "explainers"]);

async function copyPair(fromRelative, toRelative) {
  const source = resolve(root, fromRelative);
  const target = resolve(dist, toRelative);
  await mkdir(dirname(target), { recursive: true });
  await copyFile(source, target);
}

async function maybeCopyPair(fromRelative, toRelative) {
  const source = resolve(root, fromRelative);
  try {
    await access(source, constants.F_OK);
    await copyPair(fromRelative, toRelative);
  } catch {
    // Optional runtime data may not exist locally during development.
  }
}

async function copyRepoArtifacts() {
  const reposRoot = resolve(root, "repos");

  try {
    await access(reposRoot, constants.F_OK);
  } catch {
    return;
  }

  async function walk(currentDir) {
    const entries = await readdir(currentDir, { withFileTypes: true });

    await Promise.all(
      entries.map(async (entry) => {
        const fullPath = resolve(currentDir, entry.name);

        if (entry.isSymbolicLink()) {
          return;
        }

        if (entry.isDirectory()) {
          if (repoSkipDirs.has(entry.name)) {
            return;
          }
          await walk(fullPath);
          return;
        }

        if (!repoArtifactNames.has(entry.name)) {
          return;
        }

        const outputPath = resolve(dist, "repos", relative(reposRoot, fullPath));
        await mkdir(dirname(outputPath), { recursive: true });
        await copyFile(fullPath, outputPath);
      })
    );
  }

  await walk(reposRoot);
}

await Promise.all(copyPairs.map(([from, to]) => copyPair(from, to)));
await Promise.all(optionalPairs.map(([from, to]) => maybeCopyPair(from, to)));

try {
  await access(resolve(root, "status"), constants.F_OK);
  await cp(resolve(root, "status"), resolve(dist, "status"), {
    force: true,
    recursive: true
  });
} catch {
  // status/ is synced separately in some environments.
}

await copyRepoArtifacts();
