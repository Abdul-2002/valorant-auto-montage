"""
Effects package. Registration runs lazily via `src.effects.registry.discover_effects`
when resolving clip/audio/transition effects — not on `import src.effects`, so lightweight
subpackages (e.g. `presets`) can be imported without pulling optional runtime deps.
"""
