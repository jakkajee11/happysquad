"""Prompt template rendering (spec §9.1): `{{var}}` -> str.replace, unknown -> (none)."""
import re

_VAR = re.compile(r"\{\{(\w+)\}\}")
# *_note variables are optional paragraphs: a line holding only an unset one is dropped, not "(none)"
_NOTE_LINE = re.compile(r"^\{\{(\w+_note)\}\}\n", re.M)


def render_text(text, variables):
    text = _NOTE_LINE.sub(lambda m: m.group(0) if variables.get(m.group(1)) else "", text)

    def sub(m):
        v = variables.get(m.group(1))
        if v is None or v == "" or v == []:
            return "(none)"
        if isinstance(v, (list, tuple)):
            return "\n".join("- %s" % x for x in v)
        return str(v)

    return _VAR.sub(sub, text)


def render_file(path, variables):
    with open(path) as f:
        return render_text(f.read(), variables)
