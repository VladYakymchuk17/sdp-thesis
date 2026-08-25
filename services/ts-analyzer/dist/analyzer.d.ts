export interface FileMetrics {
    file_path: string;
    loc: number;
    sloc: number;
    cyclomatic_complexity: number;
    max_nesting_depth: number;
    num_functions: number;
    avg_function_length: number;
    num_parameters_max: number;
    num_classes: number;
    num_imports: number;
}
export declare function analyzeFile(filePath: string): FileMetrics | null;
export declare function analyzeDirectory(dirPath: string): FileMetrics[];
