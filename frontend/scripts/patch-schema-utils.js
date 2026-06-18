const fs = require('fs');
const path = require('path');

function patchFile(filePath, replacements) {
  if (!fs.existsSync(filePath)) return;
  let content = fs.readFileSync(filePath, 'utf8');
  let changed = false;
  for (const [from, to] of replacements) {
    if (content.includes(from)) {
      content = content.split(from).join(to);
      changed = true;
    }
  }
  if (changed) {
    fs.writeFileSync(filePath, content);
    console.log('Patched:', filePath);
  }
}

// Find all schema-utils validate.js files
function findFiles(dir, filename, results = []) {
  if (!fs.existsSync(dir)) return results;
  const entries = fs.readdirSync(dir, { withFileTypes: true });
  for (const entry of entries) {
    const fullPath = path.join(dir, entry.name);
    if (entry.isDirectory() && entry.name !== '.git') {
      findFiles(fullPath, filename, results);
    } else if (entry.name === filename) {
      results.push(fullPath);
    }
  }
  return results;
}

const nodeModules = path.join(__dirname, '..', 'node_modules');

// Patch validate.js files
const validateFiles = findFiles(nodeModules, 'validate.js').filter(f => f.includes('schema-utils'));
for (const file of validateFiles) {
  patchFile(file, [
    ["'formatMinimum', 'formatMaximum', ", ""],
    ['"formatMinimum", "formatMaximum", ', ""],
    ['allErrors: true,', 'allErrors: true, strict: false,'],
  ]);
}

// Patch index.js files
const indexFiles = findFiles(nodeModules, 'index.js').filter(f => f.includes('schema-utils/dist/index') || f.includes('schema-utils\\dist\\index'));
for (const file of indexFiles) {
  patchFile(file, [
    ['module.exports = validate.default;', 'module.exports = validate.default; module.exports.validate = validate.default;'],
  ]);
}