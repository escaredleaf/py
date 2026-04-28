"""
Sample Python script for testing basic functionality.
"""

import sys
import platform
from datetime import datetime


def greet(name: str) -> str:
    return f"Hello, {name}! Welcome to Python."


def system_info() -> dict:
    return {
        "python_version": sys.version,
        "platform": platform.system(),
        "machine": platform.machine(),
        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def fizzbuzz(n: int) -> list:
    result = []
    for i in range(1, n + 1):
        if i % 15 == 0:
            result.append("FizzBuzz")
        elif i % 3 == 0:
            result.append("Fizz")
        elif i % 5 == 0:
            result.append("Buzz")
        else:
            result.append(str(i))
    return result


def simple_calculator(a: float, b: float, op: str) -> float:
    ops = {
        "+": lambda x, y: x + y,
        "-": lambda x, y: x - y,
        "*": lambda x, y: x * y,
        "/": lambda x, y: x / y if y != 0 else None,
    }
    fn = ops.get(op)
    if fn is None:
        raise ValueError(f"Unsupported operator: {op}")
    return fn(a, b)


if __name__ == "__main__":
    print("=" * 40)
    print(greet("Termux User"))
    print("=" * 40)

    info = system_info()
    for key, value in info.items():
        print(f"  {key}: {value}")

    print("\nFizzBuzz (1~20):")
    print(", ".join(fizzbuzz(20)))

    print("\nCalculator test:")
    for op in ["+", "-", "*", "/"]:
        result = simple_calculator(10, 3, op)
        print(f"  10 {op} 3 = {result}")

    print("\nDone.")
