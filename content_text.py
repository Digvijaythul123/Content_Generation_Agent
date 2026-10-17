import re


def clean_script(script):
    script = re.sub(
        r"\(Visual:.*?\)",
        "",
        script,
        flags=re.IGNORECASE | re.DOTALL,
    )
    script = re.sub(r"\(.*?\)", "", script)
    script = script.replace('"', "")
    return re.sub(r"\s+", " ", script.replace("\n", " ")).strip()


_HIGHLIGHT_PATTERN = re.compile(r"\*\*(.+?)\*\*")


def strip_highlights(text):
    """Remove **keyword** emphasis markers used by rendered post templates."""
    return _HIGHLIGHT_PATTERN.sub(r"\1", text).replace("**", "")
