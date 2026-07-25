"use strict";

/**
 * Outils fichier exposes au modele, confines a la racine du projet choisi
 * au lancement. Aucun outil shell, aucune suppression : juste lire/lister/
 * ecrire/editer, ce qui a ete demande.
 *
 * Prend `root` en parametre plutot que de lire un etat global, pour rester
 * testable avec du Node pur (voir selftest.js).
 */

const fs = require("fs");
const path = require("path");

const MAX_READ_BYTES = 400_000;

/** Resout un chemin relatif dans `root`, en refusant toute evasion. */
function resolveIn(root, relPath) {
  const rel = (relPath || "").trim();
  const rootResolved = path.resolve(root);
  const candidate = path.isAbsolute(rel) ? path.resolve(rel) : path.resolve(rootResolved, rel);
  const fromRoot = path.relative(rootResolved, candidate);
  if (fromRoot !== "" && (fromRoot.startsWith("..") || path.isAbsolute(fromRoot))) {
    return { path: null, error: "Acces refuse : hors du dossier du projet." };
  }
  return { path: candidate, error: null };
}

function relOf(root, p) {
  const r = path.relative(path.resolve(root), p);
  return r === "" ? "." : r;
}

function listDir(root, relPath = ".") {
  const { path: target, error } = resolveIn(root, relPath);
  if (error) return { ok: false, error };
  if (!fs.existsSync(target)) return { ok: false, error: "Dossier introuvable." };
  if (!fs.statSync(target).isDirectory()) return { ok: false, error: "Ce n'est pas un dossier." };
  const entries = fs
    .readdirSync(target, { withFileTypes: true })
    .filter((e) => !e.name.startsWith("."))
    .sort((a, b) => Number(a.isFile()) - Number(b.isFile()) || a.name.localeCompare(b.name))
    .map((e) => {
      const full = path.join(target, e.name);
      return {
        name: e.name,
        type: e.isDirectory() ? "dir" : "file",
        size: e.isFile() ? fs.statSync(full).size : null,
      };
    });
  return { ok: true, path: relOf(root, target), entries };
}

function readFile(root, relPath) {
  const { path: target, error } = resolveIn(root, relPath);
  if (error) return { ok: false, error };
  if (!fs.existsSync(target) || !fs.statSync(target).isFile()) {
    return { ok: false, error: "Fichier introuvable." };
  }
  if (fs.statSync(target).size > MAX_READ_BYTES) {
    return { ok: false, error: `Fichier trop volumineux (> ${MAX_READ_BYTES} o).` };
  }
  const content = fs.readFileSync(target, "utf8");
  return { ok: true, path: relOf(root, target), content, lines: content.split("\n").length };
}

function writeFile(root, relPath, content) {
  const { path: target, error } = resolveIn(root, relPath);
  if (error) return { ok: false, error };
  fs.mkdirSync(path.dirname(target), { recursive: true });
  const existed = fs.existsSync(target);
  const text = content == null ? "" : String(content);
  fs.writeFileSync(target, text, "utf8");
  return { ok: true, path: relOf(root, target), bytes: Buffer.byteLength(text), action: existed ? "modifie" : "cree" };
}

/** Remplace la premiere occurrence exacte de `find` par `replace`. */
function editFile(root, relPath, find, replace) {
  const { path: target, error } = resolveIn(root, relPath);
  if (error) return { ok: false, error };
  if (!fs.existsSync(target) || !fs.statSync(target).isFile()) {
    return { ok: false, error: "Fichier introuvable." };
  }
  const text = fs.readFileSync(target, "utf8");
  if (!find || !text.includes(find)) return { ok: false, error: "Texte a remplacer introuvable." };
  const occurrences = text.split(find).length - 1;
  fs.writeFileSync(target, text.replace(find, replace == null ? "" : String(replace)), "utf8");
  return { ok: true, path: relOf(root, target), occurrences, replaced: 1 };
}

const TOOLS = {
  list_dir: { args: ["path"], desc: "Lister le contenu d'un dossier du projet." },
  read_file: { args: ["path"], desc: "Lire un fichier texte du projet." },
  write_file: { args: ["path", "content"], desc: "Creer ou ecraser un fichier du projet." },
  edit_file: { args: ["path", "find", "replace"], desc: "Remplacer un extrait exact dans un fichier." },
};

function toolsManual() {
  return Object.entries(TOOLS)
    .map(([name, spec]) => `- ${name}(${spec.args.join(", ")}) : ${spec.desc}`)
    .join("\n");
}

function execute(root, name, args) {
  const a = args && typeof args === "object" ? args : {};
  try {
    switch (name) {
      case "list_dir":
        return listDir(root, a.path);
      case "read_file":
        return readFile(root, a.path);
      case "write_file":
        return writeFile(root, a.path, a.content);
      case "edit_file":
        return editFile(root, a.path, a.find, a.replace);
      default:
        return { ok: false, error: `Outil inconnu : ${name}` };
    }
  } catch (exc) {
    return { ok: false, error: `${exc.name}: ${exc.message}` };
  }
}

module.exports = { TOOLS, toolsManual, execute, resolveIn, listDir, readFile, writeFile, editFile };
