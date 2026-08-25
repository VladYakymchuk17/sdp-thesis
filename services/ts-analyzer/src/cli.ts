import * as fs from "fs";
import * as path from "path";
import { analyzeFile, analyzeDirectory } from "./analyzer";

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
  const metrics = analyzeFile(resolvedPath);
  if (!metrics) {
    console.error(`Error: could not analyze file: ${resolvedPath}`);
    process.exit(1);
  }
  if (jsonOutput) {
    console.log(JSON.stringify(metrics, null, 2));
  } else {
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
} else if (stat.isDirectory()) {
  const results = analyzeDirectory(resolvedPath);
  if (jsonOutput) {
    console.log(JSON.stringify(results));
  } else {
    console.log(`Analyzed ${results.length} files in ${resolvedPath}`);
    for (const m of results) {
      console.log(`  ${m.file_path} — LOC:${m.loc} CC:${m.cyclomatic_complexity} Nest:${m.max_nesting_depth} Fns:${m.num_functions}`);
    }
  }
} else {
  console.error("Error: path is neither a file nor a directory");
  process.exit(1);
}
