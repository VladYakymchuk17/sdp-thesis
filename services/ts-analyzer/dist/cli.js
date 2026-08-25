"use strict";
var __createBinding = (this && this.__createBinding) || (Object.create ? (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    var desc = Object.getOwnPropertyDescriptor(m, k);
    if (!desc || ("get" in desc ? !m.__esModule : desc.writable || desc.configurable)) {
      desc = { enumerable: true, get: function() { return m[k]; } };
    }
    Object.defineProperty(o, k2, desc);
}) : (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    o[k2] = m[k];
}));
var __setModuleDefault = (this && this.__setModuleDefault) || (Object.create ? (function(o, v) {
    Object.defineProperty(o, "default", { enumerable: true, value: v });
}) : function(o, v) {
    o["default"] = v;
});
var __importStar = (this && this.__importStar) || (function () {
    var ownKeys = function(o) {
        ownKeys = Object.getOwnPropertyNames || function (o) {
            var ar = [];
            for (var k in o) if (Object.prototype.hasOwnProperty.call(o, k)) ar[ar.length] = k;
            return ar;
        };
        return ownKeys(o);
    };
    return function (mod) {
        if (mod && mod.__esModule) return mod;
        var result = {};
        if (mod != null) for (var k = ownKeys(mod), i = 0; i < k.length; i++) if (k[i] !== "default") __createBinding(result, mod, k[i]);
        __setModuleDefault(result, mod);
        return result;
    };
})();
Object.defineProperty(exports, "__esModule", { value: true });
const fs = __importStar(require("fs"));
const path = __importStar(require("path"));
const analyzer_1 = require("./analyzer");
function printUsage() {
    console.error("Usage:");
    console.error("  node dist/cli.js <file_or_directory> [--json]");
    console.error("  node dist/cli.js <directory> --batch --json");
    console.error("");
    console.error("Options:");
    console.error("  --json     Output as JSON (default for batch)");
    console.error("  --batch    Analyze all TS/JS files in directory recursively");
    process.exit(1);
}
const args = process.argv.slice(2);
const targetPath = args.find((a) => !a.startsWith("--"));
const jsonOutput = args.includes("--json");
const batchMode = args.includes("--batch");
if (!targetPath) {
    printUsage();
    process.exit(1);
}
const resolvedPath = path.resolve(targetPath);
if (!fs.existsSync(resolvedPath)) {
    console.error(`Error: path does not exist: ${resolvedPath}`);
    process.exit(1);
}
const stat = fs.statSync(resolvedPath);
if (stat.isFile()) {
    const metrics = (0, analyzer_1.analyzeFile)(resolvedPath);
    if (!metrics) {
        console.error(`Error: could not analyze file: ${resolvedPath}`);
        process.exit(1);
    }
    if (jsonOutput) {
        console.log(JSON.stringify(metrics, null, 2));
    }
    else {
        console.log(`File: ${metrics.file_path}`);
        console.log(`  LOC: ${metrics.loc}`);
        console.log(`  SLOC: ${metrics.sloc}`);
        console.log(`  Cyclomatic Complexity: ${metrics.cyclomatic_complexity}`);
        console.log(`  Max Nesting Depth: ${metrics.max_nesting_depth}`);
        console.log(`  Functions: ${metrics.num_functions}`);
        console.log(`  Avg Function Length: ${metrics.avg_function_length}`);
        console.log(`  Max Parameters: ${metrics.num_parameters_max}`);
        console.log(`  Classes: ${metrics.num_classes}`);
        console.log(`  Imports: ${metrics.num_imports}`);
    }
}
else if (stat.isDirectory()) {
    const results = (0, analyzer_1.analyzeDirectory)(resolvedPath);
    if (jsonOutput) {
        console.log(JSON.stringify(results));
    }
    else {
        console.log(`Analyzed ${results.length} files in ${resolvedPath}`);
        for (const m of results) {
            console.log(`  ${m.file_path} — LOC:${m.loc} CC:${m.cyclomatic_complexity} Nest:${m.max_nesting_depth} Fns:${m.num_functions}`);
        }
    }
}
else {
    console.error("Error: path is neither a file nor a directory");
    process.exit(1);
}
