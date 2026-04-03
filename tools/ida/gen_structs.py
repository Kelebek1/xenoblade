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
            print(f"{i}{n.location.file}:{n.location.line}:{n.location.column}:", n.spelling, n.kind, n.type.kind, extra)
            print_all_children(n, indent + 1)
    print(f"{node.location.file}:{node.location.line}:{node.location.column}:", node.spelling, node.kind, node.type.kind)
    print_all_children(node, 1)

def is_builtin_type(type):
    return cindex.TypeKind.FIRSTBUILTIN.value <= type.kind.value <= cindex.TypeKind.LASTBUILTIN.value

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

def create_identifying_key(node):
    return f"{node.location.file}_{node.location.line}_{node.location.column}"

def get_type_hash(node):
    name_hash = hash(create_identifying_key(node))
    return f"0x{abs(int(name_hash)):X}"

def get_node_from_type(type):
    if type.kind in (cindex.TypeKind.POINTER, cindex.TypeKind.LVALUEREFERENCE):
        while type.kind in (cindex.TypeKind.POINTER, cindex.TypeKind.LVALUEREFERENCE, cindex.TypeKind.MEMBERPOINTER):
            type = type.get_pointee()
        type_node = type.get_declaration()
    elif type.kind in (cindex.TypeKind.CONSTANTARRAY, cindex.TypeKind.VECTOR, cindex.TypeKind.INCOMPLETEARRAY, cindex.TypeKind.VARIABLEARRAY):
        type_node = type.element_type.get_declaration()
    else:
        type_node = type.get_declaration()
    return type_node

def get_type_ida_name(node):
    if type(node) is cindex.Type:
        raw_type, raw_type_pointer_str = depointer_type(node)
        if is_builtin_type(raw_type):
            return f"{builtin_type_to_string(raw_type)}{raw_type_pointer_str}"
        node = get_node_from_type(node)

    raw_type, raw_type_pointer_str = depointer_type(node.type)

    if is_builtin_type(raw_type):
        return f"{builtin_type_to_string(raw_type)}{raw_type_pointer_str}"

    if node.location.file is None:
        return raw_type.spelling

    printing_policy = cindex.PrintingPolicy.create(node)
    name = raw_type.get_fully_qualified_name(policy=printing_policy)

    if "(unnamed" in name or "(anonymous" in name:
        name = f"__unnamed_{get_type_hash(node)}"

    return name

def get_name_ida_name(node, offset):
    name = node.spelling

    if not name or "(unnamed" in name or "(anonymous" in name:
        name = f"unk{offset:X}"

    return name

def fix_func_decl(t, n):
    if "(*)" in t:
        # typedef void (*ExitFunc)();
        t = t.replace("(*)", f"(*{n})")
    else:
        # doesn"t contain the pointer, so also doesn"t have ()
        # typedef void (tL2CA_UCD_DISCOVER_CB) (BD_ADDR, UINT8, UINT32);
        ret_args = t.split(" ",1)
        t = f"{ret_args[0]} {n}{ret_args[1]}"
    return t

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

def parse_funcproto(type):
    ret_type = type.get_result()
    args = []
    for arg in type.argument_types():
        arg_type, arg_pointer_str = depointer_type(arg)
        args.append(f"{arg_type.spelling}{arg_pointer_str}")
    return [ret_type, args]

def parse_field_decl(record_node, node, offset):
    def parse_typedef(type):
        return get_type_ida_name(type)

    def parse_funcproto(node):
        children = list(node.get_children())
        if node.has_children() and children[0].kind == cindex.CursorKind.TYPE_REF:
            ret_type = get_type_ida_name(children[0])
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
    #offset = record_node.type.get_offset(node.spelling) // 8
    extra = ""

    if is_builtin_type(base_type):
        type = builtin_type_to_string(base_type)
    else:
        match base_type.kind:
            case cindex.TypeKind.FUNCTIONPROTO:
                type, args = parse_funcproto(node)
                extra = f"({", ".join(args)});"

            case cindex.TypeKind.TYPEDEF:
                type = parse_typedef(base_type)

            case cindex.TypeKind.RECORD:
                type = get_type_ida_name(base_type)

            case cindex.TypeKind.CONSTANTARRAY:
                type, num_elements = parse_array(base_type)
                for dim in num_elements:
                    if dim == -1:
                        extra += f"[]"
                    else:
                        extra += f"[{dim}]"

            case cindex.TypeKind.INCOMPLETEARRAY:
                type, num_elements = parse_array(base_type)

                for dim in num_elements:
                    if dim == -1:
                        extra += f"[]"
                    else:
                        extra += f"[{dim}]"

            case cindex.TypeKind.ENUM:
                type = parse_typedef(base_type)

            case cindex.TypeKind.UNEXPOSED:
                template_decl = base_type.get_declaration()
                num_template_args = template_decl.get_num_template_arguments()
                if num_template_args > 0:
                    template_args = []
                    for template_index in range(num_template_args):
                        template_arg = base_type.get_template_argument_type(template_index)
                        template_arg, template_ptr_str = depointer_type(template_arg)
                        
                        template_str = template_arg.spelling
                        if not template_str:
                            template_str = f"{template_decl.get_template_argument_value(template_index)}"
                        if template_ptr_str:
                            template_str += "_p"
                        template_args.append(template_str)
                    type = f"{template_decl.spelling}__{"__".join(template_args)}"
                else:
                    print(f"{node.spelling} Unhandled parse_field_decl unexposed child type {children[0].kind}")
                    exit()

            case _:
                print("\n".join(OUTPUT))
                print(f"{base_type.spelling}: Unhandled parse_field_decl kind {base_type.kind}")
                exit()

    offset_comment = f"/* 0x{offset:0{record_num_digits}X} */"
    OUTPUT.append(f"{offset_comment} {type}{pointer_str} {get_name_ida_name(node, offset)}{extra};")

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

    OUTPUT.append(f"{record_type} __cppobj {get_type_ida_name(node)} {{")

    record_size = node.type.get_size()
    record_num_digits = len(f"{record_size:X}")

    bases = node.type.get_bases()
    total_size = 0
    for i,base in enumerate(bases):
        total_size = align_up(total_size, base.type.get_align())
        base_type_name = get_type_ida_name(base.type)

        match base.type.kind:
            case cindex.TypeKind.UNEXPOSED:
                template_decl = base.type.get_declaration()
                num_template_args = template_decl.get_num_template_arguments()
                if num_template_args > 0:
                    template_args = []
                    for template_index in range(num_template_args):
                        template_arg = template_decl.get_template_argument_type(template_index)
                        template_arg, template_ptr_str = depointer_type(template_arg)

                        template_str = template_arg.spelling
                        if not template_str:
                            template_str = f"{base.type.get_template_argument_value(template_index)}"
                        if template_ptr_str:
                            template_str += "_p"
                        template_args.append(template_str)
                    base_type_name = f"{template_decl.spelling}__{"__".join(template_args)}"

        decl = f"/* 0x{total_size:0{record_num_digits}X} */ {base_type_name} _base{i};"
        OUTPUT.append(decl)

        total_size += base.type.get_size()

    fields = []
    for field in node.type.get_fields():
        total_size = align_up(total_size, field.type.get_align())

        #print(f"\t", field.spelling, field.kind, field.type.kind)
        match field.kind:
            case cindex.CursorKind.FIELD_DECL:
                parse_field_decl(node, field, total_size)

            case _:
                print(f"{field.location.file}:{field.location.line}: {field.spelling}: Unhandled parse_record element type {field.kind}")
                exit()

        total_size += field.type.get_size()

    OUTPUT.append(f"}}; // size = 0x{record_size:0{record_num_digits}X}")

def parse_type(node, offset):
    out_type = {}

    out_type["name"] = get_name_ida_name(node, offset)
    out_type["type"] = get_type_ida_name(node)

    out_type["size"] = node.type.get_size()
    out_type["offset"] = offset

    out_type["is_pointer"] = node.type.kind is cindex.TypeKind.POINTER
    out_type["is_reference"] = node.type.kind is cindex.TypeKind.LVALUEREFERENCE

    out_type["is_array"] = node.type.kind is cindex.TypeKind.CONSTANTARRAY
    if out_type["is_array"]:
        out_type["num_elements"] = node.type.element_count

    out_type["is_bitfield"] = node.is_bitfield()
    if out_type["is_bitfield"]:
        out_type["bitfield_width"] = node.get_bitfield_width()

    return out_type

def parse_type_fields(node):
    def align_up(v, to):
        assert bin(to).count("1") == 1, f"alignment must be a power of 2!"
        return (v + to - 1) & ~(to - 1)

    fields = []
    total_size = 0
    for i,field in enumerate(node.type.get_fields()):
        total_size = align_up(total_size, field.type.get_align())

        field_info = parse_type(field, total_size)

        fields.append(field_info)

        if node.kind is not cindex.CursorKind.UNION_DECL:
            total_size += field_info["size"]

    return fields

def parse_typedef_decl(node):
    def parse_typedef(type):
        return get_type_ida_name(type)

    def parse_funcproto(node):
        children = list(node.get_children())
        if node.has_children() and children[0].kind == cindex.CursorKind.TYPE_REF:
            ret_type = get_type_ida_name(children[0])
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
            arg_type = f"{get_type_ida_name(child_node)}{parm_underlying_pointer_str}"
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

    key = create_identifying_key(node)
    if key in TYPES:
        return

    TYPES[key] = {}

    underlying_type, pointer_str = depointer_type(node.underlying_typedef_type)
    extra = ""

    #print(underlying_type.spelling, underlying_type.kind)

    if underlying_type.kind == cindex.TypeKind.UNEXPOSED:
        template_decl = underlying_type.get_declaration()
        num_template_args = template_decl.get_num_template_arguments()
        if num_template_args > 0:
            template_args = []
            for template_index in range(num_template_args):
                template_arg = underlying_type.get_template_argument_type(template_index)
                template_arg, template_ptr_str = depointer_type(template_arg)

                template_str = template_arg.spelling
                if not template_str:
                    template_str = f"{template_decl.get_template_argument_value(template_index)}"
                if template_ptr_str:
                    template_str += "_p"
                template_args.append(template_str)
            decl = f"typedef {template_decl.spelling}__{"__".join(template_args)} {get_type_ida_name(node)};"
            OUTPUT.append(decl)
        else:
            print(f"{node.spelling} Unhandled parse_typedef_decl unexposed child type {children[0].kind}")
            exit()
        return

    if is_builtin_type(underlying_type):
        decl = f"typedef {underlying_type.spelling} {get_type_ida_name(node)};"
        OUTPUT.append(decl)
        return

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

        case _:
            print("\n".join(OUTPUT))
            print(f"{node.location.file}:{node.location.line}: Unhandled parse_typedef_decl type {underlying_type.kind}")
            exit()

    if type == get_type_ida_name(node):
        return

    if pointer_str:
        OUTPUT.append(f"typedef {type} ({pointer_str}{get_type_ida_name(node)}){extra};")
    else:
        OUTPUT.append(f"typedef {type} {get_type_ida_name(node)}{extra};")

def parse_enum_decl(node):
    key = create_identifying_key(node)
    if key in TYPES:
        return
    TYPES[key] = {}

    OUTPUT.append(f"enum {get_type_ida_name(node)} {{")

    for child in node.get_children():
        match child.kind:
            case cindex.CursorKind.ENUM_CONSTANT_DECL:
                OUTPUT.append(f"{child.spelling} = {child.enum_value},")

            case _:
                print(f"{node.spelling} Unhandled parse_enum_decl unexposed child type {child.kind}")
                exit()

    OUTPUT.append(f"}};")

def parse_enum(node):
    key = create_identifying_key(node)
    if key in TYPES:
        return

    TYPES[key] = {}
    TYPES[key]["name"] = get_type_ida_name(node)
    TYPES[key]["kind"] = "enum"
    TYPES[key]["size"] = node.type.get_size()
    TYPES[key]["alignment"] = node.type.get_align()
    TYPES[key]["real_type"] = node.enum_type.spelling

    TYPES[key]["fields"] = []
    for child in node.get_children():
        enum_name = child.spelling
        enum_value = child.enum_value
        TYPES[key]["fields"].append({"name":enum_name, "value":enum_value})

def parse_union_decl(node):
    key = create_identifying_key(node)
    if key in TYPES:
        return
    TYPES[key] = {}

    for union_node in node.get_children():
        parse_node(union_node)

    parse_record(node)

def parse_union(node):
    key = create_identifying_key(node)
    if key in TYPES:
        return

    for union_node in node.get_children():
        parse_node(union_node)

    TYPES[key] = {}
    TYPES[key]["name"] = get_type_ida_name(node)
    TYPES[key]["kind"] = "union"
    TYPES[key]["size"] = node.type.get_size()
    TYPES[key]["alignment"] = node.type.get_align()
    TYPES[key]["fields"] = parse_type_fields(node)

def parse_struct_decl(node):
    key = create_identifying_key(node)
    if key in TYPES:
        return
    TYPES[key] = {}

    for struct_node in node.get_children():
        parse_node(struct_node)

    is_class = node.kind is cindex.CursorKind.CLASS_DECL

    parse_record(node)

def parse_struct(node, is_class):
    key = create_identifying_key(node)
    if key in TYPES:
        return

    for struct_node in node.get_children():
        parse_node(struct_node)

    TYPES[key] = {}
    TYPES[key]["name"] = get_type_ida_name(node)
    TYPES[key]["kind"] = "struct"
    TYPES[key]["size"] = node.type.get_size()
    TYPES[key]["alignment"] = node.type.get_align()
    TYPES[key]["fields"] = parse_type_fields(node)

def parse_node(node):
    if node.location.file is None:
        return

    #print_node(node)

    if node.kind == cindex.CursorKind.TYPEDEF_DECL:
        parse_typedef_decl(node)

    elif node.kind == cindex.CursorKind.ENUM_DECL:
        parse_enum_decl(node)

    elif node.kind == cindex.CursorKind.UNION_DECL:
        parse_union_decl(node)

    elif node.kind == cindex.CursorKind.STRUCT_DECL or node.kind == cindex.CursorKind.CLASS_DECL:
        parse_struct_decl(node)

    elif node.kind is cindex.CursorKind.CLASS_TEMPLATE:
        pass

    elif node.kind is cindex.CursorKind.NAMESPACE:
        for ns in node.get_children():
            parse_node(ns)

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

        """
        has_def = False
        if "dvderr" in str(file_path):
            has_def = True
        else:
            for node in unit.cursor.get_children():
                if "DVDErrorInfo" in node.spelling:
                    has_def = True
                    break;

        if has_def:
            print(node.location.file)
            for node in unit.cursor.get_children():
                print(f"{node.location.line}{node.location.column}:", node.spelling, node.kind, node.type.kind)
                for n in node.get_children():
                    print("\t", n.spelling, n.kind, n.type.kind)
                    for v in n.get_children():
                        print("\t\t", v.spelling, v.kind, v.type.kind)


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

print(f"Generating types...")

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

def get_c_prefix(t):
    prefix = ""
    if t in TYPES:
        if TYPES[t]["kind"] == "struct" or TYPES[t]["kind"] == "class":
            prefix = "struct "
    return prefix

def get_field_definition(field):
    field_name = field["name"]
    field_type = field["type"]

    arr = ""
    bf = ""
    ptr = ""
    #if field["is_pointer"]:
    #    ptr = "*"
    #elif field["is_reference"]:
    #    ptr = "&"
    if field["is_array"]:
        field_type, arr = split_type_array(field_type)
    elif field["is_bitfield"]:
        bf = f" : {field["bitfield_width"]}"
    elif "(" in field_type and field_type[-1] == ")":
        #print(f"Fixing {field_name} -- {field_type}")
        field_name = fix_func_decl(field_type, field_name)
        field_type = ""

    return f"{field_type}{ptr} {field_name}{bf}{arr}"

def output_union(k):
    entry = TYPES[k]
    name = entry["name"]

    OUTPUT.append(f"union {name} {{")

    size_hex = f"{entry["size"]:X}"
    num_hex_digits = len(size_hex)

    for field in entry["fields"]:
        decl = get_field_definition(field)
        OUTPUT.append(f"{decl};")

    OUTPUT.append(f"}}; // size = 0x{entry["size"]:0{num_hex_digits}X}")

def output_struct(k):
    entry = TYPES[k]
    name = entry["name"]

    OUTPUT.append(f"struct {name} {{")

    size_hex = f"{entry["size"]:X}"
    num_hex_digits = len(size_hex)

    for field in entry["fields"]:
        decl = get_field_definition(field)
        OUTPUT.append(f"/* 0x{field["offset"]:0{num_hex_digits}X} */ {decl};")

    OUTPUT.append(f"}}; // size = 0x{entry["size"]:0{num_hex_digits}X}")

def output_type(k):
    global TYPES_OUTPUT
    entry = TYPES[k]
    name = entry["name"]

    #print(k, "--", entry["name"])

    if not needs_output(name):
        return
    TYPES_OUTPUT.add(name)

    ret = ""

    match entry["kind"]:
        case "typedef":
            t, arr = split_type_array(entry["real_type"])
            c_prefix = get_c_prefix(t)

            OUTPUT.append(f"typedef {c_prefix}{t} {name}{arr};")

        case "typedef_func":
            func_def = fix_func_decl(entry["real_type"], name)
            OUTPUT.append(f"typedef {func_def};")

        case "typedef_enum":
            OUTPUT.append(f"typedef {entry["real_type"]} {name};")

        case "typedef_union":
            t, arr = split_type_array(entry["real_type"])
            c_prefix = get_c_prefix(t)
            OUTPUT.append(f"typedef {c_prefix}{t} {name}{arr};")

        case "typedef_struct":
            t, arr = split_type_array(entry["real_type"])
            c_prefix = get_c_prefix(t)
            OUTPUT.append(f"typedef {c_prefix}{t} {name}{arr};")

        case "typedef_class":
            t, arr = split_type_array(entry["real_type"])
            c_prefix = get_c_prefix(t)
            OUTPUT.append(f"typedef {c_prefix}{t} {name}{arr};")

        case "enum":
            OUTPUT.append(f"enum {name} {{")

            for enum_entry in entry["fields"]:
                OUTPUT.append(f"{enum_entry["name"]} = {enum_entry["value"]},")

            OUTPUT.append("};")

        case "union":
            output_union(k)

        case "struct":
            output_struct(k)

        case _:
            print(f"Unhandled typedef type {entry["kind"]}")
            exit()
"""
for k in TYPES.keys():
    #print(f"{k} -- {TYPES[k]}")
    output_type(k)
"""
#print("\n".join(OUTPUT))
out_path = Path(__file__).parent /  "structs.h"
out_path.write_text("\n".join(OUTPUT))
