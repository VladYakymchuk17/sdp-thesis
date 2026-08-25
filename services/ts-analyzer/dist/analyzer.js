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
exports.analyzeFile = analyzeFile;
exports.analyzeDirectory = analyzeDirectory;
const ts = __importStar(require("typescript"));
const fs = __importStar(require("fs"));
const path = __importStar(require("path"));
function countLinesOfCode(sourceText) {
    const lines = sourceText.split("\n");
    const loc = lines.length;
    let sloc = 0;
    for (const line of lines) {
        const trimmed = line.trim();
        if (trimmed.length > 0 && !trimmed.startsWith("//") && !trimmed.startsWith("*") && trimmed !== "/*" && trimmed !== "*/") {
            sloc++;
        }
    }
    return { loc, sloc };
}
function computeCyclomaticComplexity(node) {
    let complexity = 0;
    function visit(n) {
        switch (n.kind) {
            case ts.SyntaxKind.IfStatement:
            case ts.SyntaxKind.ConditionalExpression: // ternary
            case ts.SyntaxKind.ForStatement:
            case ts.SyntaxKind.ForInStatement:
            case ts.SyntaxKind.ForOfStatement:
            case ts.SyntaxKind.WhileStatement:
            case ts.SyntaxKind.DoStatement:
            case ts.SyntaxKind.CatchClause:
            case ts.SyntaxKind.CaseClause:
                complexity++;
                break;
            case ts.SyntaxKind.BinaryExpression:
                const op = n.operatorToken.kind;
                if (op === ts.SyntaxKind.AmpersandAmpersandToken || op === ts.SyntaxKind.BarBarToken || op === ts.SyntaxKind.QuestionQuestionToken) {
                    complexity++;
                }
                break;
        }
        ts.forEachChild(n, visit);
    }
    visit(node);
    return complexity + 1; // base path
}
function computeMaxNesting(node) {
    let maxDepth = 0;
    function visit(n, depth) {
        switch (n.kind) {
            case ts.SyntaxKind.IfStatement:
            case ts.SyntaxKind.ForStatement:
            case ts.SyntaxKind.ForInStatement:
            case ts.SyntaxKind.ForOfStatement:
            case ts.SyntaxKind.WhileStatement:
            case ts.SyntaxKind.DoStatement:
            case ts.SyntaxKind.SwitchStatement:
            case ts.SyntaxKind.TryStatement:
                depth++;
                if (depth > maxDepth)
                    maxDepth = depth;
                break;
        }
        ts.forEachChild(n, (child) => visit(child, depth));
    }
    visit(node, 0);
    return maxDepth;
}
function extractFunctions(sourceFile) {
    const functions = [];
    function visit(node) {
        let name = "<anonymous>";
        let params;
        let body;
        if (ts.isFunctionDeclaration(node)) {
            name = node.name?.getText(sourceFile) ?? "<anonymous>";
            params = node.parameters;
            body = node.body;
        }
        else if (ts.isMethodDeclaration(node)) {
            name = node.name?.getText(sourceFile) ?? "<anonymous>";
            params = node.parameters;
            body = node.body;
        }
        else if (ts.isArrowFunction(node) || ts.isFunctionExpression(node)) {
            if (node.parent && ts.isVariableDeclaration(node.parent) && node.parent.name) {
                name = node.parent.name.getText(sourceFile);
            }
            params = node.parameters;
            body = node.body;
        }
        else if (ts.isConstructorDeclaration(node)) {
            name = "constructor";
            params = node.parameters;
            body = node.body;
        }
        else if (ts.isGetAccessorDeclaration(node) || ts.isSetAccessorDeclaration(node)) {
            name = node.name?.getText(sourceFile) ?? "<accessor>";
            params = node.parameters;
            body = node.body;
        }
        if (params !== undefined && body !== undefined) {
            const startLine = sourceFile.getLineAndCharacterOfPosition(body.getStart(sourceFile)).line;
            const endLine = sourceFile.getLineAndCharacterOfPosition(body.getEnd()).line;
            functions.push({
                name,
                lineCount: endLine - startLine + 1,
                paramCount: params.length,
            });
        }
        ts.forEachChild(node, visit);
    }
    visit(sourceFile);
    return functions;
}
function countClasses(sourceFile) {
    let count = 0;
    function visit(node) {
        if (ts.isClassDeclaration(node) || ts.isClassExpression(node)) {
            count++;
        }
        ts.forEachChild(node, visit);
    }
    visit(sourceFile);
    return count;
}
function countImports(sourceFile) {
    let count = 0;
    function visit(node) {
        if (ts.isImportDeclaration(node)) {
            count++;
        }
        ts.forEachChild(node, visit);
    }
    visit(sourceFile);
    return count;
}
function analyzeFile(filePath) {
    if (!fs.existsSync(filePath)) {
        return null;
    }
    const sourceText = fs.readFileSync(filePath, "utf-8");
    const ext = path.extname(filePath).toLowerCase();
    const scriptKind = ext === ".tsx" ? ts.ScriptKind.TSX :
        ext === ".jsx" ? ts.ScriptKind.JSX :
            ext === ".js" || ext === ".mjs" || ext === ".cjs" ? ts.ScriptKind.JS :
                ts.ScriptKind.TS;
    const sourceFile = ts.createSourceFile(filePath, sourceText, ts.ScriptTarget.Latest, true, scriptKind);
    const { loc, sloc } = countLinesOfCode(sourceText);
    const complexity = computeCyclomaticComplexity(sourceFile);
    const maxNesting = computeMaxNesting(sourceFile);
    const functions = extractFunctions(sourceFile);
    const numClasses = countClasses(sourceFile);
    const numImports = countImports(sourceFile);
    const avgFunctionLength = functions.length > 0
        ? functions.reduce((sum, f) => sum + f.lineCount, 0) / functions.length
        : 0;
    const maxParams = functions.length > 0
        ? Math.max(...functions.map((f) => f.paramCount))
        : 0;
    return {
        file_path: filePath,
        loc,
        sloc,
        cyclomatic_complexity: complexity,
        max_nesting_depth: maxNesting,
        num_functions: functions.length,
        avg_function_length: Math.round(avgFunctionLength * 100) / 100,
        num_parameters_max: maxParams,
        num_classes: numClasses,
        num_imports: numImports,
    };
}
function analyzeDirectory(dirPath) {
    const results = [];
    const validExtensions = new Set([".ts", ".tsx", ".js", ".jsx", ".mts", ".cts", ".mjs", ".cjs"]);
    function walk(dir) {
        const entries = fs.readdirSync(dir, { withFileTypes: true });
        for (const entry of entries) {
            const fullPath = path.join(dir, entry.name);
            if (entry.isDirectory()) {
                if (entry.name === "node_modules" || entry.name === ".git" || entry.name === "dist" || entry.name === "build" || entry.name === ".next") {
                    continue;
                }
                walk(fullPath);
            }
            else if (entry.isFile() && validExtensions.has(path.extname(entry.name).toLowerCase())) {
                const metrics = analyzeFile(fullPath);
                if (metrics) {
                    results.push(metrics);
                }
            }
        }
    }
    walk(dirPath);
    return results;
}
