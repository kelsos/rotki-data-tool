# rotki-data-tool

A small python cli utility to help manage rotki data/accounts during development
## Installation

```bash
python -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

## Usage

To see what the utility can do run the following.

```bash
./tool --help
```

## Building

In order to build a single binary out of the tool you can do the following:

```bash
pyinstaller tool.spec
```

This will create a `account-sync` executable file in the `dist` directory that you can then use directly.

## License
[GPLv3](License.md)