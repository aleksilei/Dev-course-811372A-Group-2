# Dev-course-811372A-Group-2

## Setup for local development

Create the python virtual environment
```bash
make venv
```

Install dependencies
```bash
make install
```

## Useful commands

There are quite many other useful make targets that can be checked with:
```bash
make help
```

### Tests / Linters

Run all checks **(Do this before committing)**
```bash
make check
```

Run pytests with
```bash
make test
```

You can run pylint and ruff with
```bash
make lint
```

or with the fix parameter for ruff (automagically fixes some issues)
```bash
make fix
```
