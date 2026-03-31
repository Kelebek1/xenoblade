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
        args.append("-nostdlibinc")
        args.append("-nostdinc")
        args.append("-nostdinc++")
        args.append("--target=ppc32")
        args.extend([f"-I{include}" for include in compile_includes])

        #options = cindex.TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD | cindex.TranslationUnit.PARSE_SKIP_FUNCTION_BODIES
        options = cindex.TranslationUnit.PARSE_SKIP_FUNCTION_BODIES

        unit = index.parse(file_path, args=args, options=options)
        source_files[k]["unit"] = unit

        has_def = False
        for node in unit.cursor.get_children():
            if "desc_info" in node.spelling:
                has_def = True
                break;
        """
        if has_def:
            print(node.location.file)
            for node in unit.cursor.get_children():
                print(node.location.line, node.spelling, node.kind, node.type.kind)

            exit()
        """
        #print(file_path, args)

        if "PowerPC_EABI_Support" not in str(file_path) and "sj_crs.c" not in str(file_path):
            for diag in unit.diagnostics:
                if diag.severity == cindex.Diagnostic.Error:
                    print(diag)
                    exit()

        """
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
                #print(f"Found include {include_path}, parsing")
                source_files[include_path_str] = {"path":include_path, "compile_include_paths":compile_includes, "compile_lang":compile_lang}
                source_files |= parse_file(source_files, index, include_path_str)
        """
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
    def align_up(v, to):
        assert bin(to).count("1") == 1, f"to must be a power of 2!"
        return (v + to - 1) & ~to
    TYPES[name]["fields"] = []
    total_size = 0
    for i,field in enumerate(node.type.get_fields()):
        total_size = align_up(total_size, field.type.get_align())
        size = field.type.get_size()
        TYPES[name]["fields"].append({"name":field.spelling, "type":field.type.spelling, "size":size, "offset":total_size})
        total_size += size

def output_typedef(node):
    name = node.type.get_fully_qualified_name(policy=cindex.PrintingPolicy.create(node))

    if name in TYPES:
        return

    TYPES[name] = {}

    underlying_type = node.underlying_typedef_type.spelling

    #if "GXTlutRegionCallback" in name:
    #    print(node.spelling, underlying_type)
    #    exit()

    if "(" in underlying_type and underlying_type[-1] == ")":
        TYPES[name]["kind"] = "typedef_func"
    elif underlying_type.startswith("enum "):
        TYPES[name]["kind"] = "typedef_enum"
        underlying_type = underlying_type.split("enum ",1)[1]
    elif underlying_type.startswith("struct "):
        TYPES[name]["kind"] = "typedef_struct"
        underlying_type = underlying_type.split("struct ",1)[1]
    elif underlying_type.startswith("class "):
        TYPES[name]["kind"] = "typedef_struct"
        underlying_type = underlying_type.split("class ",1)[1]
    else:
        TYPES[name]["kind"] = "typedef"

    TYPES[name]["size"] = node.type.get_size()
    TYPES[name]["alignment"] = node.type.get_align()
    TYPES[name]["real_type"] = underlying_type

def output_enum(node):
    name = node.type.get_fully_qualified_name(policy=cindex.PrintingPolicy.create(node))

    if "(unnamed" in name:
        name = f"__unnamed_{node.location.file}_{node.location.line}"

    if name in TYPES:
        return

    TYPES[name] = {}
    TYPES[name]["kind"] = "enum"
    TYPES[name]["size"] = node.type.get_size()
    TYPES[name]["alignment"] = node.type.get_align()
    TYPES[name]["real_type"] = node.enum_type.spelling

    TYPES[name]["fields"] = []
    for child in node.get_children():
        enum_name = child.spelling
        enum_value = child.enum_value
        TYPES[name]["fields"].append({"name":enum_name, "value":enum_value})

    #print(name, TYPES[name])

def parse_node(node):
    if node.kind == cindex.CursorKind.TYPEDEF_DECL:
        output_typedef(node)
        #print(f"typedef {TYPES[name]['real_type']} {name};")

    elif node.kind == cindex.CursorKind.ENUM_DECL:
        output_enum(node)

    elif node.kind == cindex.CursorKind.STRUCT_DECL:
        name = node.type.get_fully_qualified_name(policy=cindex.PrintingPolicy.create(node))
        if name in TYPES:
            return

        #print(f"{node.location.file}:{node.location.line} -- {node.type.spelling}")

        TYPES[name] = {}
        TYPES[name]["kind"] = "struct"
        TYPES[name]["size"] = node.type.get_size()
        TYPES[name]["alignment"] = node.type.get_align()

        output_type_fields(node, name)

    elif node.kind == cindex.CursorKind.CLASS_DECL:
        name = node.type.get_fully_qualified_name(policy=cindex.PrintingPolicy.create(node))
        if name in TYPES:
            return

        TYPES[name] = {}
        TYPES[name]["kind"] = "class"
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
    "bool",
}

def needs_output(name):
    return not (name in BUILTIN_TYPES or name in TYPES_OUTPUT)

def split_type_array(t):
    arr = ""
    if "[" in t:
        t, arr = t.split("[",1)
        arr = "[" + arr
    return t, arr

def get_prefix(t):
    prefix = ""
    if t in TYPES:
        if TYPES[t]["kind"] == "struct" or TYPES[t]["kind"] == "class":
            prefix = "struct "
    return prefix

def output_type(k):
    global TYPES_OUTPUT
    name = k
    entry = TYPES[k]

    if not needs_output(name):
        return
    TYPES_OUTPUT.add(name)

    ret = ""

    match entry["kind"]:
        case "typedef":
            t, arr = split_type_array(entry['real_type'])
            prefix = get_prefix(t)

            OUTPUT.append(f"typedef {prefix}{t} {name}{arr};")

        case "typedef_func":
            func_def = entry['real_type']
            if "(*)" in func_def:
                # typedef void (*ExitFunc)();
                func_def = func_def.replace("(*)", f"(*{name})")
            else:
                # doesn't contain the pointer, so also doesn't have ()
                # typedef void (tL2CA_UCD_DISCOVER_CB) (BD_ADDR, UINT8, UINT32);
                ret_args = func_def.split(' ',1)
                func_def = f"{ret_args[0]} {name}{ret_args[1]}"
            OUTPUT.append(f"typedef {func_def};")

        case "typedef_enum":
            OUTPUT.append(f"typedef {entry['real_type']} {name};")

        case "typedef_struct":
            t, arr = split_type_array(entry['real_type'])
            prefix = get_prefix(t)
            OUTPUT.append(f"typedef {prefix}{t} {name}{arr};")

        case "typedef_class":
            t, arr = split_type_array(entry['real_type'])
            prefix = get_prefix(t)
            OUTPUT.append(f"typedef {prefix}{t} {name}{arr};")

        case "enum":
            if name.startswith("__unnamed"):
                OUTPUT.append(f"enum {{")
            else:
                OUTPUT.append(f"enum {name} {{")

            for enum_entry in entry["fields"]:
                OUTPUT.append(f"{enum_entry['name']} = {enum_entry['value']},")

            OUTPUT.append("};")

        case "struct":
            OUTPUT.append(f"struct {name};")

        case "class":
            OUTPUT.append(f"struct {name};")

        #case _:
        #    print(f"Unhandled typedef type {entry['kind']}")
        #    exit()

for k in TYPES.keys():
    #print(f"{k} -- {TYPES[k]}")
    output_type(k)

#print("\n".join(OUTPUT))
out_path = Path(__file__).parent /  "structs.h"
out_path.write_text("\n".join(OUTPUT))
