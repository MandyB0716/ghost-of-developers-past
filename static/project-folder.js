"use strict";

// Read only files inside the folder the user selected. Never request write access.
async function collectProjectFolder(root, {excludedFolders, allowFile}) {
  const result = {files: [], excluded: 0, unreadable: 0, limited: false};
  let visited = 0;
  async function walk(directory, prefix, depth) {
    const entries = [];
    try {
      for await (const entry of directory.values()) {
        if (visited >= 1000) { result.limited = true; break; }
        visited++;
        entries.push(entry);
      }
    } catch (error) {
      if (!prefix) throw error;
      result.unreadable++;
      return;
    }
    // Collect this directory's files before visiting its subdirectories.
    entries.sort((a, b) => (a.kind === "directory") - (b.kind === "directory") || a.name.localeCompare(b.name));
    for (const entry of entries) {
      const path = prefix + entry.name;
      if (entry.kind === "directory") {
        if (entry.name.startsWith(".") || excludedFolders.includes(entry.name.toLowerCase())) {
          result.excluded++;
        } else if (depth >= 12 || visited >= 1000) {
          result.limited = true;
        } else {
          await walk(entry, path + "/", depth + 1);
        }
      } else if (!allowFile(path)) {
        result.excluded++;
      } else {
        try { result.files.push({path, file: await entry.getFile()}); }
        catch { result.unreadable++; }
      }
    }
  }
  await walk(root, "", 0);
  return result;
}

if (typeof module !== "undefined") module.exports = {collectProjectFolder};
