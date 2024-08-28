# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "libcst",
# ]
# ///
# pyright: strict

import argparse
import inspect
import importlib
import os
import typing as t
from pathlib import Path

import libcst as cst

IGNORE_NAMES: t.Sequence[str] = (
    "__pycache__"
)

parser = argparse.ArgumentParser(
    "Runtime generics analyzer",
    description="Analyzes the support for runtime type subscription according to the given stub files"
)
parser.add_argument("path", help="A path to a directory or a file that contains the implementation of the classes that should be checked", type=Path)
parser.add_argument("stubs", help="A path to a directory or a file that contains the stub files of the given classes", type=Path)
parser.add_argument("-r", "--runtime", required=False, action="store_true", help="Whether to check the stub files at runtime")
parser.add_argument("-f", "--fix", required=False, action="store_true", help="Whether to fix the implementation")
parser.add_argument("-v", "--verbose", required=False, action="store_true", help="Explain what is being done")

args = parser.parse_args()

class GenericClassVisitor(cst.CSTVisitor):
    __slots__: t.Sequence[str] = ("_generic_class_names", "_typevar_name", "_typevars")

    def __init__(self) -> None:
        self._generic_class_names: list[str] = []
        self._typevar_name: str = ""
        self._typevars: list[str] = []

    @property
    def generic_class_names(self) -> list[str]:
        return self._generic_class_names

    def visit_Assign(self, node: cst.Assign) -> None:
        # Can't create a type variable if TypeVar wasn't imported
        if self._typevar_name == "": return

        if not isinstance(node.value, cst.Call):
            return
        
        var_name = t.cast(str, node.targets[0].target.value)
        
        func = node.value.func
        # Can't create a type variable using dot notation and from typing import TypeVar at the same time
        if isinstance(func, cst.Attribute):
            if "." not in self._typevar_name:
                return
            
            module, name = self._typevar_name.split(".")
            if (func.value.value, func.attr.value) == (module, name): # typevar call matches type var import
                self._typevars.append(var_name)

        elif isinstance(func, cst.Name):
            if func.value != self._typevar_name:
                return
            
            self._typevars.append(var_name)


    def visit_Import(self, node: cst.Import) -> None:
        name = self._find_TypeVar(node, "typing")
        if name is not None:
            self._typevar_name = f"{name}.TypeVar"
        
    def visit_ImportFrom(self, node: cst.ImportFrom):
        if node.module.value != "typing":
            return
        
        if isinstance(node.names, cst.ImportStar):
            self._typevar_name = "TypeVar"    

        else:
            name = self._find_TypeVar(node, "TypeVar")
            if name is not None:
                self._typevar_name = name

    def _find_TypeVar(self, node: t.Union[cst.Import, cst.ImportFrom], namespace: str) -> t.Optional[str]:
        assert not isinstance(node.names, cst.ImportStar)
        for alias in node.names:
            origin_name = t.cast(str, alias.name.value)
            if origin_name != namespace:
                continue

            if alias.asname is not None:
                origin_name = cst.ensure_type(alias.asname.name, cst.Name).value

            return origin_name

    def visit_ClassDef(self, node: cst.ClassDef) -> None:
        # class uses type parameter syntax so it's generic
        if node.type_parameters is not None:
            self._generic_class_names.append(node.name.value)

        else: # Check if the bases contain type subscripts using previously declared TypeVars
            for base in node.bases:
                if not isinstance(base.value, cst.Subscript):
                    continue

                slice_ = base.value.slice
                for subscript in slice_:
                    if subscript.slice.value.value in self._typevars:
                        self._generic_class_names.append(node.name.value)
                        return
                    

class FileTransformer(cst.CSTTransformer):
    __slots__: t.Sequence[str] = ("_generic_class_names", "_generic_alias_cls")

    def __init__(self, generic_class_names: list[str]) -> None:
        self._generic_class_names = generic_class_names
        self._generic_alias_cls: str = ""

    def visit_Import(self, node: cst.Import) -> None:
        name = self._find_GenericAlias(node, "types")
        if name is not None:
            self._generic_alias_cls = f"{name}.GenericAlias"
        
    def visit_ImportFrom(self, node: cst.ImportFrom):
        if node.module.value != "types":
            return
        
        if isinstance(node.names, cst.ImportStar):
            self._generic_alias_cls = "GenericAlias"    

        else:
            name = self._find_GenericAlias(node, "GenericAlias")
            if name is not None:
                self._generic_alias_cls = name

    def _find_GenericAlias(self, node: t.Union[cst.Import, cst.ImportFrom], namespace: str) -> t.Optional[str]:
        assert not isinstance(node.names, cst.ImportStar)
        for alias in node.names:
            origin_name = t.cast(str, alias.name.value)
            if origin_name != namespace:
                continue

            if alias.asname is not None:
                origin_name = cst.ensure_type(alias.asname.name, cst.Name).value

            return origin_name

    def leave_ClassDef(self, original_node: cst.ClassDef, updated_node: cst.ClassDef) -> t.Union[cst.ClassDef, cst.FlattenSentinel]:
        #print(dump(updated_node))
        if original_node.name.value in self._generic_class_names:
            _import_stmt: t.Optional[bool] = None

            if self._generic_alias_cls == "":
                _import_stmt = cst.parse_statement("from types import GenericAlias")
                self._generic_alias_cls = "GenericAlias"
                
            __class_getitem__Node = cst.parse_statement(
                f"__class_getitem__ = classmethod({self._generic_alias_cls})"
            )
            statements = original_node.body.body
            if isinstance(original_node.body, cst.SimpleStatementSuite):
                statements = [cst.SimpleStatementLine(statements)]

            updated_node = updated_node.with_changes(
                body=cst.IndentedBlock(
                    body=(
                        *statements,
                        __class_getitem__Node
                    )
                )
            )

            if _import_stmt is not None:
                return cst.FlattenSentinel((_import_stmt, updated_node))
        
        return updated_node

def _convert_to_module_path(path: Path, ext: str) -> str:
    return ".".join(path.parts).rstrip(ext)

def _log(message: str) -> None:
    if args.verbose is True:
        print(message)

def _get_ast(p: Path) -> cst.Module:
    with open(str(p)) as f:
        return cst.parse_module(f.read())

def _get_runtime_generic_classes(path: Path) -> list[str]:
    stubs_import_path = _convert_to_module_path(path, ".pyi")
    module = importlib.import_module(stubs_import_path)

    def predicate(obj: t.Any) -> bool:
        return (
            inspect.isclass(obj) 
            and getattr(obj, "__module__", "") == stubs_import_path
            and hasattr(obj, "__class_getitem__")
        )
    
    generic_classes: list[str] = [
        name for name, _ in inspect.getmembers(module, predicate)
    ]
    return generic_classes

def _get_ast_generic_classes(path: Path) -> list[str]:
    tree = _get_ast(path)
    visitor = GenericClassVisitor()
    tree.visit(visitor)

    return visitor.generic_class_names

if args.runtime:
    import sys
    from importlib.machinery import FileFinder, SourceFileLoader

    sys.path_hooks.insert(0, FileFinder.path_hook((SourceFileLoader, ['.pyi', '.py'])))
    get_generic_classes = _get_runtime_generic_classes
    
else:
    get_generic_classes = _get_ast_generic_classes

def compare_files(path_to_impl: Path, path_to_stub: Path, *, fix: bool) -> None:
    generic_classes = get_generic_classes(path_to_stub)
    if not generic_classes:
        _log(f"{path_to_stub} does not contain any generic classes. Skipping.")
        return
    
    _log(f"Found the following generic classes in {path_to_stub}: {', '.join(generic_classes)}")

    impl_import_path = _convert_to_module_path(path_to_impl, ".py")
    try:
        module = importlib.import_module(impl_import_path)

    except: 
        _log(f"Could not check runtime subscription support for {path_to_impl} ({impl_import_path}). Skipping.")
        return
    
    non_subscriptable_classes: list[str] = []

    for name, cls in inspect.getmembers(module, inspect.isclass):
        if cls.__module__ != impl_import_path:
            continue

        if hasattr(cls, "__class_getitem__") is False and name in generic_classes:
            non_subscriptable_classes.append(name)
            print(f"ERROR: {cls.__module__}.{cls.__qualname__} is marked as subscriptable in {path_to_stub} but is not subscriptable at runtime")

    if not non_subscriptable_classes:
        _log("All classes checked support subscription.")

    elif fix is True:
        _log(f"--fix is enabled, will be fixing the following classes: {', '.join(non_subscriptable_classes)}")
        tree = _get_ast(path_to_impl)
        visitor = FileTransformer(non_subscriptable_classes)
        modified_tree = tree.visit(visitor)
        with open(path_to_impl, "w") as f:
            f.write(modified_tree.code)

def compare_dirs(path_to_impl: Path, path_to_stub: Path, *, fix: bool) -> None:
    for p in path_to_stub.iterdir():
        name = os.sep.join(p.parts[len(path_to_stub.parts):])
        if name in IGNORE_NAMES:
            _log(f"{p} is __pycache__. Skipping.")
            continue

        if p.suffix == ".pyi":
            name = name.replace(p.suffix, ".py")

        impl_path = path_to_impl / name
        if impl_path.exists() is False:
            _log(f"ERROR: No matching implementation for stub file {p}, {impl_path} does not exist. Skipping.")  
            continue

        if p.is_dir() and impl_path.is_dir():
            compare_dirs(impl_path, p, fix=fix)

        elif p.is_file() and impl_path.is_file():
            compare_files(impl_path, p, fix=fix)

        else:
            _log(f"ERROR: Can't compare directory to file (comparing {p} with {impl_path} failed). Skipping.")
            continue


def main(path_to_impl: Path, path_to_stub: Path, *, fix: bool=False) -> None:
    if path_to_impl.is_dir() and path_to_stub.is_dir():
        compare_dirs(path_to_impl, path_to_stub, fix=fix)

    elif path_to_impl.is_file() and path_to_stub.is_file():
        compare_files(path_to_impl, path_to_stub, fix=fix)

    else:
        print("ERROR: Can't compare directory with file.")

main(args.path, args.stubs, fix=args.fix)