"""Allow running the marketing engine as a module: python -m marketing.scheduler"""

from .scheduler import run

if __name__ == "__main__":
    run()
