"""
Detection package.

IMPORTANT: Do not auto-import all detectors on package import.
Some detectors have optional heavy dependencies (e.g. audio libs) that may not be present
in minimal runtime environments. Discovery is triggered lazily by `get_detector()`.
"""
