"""Minimal S-expression reader/writer for KiCad files."""
import re

_TOKEN = re.compile(r'"(?:\\.|[^"\\])*"|\(|\)|[^\s()"]+')


def _unescape(t):
    out, i = [], 0
    while i < len(t):
        if t[i] == "\\" and i + 1 < len(t):
            out.append({"n": "\n", "t": "\t"}.get(t[i + 1], t[i + 1]))
            i += 2
        else:
            out.append(t[i])
            i += 1
    return "".join(out)


class Sym(str):
    """Bare (unquoted) atom."""


def parse(text):
    stack, cur = [], []
    for m in _TOKEN.finditer(text):
        t = m.group(0)
        if t == "(":
            stack.append(cur)
            cur = []
        elif t == ")":
            done = cur
            cur = stack.pop()
            cur.append(done)
        elif t[0] == '"':
            cur.append(_unescape(t[1:-1]))
        else:
            cur.append(Sym(t))
    return cur[0]


def dump(node, indent=0):
    if isinstance(node, list):
        simple = all(not isinstance(c, list) for c in node)
        if simple:
            return "(" + " ".join(dump(c) for c in node) + ")"
        pad = "\n" + "  " * (indent + 1)
        out = "(" + dump(node[0])
        for c in node[1:]:
            out += (pad + dump(c, indent + 1)) if isinstance(c, list) else (" " + dump(c))
        return out + "\n" + "  " * indent + ")"
    if isinstance(node, Sym):
        return str(node)
    if isinstance(node, str):
        return '"' + node.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'
    if isinstance(node, float):
        return ("%.4f" % node).rstrip("0").rstrip(".")
    return str(node)


def find(node, key):
    return [c for c in node[1:] if isinstance(c, list) and c and c[0] == key]


def first(node, key):
    r = find(node, key)
    return r[0] if r else None
