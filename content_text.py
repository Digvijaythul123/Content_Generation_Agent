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
