from functools import cache


@cache
def fibonacci(n: int) -> int:
    """Return the nth Fibonacci number (0-indexed).

    Uses memoization for O(n) time and O(n) space on first call,
    O(1) for subsequent calls with the same argument.

    Args:
        n: Non-negative integer index.

    Returns:
        The nth Fibonacci number.

    Raises:
        ValueError: If n is negative.
    """
    if n < 0:
        raise ValueError(f"n must be non-negative, got {n}")
    if n < 2:
        return n
    return fibonacci(n - 1) + fibonacci(n - 2)


def fibonacci_iterative(n: int) -> int:
    """Return the nth Fibonacci number using an iterative approach.

    O(n) time, O(1) space. Preferred for large n to avoid recursion limits.

    Args:
        n: Non-negative integer index.

    Returns:
        The nth Fibonacci number.

    Raises:
        ValueError: If n is negative.
    """
    if n < 0:
        raise ValueError(f"n must be non-negative, got {n}")
    a, b = 0, 1
    for _ in range(n):
        a, b = b, a + b
    return a
