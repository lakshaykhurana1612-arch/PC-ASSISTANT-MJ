from pathlib import Path
import ast


class ProjectScanner:

    def __init__(self, root):
        self.root = Path(root)

        self.files = []
        self.python = []
        self.functions = []

        self.classes = []

        self.imports = []

        self.folders = 0

    def scan(self):

        for item in self.root.rglob("*"):

            if item.is_dir():
                self.folders += 1

            else:

                self.files.append(item)

                if item.suffix == ".py":

                   self.python.append(item)

                   parsed = self.parse_python_file(item)

                   self.functions.extend(parsed["functions"])

                   self.classes.extend(parsed["classes"])

                   self.imports.extend(parsed["imports"])

        return {

                "project": self.root.name,

                "root": str(self.root),

                "files": len(self.files),

                "folders": self.folders,

                "python": len(self.python),

                "functions": len(self.functions),
                "function_index": self.functions,

                "classes": len(self.classes),

                "class_index": self.classes,

                "imports": len(set(self.imports)),

                "function_names": sorted(

               [f["name"] for f in self.functions]

                ),

                "class_names": sorted(

                [c["name"] for c in self.classes]

                ),

                "import_names": sorted(set(self.imports))
            }


    
    

    def parse_python_file(self, filepath):

        result = {
        "functions": [],
        "classes": [],
        "imports": []
    }

        try:

            with open(filepath, "r", encoding="utf-8") as f:

                tree = ast.parse(f.read())

            for node in ast.walk(tree):

                if isinstance(node, ast.FunctionDef):

                    result["functions"].append({

                       "name": node.name,

                       "file": str(filepath),

                       "line": node.lineno,

                       "args": [arg.arg for arg in node.args.args]
                   })

                elif isinstance(node, ast.ClassDef):

                    result["classes"].append
                elif isinstance(node, ast.Import):

                    for imp in node.names:

                        result["imports"].append(imp.name)

                elif isinstance(node, ast.ImportFrom):

                    if node.module:

                        result["imports"].append(node.module)

        except Exception:
            pass

        return result
    
def analyze_project(path):
    scanner = ProjectScanner(path)
    return scanner.scan()

def find_function(project_data, function_name):

    if not project_data:
        return None

    for func in project_data.get("function_index", []):

        if func["name"].lower() == function_name.lower():
            return func

    return None