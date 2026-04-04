from functools import cache


@cache
def fibonacci(n: int) -> int:
    """Return the nth Fibonacci number (0-indexed).

    Uses memoized recursion for small n; iterative for large n to avoid stack overflow.

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

    # Iterative for large n to avoid recursion depth limits
    if n > 500:
        a, b = 0, 1
        for _ in range(n - 1):
            a, b = b, a + b
        return b

    return fibonacci(n - 1) + fibonacci(n - 2)
