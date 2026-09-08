import argparse
import sys

from .config import Config


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m bot", description="Маркетолог iiko: Telegram-бот")
    ap.add_argument("--check", action="store_true", help="напечатать конфиг без секретов и выйти")
    args = ap.parse_args(argv)
    cfg = Config.from_env()
    if args.check:
        print(cfg.describe())
        return 0
    from .telegram import run

    return run(cfg)


if __name__ == "__main__":
    sys.exit(main())
