"""Download avatar checkpoints into the persistent model volume."""

from .engine import AvatarEngine


def main() -> None:
    engine = AvatarEngine()
    engine._ensure_models()
    print("Avatar model checkpoints are ready.")


if __name__ == "__main__":
    main()
