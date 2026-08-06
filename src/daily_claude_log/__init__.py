try:
    from importlib.metadata import version

    __version__ = version("daily-claude-log")
except Exception:
    __version__ = "0.0.0+dev"
