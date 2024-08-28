# How it works:
The script goes through the given stub files and finds all generic classes. In this context, classes are generic if they specify type parameters using the new [type parameter syntax](https://docs.python.org/3/reference/compound_stmts.html#generic-classes) introduced in python 3.12 or if they specify type variables in the list of classes they inherit from e.g. `typing.Generic[T]`. It's not guaranteed that the script will find all generic classes. If you want to make sure it catches every class that supports type subscripts you  can specify the `--runtime` flag. This will import the stub files at runtime (as long as they represent semantically correct python) and check whether the classes implement `__class_getitem__`. The same approach is used when checking if the implementation of the classes support type subscript.

Specify `--fix` to actually make the changes in the implementation files. The script will add type subscript support by adding the following line:<br>
```py
__class_getitem__ = classmethod(GenericAlias)
``` 
in the class body and an additional line
```py
from types import GenericAlias
```
In case it can't find a `GenericAlias` class. In case it does it will use the exact naming for the type subscript support.

Specify `--verbose` to see which files are inspected, skipped or any other silent errors raised.

The script uses [LibCST](https://github.com/Instagram/LibCST) internally to parse and format the files.
It's recommended you use [uv](https://docs.astral.sh/uv/) to run the script, it's as easy as:
```
uv run analyzer.py <path to impl> <path to stub>
```
uv will automatically figure out which python version to use and installs LibCST in case it's your first time running the script.
The paths should both either point to a valid directory or a valid file. You can't specify a directory AND a file path.