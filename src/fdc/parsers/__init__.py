"""Parsers that turn local filing artifacts into typed contract drafts.

``fdc.parsers.edgartools_adapter`` wraps the pinned EdgarTools release; later
modules add the deterministic HTML/table parsers.  Nothing here imports
EdgarTools at module import time, and nothing written here may leak EdgarTools
model classes into the database layer.
"""
