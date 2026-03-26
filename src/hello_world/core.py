import sys


def greeting(name: str = "World") -> str:
    if not isinstance(name, str) or not name:
        raise ValueError("name must be a non-empty string")
    return f"Hello, {name}!"


def main() -> None:
    try:
        name = sys.argv[1] if len(sys.argv) > 1 else "World"
        print(greeting(name))
    except ValueError as e:
        print(e, file=sys.stderr)
        sys.exit(1)
