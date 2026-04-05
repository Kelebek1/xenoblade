import os
import sys
from pathlib import Path
import cindex

PROJECT_PATH = Path(Path(__file__).parent.parent.parent)
check_type = type

def get_ninja_sources():
    def parse_build(ninja, i):
        full_build_line = ninja[i].split(": ",1)[1]
        while "$" in ninja[i]:
            i += 1
            full_build_line += ninja[i]
        full_build_line = full_build_line.replace("$", "").split()

        if ".c" not in full_build_line[1] and ".cpp" not in full_build_line[1]:
            return None

        source_path = PROJECT_PATH / full_build_line[1]
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
                includes.append(PROJECT_PATH / f"{flags[j + 1]}")
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

files = get_ninja_sources()

#print(f"Found libclang at {clang_path}")
cindex.conf.set_library_path(clang_path)

TYPES = {}
TYPES_OUTPUT = set()
OUTPUT = []

def print_node(node):
    def print_all_children(node, indent):
        i = f"    " * indent
        for n in node.get_children():
            td = n.underlying_typedef_type if n.kind == cindex.CursorKind.TYPEDEF_DECL else None
            extra = ""
            if td:
                extra = f"{td.spelling} {td.kind} -- {td.get_declaration().spelling} {td.get_declaration().kind}"
            print(f"{i}{n.location.file}:{n.location.line}:{n.location.column}:", n.spelling, n.kind, n.type.kind, extra, f"children:{len(list(n.get_children()))}")
            print_all_children(n, indent + 1)
    print(f"{node.location.file}:{node.location.line}:{node.location.column}:", node.spelling, node.kind, node.type.kind, f"children:{len(list(node.get_children()))}")
    print_all_children(node, 1)

def depointer_type(type):
    pointer_str = ""
    while type.kind in (cindex.TypeKind.POINTER, cindex.TypeKind.LVALUEREFERENCE, cindex.TypeKind.MEMBERPOINTER):
        match type.kind:
            case cindex.TypeKind.POINTER:
                pointer_str += "*"
            case cindex.TypeKind.LVALUEREFERENCE:
                pointer_str += "&"
            case cindex.TypeKind.MEMBERPOINTER:
                pointer_str += "*"
        type = type.get_pointee()
    return (type, pointer_str)

BUILTINS = {
    "void",
    "bool",
    "unsigned char",
    "unsigned char",
    "char16_t",
    "char32_t",
    "unsigned short",
    "unsigned int",
    "unsigned long",
    "unsigned long long",
    "unsigned __int128",
    "signed char",
    "signed char",
    "wchar_t",
    "signed short",
    "signed int",
    "signed long",
    "signed long long",
    "signed __int128",
    "float",
    "double",
    "long double",
    "nullptr_t",
}

def are_builtin_types_the_same(base1, base2):
    if " " not in base1 and " " not in base2:
        return base1 == base2

    if " " not in base1 and base1 in ("char", "int", "short", "long", "__int128"):
        base1 = f"signed {base1}"

    if " " not in base2 and base2 in ("char", "int", "short", "long", "__int128"):
        base2 = f"signed {base2}"

    return base1 == base2

def is_builtin_type(type):
    return cindex.TypeKind.FIRSTBUILTIN.value <= type.kind.value <= cindex.TypeKind.LASTBUILTIN.value

def builtin_type_to_ida_string(type, remove_spaces=False):
    def builtin_type_to_string(type):
        match type.kind:
            case cindex.TypeKind.VOID:
                return "void"
            case cindex.TypeKind.BOOL:
                return "bool"
            case cindex.TypeKind.CHAR_U:
                return "unsigned char"
            case cindex.TypeKind.UCHAR:
                return "unsigned char"
            case cindex.TypeKind.CHAR16:
                return "char16_t"
            case cindex.TypeKind.CHAR32:
                return "char32_t"
            case cindex.TypeKind.USHORT:
                return "unsigned short"
            case cindex.TypeKind.UINT:
                return "unsigned int"
            case cindex.TypeKind.ULONG:
                return "unsigned long"
            case cindex.TypeKind.ULONGLONG:
                return "unsigned long long"
            case cindex.TypeKind.UINT128:
                return "unsigned __int128"
            case cindex.TypeKind.CHAR_S:
                return "signed char"
            case cindex.TypeKind.SCHAR:
                return "signed char"
            case cindex.TypeKind.WCHAR:
                return "wchar_t"
            case cindex.TypeKind.SHORT:
                return "signed short"
            case cindex.TypeKind.INT:
                return "signed int"
            case cindex.TypeKind.LONG:
                return "signed long"
            case cindex.TypeKind.LONGLONG:
                return "signed long long"
            case cindex.TypeKind.INT128:
                return "signed __int128"
            case cindex.TypeKind.FLOAT:
                return "float"
            case cindex.TypeKind.DOUBLE:
                return "double"
            case cindex.TypeKind.LONGDOUBLE:
                return "long double"
            case cindex.TypeKind.NULLPTR:
                return "nullptr_t"
            case _:
                assert False
                print(f"Unhandled built-in type {type.kind} from {type.spelling}")
                exit()
    s = builtin_type_to_string(type)
    if remove_spaces:
        s = s.replace(" ", "_")
    return s

def create_identifying_key(node):
    return f"{node.location.file}_{node.location.line}_{node.location.column}"

def get_type_hash(node):
    name_hash = hash(create_identifying_key(node))
    return f"{abs(int(name_hash)):X}"

def get_node_from_type(type):
    type, _ = depointer_type(type)
    if is_builtin_type(type):
        return None
    if type.kind in (cindex.TypeKind.POINTER, cindex.TypeKind.LVALUEREFERENCE):
        while type.kind in (cindex.TypeKind.POINTER, cindex.TypeKind.LVALUEREFERENCE, cindex.TypeKind.MEMBERPOINTER):
            type = type.get_pointee()
        type_node = type.get_declaration()
    elif type.kind in (cindex.TypeKind.CONSTANTARRAY, cindex.TypeKind.VECTOR, cindex.TypeKind.INCOMPLETEARRAY, cindex.TypeKind.VARIABLEARRAY):
        type_node = type.element_type.get_declaration()
    elif type.kind in (cindex.TypeKind.FUNCTIONPROTO, cindex.TypeKind.FUNCTIONNOPROTO):
        return None
    else:
        type_node = type.get_declaration()
        if type_node.type.kind is cindex.TypeKind.TYPEDEF:
            type_node = get_node_from_type(type_node.underlying_typedef_type)
            #if type_node:
            #    print(f"get_node_from_type", type.kind, "into", type_node.kind, type_node.type.kind)
    return type_node

def get_full_qualified_name(node):
    printing_policy = cindex.PrintingPolicy.create(node)
    return node.type.get_fully_qualified_name(policy=printing_policy)

def is_type_template(type):
    return type.get_num_template_arguments() > 0

def get_type_ida_name(type):
    def fix_type_string(name):
        if not name:
            return ""

        while "(anonymous namespace)" in name:
            name = name.replace("::(anonymous namespace)::", "")
            name = name.replace("(anonymous namespace)::", "")
            name = name.replace("::(anonymous namespace)", "")

        if "(unnamed" in name or "(anonymous" in name:
            name = f"__unnamed_{get_type_hash(type_node)}"

        #print(f"new name: {name}", "type_node:", type_node.spelling, type_node.kind, type_node.type.kind)

        if name.startswith("const "):
            name = name[len("const "):]
        if name.startswith("volatile "):
            name = name[len("volatile "):]

        name = name.replace("<", "__")
        name = name.replace(">", "__")

        while name[-1] in ("*", "&"):
            name = name[:-1]

        if name.endswith(" "):
            name = name[:-1]
        return name

    def fix_type_ida_name(type_node):
        def get_template_args(node):
            num_template_args = node.get_num_template_arguments()
            #print(f"{node.canonical.spelling} Has {num_template_args} template args")
            if num_template_args > 0:
                template_args = []
                for template_index in range(num_template_args):
                    template_arg = node.get_template_argument_type(template_index)
                    template_arg, template_ptr_str = depointer_type(template_arg)
                    template_str = get_type_ida_name(template_arg.get_canonical())
                    template_str = template_str.replace(" ", "_")
                    #print(f"Template arg {template_index} = {template_arg.spelling} {template_arg.kind}, ret str {template_str}")

                    if is_type_template(template_arg):
                        template_str = get_template_args(get_node_from_type(template_arg))
                    else:
                        if not template_str:
                            template_str = f"{node.get_template_argument_value(template_index)}"
                        if template_ptr_str:
                            template_str += "_p"
                    template_str = template_str.replace("::(anonymous namespace)::", "")
                    template_str = template_str.replace("(anonymous namespace)::", "")
                    template_args.append(template_str)
                return f"{node.spelling}__{"__".join(template_args)}"
            return node.spelling

        #print()
        #print(f"first name:", name, "type_node:", type_node.spelling, type_node.kind, type_node.type.kind)

        if type_node.kind in (cindex.CursorKind.STRUCT_DECL, cindex.CursorKind.CLASS_DECL) and type_node.get_num_template_arguments() > 0:
            name = get_template_args(type_node)
            #print(f"template args return: {name}")
        else:
            name = get_full_qualified_name(type_node)
        return fix_type_string(name)

    assert check_type(type) == cindex.Type, f""

    #print(f"Going into get_node with", type.spelling, type.kind)
    type, type_ptr_str = depointer_type(type)
    type_node = get_node_from_type(type)
    if not type_node or type_node.type.kind is cindex.TypeKind.INVALID:
        #print(f"Failed to get a node:", type.spelling, type.kind)
        if is_builtin_type(type):
            return f"{builtin_type_to_ida_string(type)}{type_ptr_str}"
        return fix_type_string(type.spelling)

    #print(f"Got a node:", type_node.spelling, type_node.kind, type_node.type.kind)

    if is_builtin_type(type_node.type):
        return f"{builtin_type_to_ida_string(type_node.type)}{raw_type_pointer_str}"

    if type_node.location.file is None:
        return type_node.type.spelling

    return fix_type_ida_name(type_node)

def get_variable_name_ida_name(node, offset):
    name = node.spelling

    #print(f"full name:", name)

    if not name:
        name = f"unk_{offset:X}"
    elif "(unnamed" in name or "(anonymous" in name:
        name = f"unnamed_{offset:X}"

    #print(f"final name", name)
    return name

def parse_funcproto(type):
    ret_type = type.get_result()
    args = []
    for arg in type.argument_types():
        arg_type, arg_pointer_str = depointer_type(arg)
        args.append(f"{arg_type.spelling}{arg_pointer_str}")
    return [ret_type, args]

def parse_field_decl(record_node, node, offset):
    def parse_funcproto(node):
        children = list(node.get_children())
        if node.has_children() and children[0].kind == cindex.CursorKind.TYPE_REF:
            ret_type = get_type_ida_name(children[0].type)
            children = children[1:]
        else:
            ret_type = "void"

        func_args = []
        for child in children:
            assert child.kind == cindex.CursorKind.PARM_DECL, f"{node.spelling} typedef func argument {child.spelling} is not a PARM_DECL? It's a {child.kind}"
            if child.has_children():
                arg_type = next(child.get_children()).type.spelling
            else:
                # builtin type so clang refuses to emit a node for it...
                parm_underlying_type, parm_underlying_pointer_str = depointer_type(child.type)
                arg_type = f"{get_type_ida_name(parm_underlying_type)}{parm_underlying_pointer_str}"
            func_args.append(f"{arg_type} {child.spelling}")

        return (ret_type, func_args)

    def parse_array(type):
        #print(f"parse_array", type.spelling, type.kind)
        num_elements = []
        while type.kind in (cindex.TypeKind.CONSTANTARRAY, cindex.TypeKind.INCOMPLETEARRAY):
            if type.kind is cindex.TypeKind.INCOMPLETEARRAY:
                num_elements.append(-1)
            else:
                num_elements.append(type.element_count)
            type = type.element_type

        return (get_type_ida_name(type), num_elements)

    record_size = record_node.type.get_size()
    record_num_digits = len(f"{record_size:X}")

    base_type, pointer_str = depointer_type(node.type)
    extra = ""

    """
    if node.spelling == "tmp":
        print_node(record_node)
        print()
        print_node(node)
        print()
        print(base_type.spelling, base_type.kind)
        print(get_full_qualified_name(node))

        exit()
    """

    if is_builtin_type(base_type):
        type = builtin_type_to_ida_string(base_type)
    else:
        try_parse_node_from_type(base_type)

        match base_type.kind:
            case cindex.TypeKind.FUNCTIONPROTO:
                type, args = parse_funcproto(node)
                extra = f"({", ".join(args)});"

            case cindex.TypeKind.TYPEDEF:
                type = get_type_ida_name(base_type)

            case cindex.TypeKind.RECORD:
                type = get_type_ida_name(base_type)

            case cindex.TypeKind.CONSTANTARRAY:
                try_parse_node_from_type(base_type.element_type)

                type, num_elements = parse_array(base_type)
                for dim in num_elements:
                    if dim == -1:
                        extra += f"[]"
                    else:
                        extra += f"[{dim}]"

            case cindex.TypeKind.INCOMPLETEARRAY:
                try_parse_node_from_type(base_type.element_type)

                type, num_elements = parse_array(base_type)

                for dim in num_elements:
                    if dim == -1:
                        extra += f"[]"
                    else:
                        extra += f"[{dim}]"

            case cindex.TypeKind.ENUM:
                type = get_type_ida_name(base_type)

            case cindex.TypeKind.UNEXPOSED:
                type = get_type_ida_name(base_type)

                if is_type_template(base_type):
                    for template_index in range(base_type.get_num_template_arguments()):
                        template_arg = base_type.get_template_argument_type(template_index)
                        try_parse_node_from_type(template_arg)
                        #print(f"{node.spelling} template {template_index}: {template_arg.spelling}, {template_arg.kind}")
                else:
                   #print_node(record_node)
                   #print(record_node.get_num_template_arguments())
                   #print()

                    arg_matched = False
                    num_record_templates = record_node.get_num_template_arguments()
                    for record_template_index in range(num_record_templates):
                        record_template_arg = record_node.get_template_argument_type(record_template_index)
                        template_type, template_pointer_str = depointer_type(record_template_arg)
                        record_template_arg_str = get_type_ida_name(template_type)
                        #print(f"{record_node.spelling} {node.spelling} Checking \"{type}\" against \"{record_template_arg_str}\"")

                        if type == record_template_arg_str or are_builtin_types_the_same(type, record_template_arg_str):
                            arg_matched = True
                            try_parse_node_from_type(template_type)

                            type = record_template_arg_str
                            pointer_str = template_pointer_str
                            #print(f"New template type {type}{pointer_str}")
                            break

                    if not arg_matched:
                        print(f"{record_node.spelling}: {node.spelling} {base_type.kind} Failed to match template arg \"{type}\"")
                        exit()
            case _:
                print(f"{base_type.spelling}: Unhandled parse_field_decl kind {base_type.kind}")
                exit()

    offset_comment = f"/* 0x{offset:0{record_num_digits}X} */"
    return f"{offset_comment} {type}{pointer_str} {get_variable_name_ida_name(node, offset)}{extra};"

def parse_record(node):
    def align_up(v, to):
        assert bin(to).count("1") == 1, f"alignment must be a power of 2!"
        return (v + to - 1) & ~(to - 1)

    #print(f"Parsing record:", node.spelling, node.kind, node.type.kind)

    match node.kind:
        case cindex.CursorKind.STRUCT_DECL:
            record_type = "struct"
        case cindex.CursorKind.CLASS_DECL:
            record_type = "class"
        case cindex.CursorKind.UNION_DECL:
            record_type = "union"
        case _:
            print(f"Unhandled record type {node.kind}")
            exit()

    record_name = get_type_ida_name(node.type)

    to_output = []
    to_output.append(f"{record_type} __cppobj {record_name} {{")

    record_size = node.type.get_size()
    record_num_digits = len(f"{record_size:X}")

    bases = node.type.get_bases()
    total_size = 0
    for i,base in enumerate(bases):
        total_size = align_up(total_size, base.type.get_align())

        base_decl = base.type.get_declaration()
        assert base_decl.kind in (cindex.CursorKind.STRUCT_DECL, cindex.CursorKind.CLASS_DECL, cindex.CursorKind.TYPEDEF_DECL), f"Record base template kind unknown: {base_decl.kind}"
        #print(base.spelling, base.kind, base.type.kind, "---", base_decl.spelling, base_decl.kind, base_decl.type.kind)
        parse_node(base_decl)

        base_type_name = get_type_ida_name(base.type)
        decl = f"/* 0x{total_size:0{record_num_digits}X} */ {base_type_name} _base{i};"
        to_output.append(decl)

        total_size += base.type.get_size()

    fields = []
    for field in node.type.get_fields():
        total_size = align_up(total_size, field.type.get_align())
        """
        if "reslist" in node.spelling:
            print()
            print_node(field)
            print(field.spelling, field.type.spelling, field.type.kind)
            base_type, pointer_str = depointer_type(field.type)
            print(base_type.spelling, base_type.kind)
        """
        #print(f"\t", field.spelling, field.kind, field.type.kind)
        match field.kind:
            case cindex.CursorKind.FIELD_DECL:
                to_output.append(parse_field_decl(node, field, total_size))

            case _:
                print(f"{field.location.file}:{field.location.line}: {field.spelling}: Unhandled parse_record element type {field.kind}")
                exit()

        total_size += field.type.get_size()

    #if "reslist" in node.spelling:
    #    exit()

    to_output.append(f"}}; // size = 0x{record_size:0{record_num_digits}X}")
    OUTPUT.extend(to_output)

def parse_typedef_decl(node):
    def parse_typedef(type):
        return get_type_ida_name(type)

    def parse_funcproto(node):
        children = list(node.get_children())
        if node.has_children() and children[0].kind == cindex.CursorKind.TYPE_REF:
            ret_type = get_type_ida_name(children[0].type)
            children = children[1:]
        else:
            ret_type = "void"

        func_args = []
        for child in children:
            assert child.kind == cindex.CursorKind.PARM_DECL, f"{node.spelling} typedef func argument {child.spelling} is not a PARM_DECL? It's a {child.kind}"
            if child.has_children():
                child_node = next(child.get_children())
            else:
                # builtin type so clang refuses to emit a node for it...
                child_node = child
            parm_underlying_type, parm_underlying_pointer_str = depointer_type(child.type)
            arg_type = f"{get_type_ida_name(child_node.type)}{parm_underlying_pointer_str}"
            func_args.append(f"{arg_type} {child.spelling}")
        return (ret_type, func_args)

    def parse_array(type):
        num_elements = []
        while type.kind in (cindex.TypeKind.CONSTANTARRAY, cindex.TypeKind.INCOMPLETEARRAY):
            if type.kind is cindex.TypeKind.INCOMPLETEARRAY:
                num_elements.append(-1)
            else:
                num_elements.append(type.element_count)
            type = type.element_type

        return (type.spelling, num_elements)

    underlying_type, pointer_str = depointer_type(node.underlying_typedef_type)
    extra = ""

    #print_node(node)
    #print(underlying_type.spelling, underlying_type.kind)

    if underlying_type.kind is cindex.TypeKind.UNEXPOSED:
        template_decl = underlying_type.get_declaration()
        assert template_decl.kind in (cindex.CursorKind.STRUCT_DECL, cindex.CursorKind.CLASS_DECL), f"Typedef template kind unknown: {template_decl.kind}"
        parse_node(template_decl)

    if is_builtin_type(underlying_type):
        decl = f"typedef {underlying_type.spelling} {get_type_ida_name(node.type)};"
        OUTPUT.append(decl)
        return

    try_parse_node_from_type(underlying_type)

    match underlying_type.kind:
        case cindex.TypeKind.FUNCTIONPROTO:
            type, func_args = parse_funcproto(node)
            extra = f"({", ".join(func_args)})"

        case cindex.TypeKind.FUNCTIONNOPROTO:
            type, func_args = parse_funcproto(node)
            extra = f"({", ".join(func_args)})"

        case cindex.TypeKind.TYPEDEF:
            #print(node.location.file, node.location.line, underlying_type.spelling)
            type = parse_typedef(underlying_type)
            """
            #print(type)
            if "ALLOC_HANDLE" in node.spelling:
                print(get_full_qualified_name(node))
                exit()
            """

        case cindex.TypeKind.CONSTANTARRAY:
            type, element_dims = parse_array(underlying_type)
            extra = ""
            for dim in element_dims:
                extra += f"[{dim}]"

        case cindex.TypeKind.INCOMPLETEARRAY:
            type, element_dims = parse_array(underlying_type)
            extra = ""
            for dim in element_dims:
                if dim == -1:
                    extra += f"[]"
                else:
                    extra += f"[{dim}]"

        case cindex.TypeKind.RECORD:
            type = parse_typedef(underlying_type)

        case cindex.TypeKind.ENUM:
            type = underlying_type.spelling

        case cindex.TypeKind.UNEXPOSED:
            type = get_type_ida_name(underlying_type)

        case _:
            print(f"{node.location.file}:{node.location.line}: Unhandled parse_typedef_decl type {underlying_type.kind}")
            exit()

    name = get_full_qualified_name(node)

    if pointer_str:
        OUTPUT.append(f"typedef {type} ({pointer_str}{name}){extra};")
    else:
        OUTPUT.append(f"typedef {type} {name}{extra};")

def parse_enum_decl(node):
    OUTPUT.append(f"enum {get_type_ida_name(node.type)} {{")

    for child in node.get_children():
        match child.kind:
            case cindex.CursorKind.ENUM_CONSTANT_DECL:
                OUTPUT.append(f"{child.spelling} = {child.enum_value},")

            case _:
                print(f"{node.spelling} Unhandled parse_enum_decl unexposed child type {child.kind}")
                exit()

    OUTPUT.append(f"}};")

def parse_union_decl(node):
    for union_node in node.get_children():
        parse_node(union_node)

    parse_record(node)

def parse_struct_decl(node):
    for struct_node in node.get_children():
        parse_node(struct_node)

    parse_record(node)

CURRENT_NAMESPACES = []

def parse_node(node):
    if node.location.file is None:
        return

    #print(node.spelling, node.kind, node.type.kind)
    if node.kind not in (cindex.CursorKind.TYPEDEF_DECL, cindex.CursorKind.ENUM_DECL, 
                         cindex.CursorKind.UNION_DECL, cindex.CursorKind.STRUCT_DECL, 
                         cindex.CursorKind.CLASS_DECL, cindex.CursorKind.NAMESPACE):
        return

    if node.kind is not cindex.CursorKind.NAMESPACE:
        name = get_type_ida_name(node.type)
        #print(f"{name} --", node.spelling, node.kind, node.type.spelling, node.type.kind)
        if name in TYPES_OUTPUT:
            #print(f"OLD {name} --", node.location.file, node.location.line, node.spelling, node.kind, node.type.spelling, node.type.kind)
            return
        #print(f"NEW {name} --", node.location.file, node.location.line, node.spelling, node.kind, node.type.spelling, node.type.kind)
        TYPES_OUTPUT.add(name)
    #print_node(node)

    if node.kind == cindex.CursorKind.TYPEDEF_DECL:
        parse_typedef_decl(node)

    elif node.kind == cindex.CursorKind.ENUM_DECL:
        parse_enum_decl(node)

    elif node.kind == cindex.CursorKind.UNION_DECL:
        parse_union_decl(node)

    elif node.kind == cindex.CursorKind.STRUCT_DECL or node.kind == cindex.CursorKind.CLASS_DECL:
        parse_struct_decl(node)

    elif node.kind is cindex.CursorKind.NAMESPACE:
        CURRENT_NAMESPACES.append(node.spelling)
        #print()
        #print(f"RECURSING into {"::".join(CURRENT_NAMESPACES)}")
        for ns in node.get_children():
            parse_node(ns)

        #print(f"RECURSING out of {"::".join(CURRENT_NAMESPACES)}")
        #print()
        CURRENT_NAMESPACES.pop(-1)

def try_parse_node_from_type(type):
    type_node = get_node_from_type(type)
    if not type_node:
        return

    parse_node(type_node)

def parse_files(files, index):
    def parse_file(file):
        nonlocal index

        file_path = file["path"]
        compile_includes = file["compile_include_paths"]
        compile_lang = file["compile_lang"]

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

            include_path_str = str(PROJECT_PATH / include_path)
            #print(f"\tFound {include_path_str}")
            if include_path_str not in files:
                #print(f"Found include {include_path}, parsing")
                files[include_path_str] = {"path":PROJECT_PATH / include_path, "compile_include_paths":compile_includes, "compile_lang":compile_lang}
                inc_unit = parse_file(files[include_path_str])
                for node in inc_unit.cursor.get_children():
                    parse_node(node)
            """

        return unit

    base_files = list(files.keys())

    for file_path in base_files:
        unit = parse_file(files[file_path])
        for node in unit.cursor.get_children():
            parse_node(node)

print(f"Parsing all files...")
index = cindex.Index.create()
parse_files(files, index)

#print(TYPES)
#print(OUTPUT)

out_path = Path(__file__).parent /  "structs.h"
out_path.write_text("\n".join(OUTPUT))
