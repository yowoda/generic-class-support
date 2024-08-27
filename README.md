# How it works:
The script goes through the given stub files and finds all generic classes. In this context, classes are generic if they specify type parameters using the new [type parameter syntax](https://docs.python.org/3/reference/compound_stmts.html#generic-classes) introduced in python 3.12. This doesn't neccessarily mean the script doesn't support python stub files written in python 3.11 or below. In that case make sure the stub files represent semantically correct python code and specify the `--runtime` flag when running the script. The script will then find generic classes in stub files by checking if they implement `__class_getitem__`. The same approached is used when checking if the implementation of the classes support type subscription.

Specify `--fix` to actually make the changes in the implementation files. Careful: This uses `ast.unparse` so comments and other info will  be lost.<br>
Specify `--verbose` to see which files are inspected, skipped or any other silent errors raised

Simply run `python analyzer.py dir1 dir2` to compare the implementation of classes in the directory `dir1` to the types in the directory `dir2`
Run `python analyzer.py file1 file2` to compare the implementation of classes in the file `file1` to the types in the file `file2`