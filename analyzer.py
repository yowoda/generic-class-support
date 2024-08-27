# pyright: strict

import argparse
import inspect
import importlib
import os
import typing as t
from pathlib import Path

import ast

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

def _convert_to_module_path(path: Path, ext: str) -> str:
    return ".".join(path.parts).rstrip(ext)

def _log(message: str) -> None:
    if args.verbose is True:
        print(message)

def _get_ast(p: Path) -> ast.Module:
    with open(str(p)) as f:
        return ast.parse(f.read())

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
    generic_classes: list[str] = []

    class NodeVisitor(ast.NodeVisitor):
        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            if node.type_params:
                generic_classes.append(node.name)

    tree = _get_ast(path)
    visitor = NodeVisitor()
    visitor.visit(tree)

    return generic_classes

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

        class NodeVisitor(ast.NodeVisitor):
            types_import: str = ""
            __class_getitem__Node: t.Optional[ast.Assign]

            def visit_Module(self, node: ast.Module):
                pos: int = 0
                while pos < len(node.body):
                    stmt = node.body[pos]
                    if isinstance(stmt, ast.Import):
                        for alias in stmt.names:
                            if alias.name != "types":
                                break
                            
                            if alias.asname is not None:
                                self.types_import = alias.asname

                            else:
                                self.types_import = alias.name

                            self._Build__class_getitem_Node()

                    elif self.types_import == "":
                        self.types_import = "types"
                        node.body.insert(pos, ast.parse(f"import {self.types_import}").body[0])
                        pos += 1
                        self._Build__class_getitem_Node()

                    self.visit(stmt)
                    pos += 1

            def _Build__class_getitem_Node(self) -> None:
                self.__class_getitem__Node = t.cast(ast.Assign, ast.parse(f"__class_getitem__ = classmethod({self.types_import}.GenericAlias)").body[0])

            def visit_ClassDef(self, node: ast.ClassDef) -> None:
                if node.name in non_subscriptable_classes:
                    assert self.__class_getitem__Node is not None
                    node.body.append(self.__class_getitem__Node)

        visitor = NodeVisitor()
        visitor.visit(tree)
        with open(path_to_impl, "w") as f:
            f.write(ast.unparse(tree))

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