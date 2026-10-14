"""Hand Clap - Fitz and the Tantrums (chorus / hook lines for alignment prompts)."""

# Short hook-centric lyric sheet used to bias ASR + select overlay phrases.
# Timing still comes from the audio model, not from these line breaks.
HANDCLAP_LYRICS = """
hand clap
hand clap
put your hands up
hand clap
hand clap
make your hands clap
put your hands up
hand clap
"""

# Phrases we flash on screen when ASR hears them (normalized lowercase match).
HOOK_PHRASES: tuple[str, ...] = (
    "hand clap",
    "hands clap",
    "make your hands clap",
    "put your hands up",
    "hands up",
)
