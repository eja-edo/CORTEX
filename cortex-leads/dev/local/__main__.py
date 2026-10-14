"""python -m dev.local {setup|serve}"""
import asyncio
import sys


def main(argv: list[str]) -> int:
    if len(argv) != 1 or argv[0] not in ("setup", "serve"):
        print("Cách dùng: python -m dev.local setup | serve")
        return 2
    sys.stdout.reconfigure(line_buffering=True)  # log ra file/pipe vẫn thấy ngay
    if argv[0] == "setup":
        from dev.local.setup import run
    else:
        from dev.local.serve import run
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
