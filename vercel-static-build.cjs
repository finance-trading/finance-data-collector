#!/usr/bin/env node
const { execSync } = require("node:child_process");
const path = require("node:path");
const root = path.resolve(__dirname, "frontend");
execSync("npm run build", { cwd: root, stdio: "inherit" });
process.exit(0);
