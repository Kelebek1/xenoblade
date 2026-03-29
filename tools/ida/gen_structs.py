import os
import sys
from pathlib import Path
import cindex

PROJECT_PATH = Path(Path(__file__).parent.parent.parent)

def get_ninja_sources():
    def parse_build(ninja, i):
        full_build_line = ninja[i].split(": ",1)[1]
        while "$" in ninja[i]:
            i += 1
            full_build_line += ninja[i]
        full_build_line = full_build_line.replace("$", "").split()

        if ".c" not in full_build_line[1] and ".cpp" not in full_build_line[1]:
            return None

        source_path = Path(full_build_line[1])
        if not source_path.exists():
            print(f"Parsed but failed to find {source_path}")
            exit()

        includes = []

        while "cflags" not in ninja[i]:
            i += 1

        flags = ninja[i].split(" = ",1)[1]
        while "$" in ninja[i]:
            i += 1
            flags += ninja[i]
        flags = flags.replace("$", "").split()

        compile_lang = None

        for j,flag in enumerate(flags):
            if flag == "-i":
                includes.append(f"{flags[j + 1]}")
            elif flag.startswith("-lang"):
                match flag.split("=",1)[1]:
                    case "c":
                        compile_lang = "-std=c99"
                    case "c99":
                        compile_lang = "-std=c99"
                    case "c++":
                        compile_lang = "-std=c++98"
                    case _:
                        print(f"Unknown lang {compile_lang}")
                        exit()

        return {full_build_line[1]: {"path":source_path, "compile_include_paths":includes, "compile_lang":compile_lang}}

    ninja_path = PROJECT_PATH / "build.ninja"
    if not ninja_path.exists():
        print(f"build.ninja does not exist, make sure you run configure.py first")
        exit()

    ninja = ninja_path.read_text().splitlines()
    sources = {}

    i = 0
    while i < len(ninja):
        line = ninja[i]
        if line.startswith("build ") and ".o:" in line:
            res = parse_build(ninja, i)
            if res is not None:
                sources |= res
        i += 1

    return sources

def get_included_headers(source_files, index):
    def parse_file(source_files, index, k):
        file_path = source_files[k]["path"]
        compile_includes = source_files[k]["compile_include_paths"]
        compile_lang = source_files[k]["compile_lang"]

        #print(f"Parsing {file_path}")

        args = []
        match compile_lang:
            case "-std=c99":
                args.extend(["-x", "c"])
            case "-std=c++98":
                args.extend(["-x", "c++"])
            case _:
                print(f"Unknown compile lang {compile_lang}")
                exit()
        args.append(compile_lang)
        args.append("-nobuiltininc")
        args.append("-nostdlibinc")
        args.append("-nostdinc")
        args.append("-nostdinc++")
        args.extend([f"-I{include}" for include in compile_includes])

        #options = cindex.TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD | cindex.TranslationUnit.PARSE_SKIP_FUNCTION_BODIES
        options = cindex.TranslationUnit.PARSE_SKIP_FUNCTION_BODIES

        unit = index.parse(file_path, args=args, options=options)

        if "PowerPC" not in str(file_path):
            for diag in unit.diagnostics:
                if diag.severity == cindex.Diagnostic.Error:
                    print(diag)
                    exit()

        new_files = []
        for node in unit.cursor.get_children():
            if node.kind != cindex.CursorKind.INCLUSION_DIRECTIVE:
                continue

            include_path = Path(node.spelling)
            #print(f"\tTrying to find {include_path}")

            if not include_path.exists():
                for compile_include_path in compile_includes:
                    test_include_path = compile_include_path / include_path
                    #print(f"\t\tChecking for {test_include_path}")
                    if test_include_path.exists():
                        include_path = test_include_path
                        break;
                else:
                    print(f"\t\tUnable to find file path for {node.spelling}")
                    exit()

            include_path_str = str(include_path)
            if include_path_str not in source_files:
                #print(f"Found include {include_path}")
                source_files[include_path_str] = {"path":include_path, "compile_include_paths":compile_includes, "compile_lang":compile_lang}
                source_files |= parse_file(source_files, index, include_path_str)

        source_files[k]["unit"] = unit
        return source_files

    root_files = list(source_files.keys())
    for root in root_files:
        source_files |= parse_file(source_files, index, root)

    return source_files

clang_path = None

if sys.platform == "win32":
    for path in os.environ.get("PATH").split(";"):
        files = Path.glob(Path(path), pattern="*.exe")
        for file in files:
            if file.name == "clang.exe":
                clang_path = file.parent
                break;

if not clang_path:
    print(f"Failed to find libclang, is it in your PATH?")

print(f"Parsing ninja sources...")

source_files = get_ninja_sources()

#print(f"Found libclang at {clang_path}")
cindex.conf.set_library_path(clang_path)
index = cindex.Index.create()

print(f"Parsing all included files...")

source_files |= get_included_headers(source_files, index)

print(f"Building types...")

TYPES = {}

def output_type_fields(node, name):
    TYPES[name]["fields"] = []
    total_size = 0
    for i,field in enumerate(node.type.get_fields()):
        size = field.type.get_size()
        TYPES[name]["fields"].append({"name":field.spelling, "type":field.type.spelling, "size":size, "offset":total_size})
        total_size += size

def parse_node(node):
    if node.kind == cindex.CursorKind.TYPEDEF_DECL:
        name = node.type.get_fully_qualified_name(policy=cindex.PrintingPolicy.create(node))

        TYPES[name] = {}
        TYPES[name]["type"] = "typedef"
        TYPES[name]["size"] = node.type.get_size()
        TYPES[name]["alignment"] = node.type.get_align()
        TYPES[name]["real_type"] = node.underlying_typedef_type.spelling

        #print(f"typedef {TYPES[name]['real_type']} {name};")

    elif node.kind == cindex.CursorKind.STRUCT_DECL:
        name = node.type.get_fully_qualified_name(policy=cindex.PrintingPolicy.create(node))
        if name in TYPES:
            return

        #print(f"{node.location.file}:{node.location.line} -- {node.type.spelling}")

        TYPES[name] = {}
        TYPES[name]["type"] = "struct"
        TYPES[name]["size"] = node.type.get_size()
        TYPES[name]["alignment"] = node.type.get_align()

        output_type_fields(node, name)

    elif node.kind == cindex.CursorKind.CLASS_DECL:
        name = node.type.get_fully_qualified_name(policy=cindex.PrintingPolicy.create(node))
        if name in TYPES:
            return

        TYPES[name] = {}
        TYPES[name]["type"] = "class"
        TYPES[name]["size"] = node.type.get_size()
        TYPES[name]["alignment"] = node.type.get_align()

        output_type_fields(node, name)

        for class_node in node.get_children():
            parse_node(class_node)

# Now we have all the project build files and have parsed them
for _, entry in source_files.items():
    #print(f"Parsing {entry['path']}")
    for node in entry["unit"].cursor.get_children():
        parse_node(node)

#print(TYPES)

print(f"Generating types...")

TYPES_OUTPUT = set()
OUTPUT = []

BUILTIN_TYPES = {
    "char",
    "signed char",
    "unsigned char",
    "short",
    "signed short",
    "unsigned short",
    "int",
    "signed int",
    "unsigned int",
    "long",
    "signed long",
    "unsigned long",
    "long long",
    "signed long long",
    "unsigned long long",
    "float",
    "double",
    "void",
    "nullptr",
}

def needs_output(name):
    return not (name in BUILTIN_TYPES or name in TYPES_OUTPUT)

def output_type(k):
    global TYPES_OUTPUT
    name = k
    entry = TYPES[k]

    if not needs_output(name):
        return
    TYPES_OUTPUT.add(name)

    ret = ""

    match entry["type"]:
        case "typedef":
            if needs_output(entry['real_type']):
                output_type(entry['real_type'])
            OUTPUT.append(f"typedef {entry['real_type']} {name};")

for k in TYPES.keys():
    output_type(k)

print("\n".join(output))
