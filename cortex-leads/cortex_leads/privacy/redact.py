"""PII masking before anything reaches an LLM or a log (DESIGN N2)."""
import re
import unicodedata
from dataclasses import dataclass, field

# VN mobile/landline: 0xxxxxxxxx or +84xxxxxxxxx, optionally split by space/dot/dash.
_PHONE = re.compile(r"(?<![\d+])(?:\+84(?:[ .\-]?\d){9}|0(?:[ .\-]?\d){9})(?!\d)")
_EMAIL = re.compile(r"[\w.+\-]+@[\w\-]+(?:\.[\w\-]+)+")


_HONORIFICS = ("anh", "chi", "em", "co", "chu", "bac", "ban", "a", "c", "e", "mr", "ms")
# "em là Hà", "mình tên Nguyễn Thu Hà", "tôi là anh Minh": a name the platform never gave us (R51).
_SELF_INTRO = re.compile(r"(?i:\b(?:em|mình|tôi|tớ|chị|anh|con|cháu)\s+(?:tên\s+là|tên|là)\s+"
                         r"(?:(?:anh|chị|em|cô|chú)\s+)?)((?:[^\W\d_]+\s*){1,4})")


def _self_named(text: str) -> list[str]:
    """Capitalised words right after a self-introduction: "là học sinh" is not a name, "là Hà" is."""
    found = []
    for m in _SELF_INTRO.finditer(text):
        words = []
        for w in m.group(1).split():
            if not w[0].isupper():
                break
            words.append(w)
        if words:
            found.append(" ".join(words))
    return found


def _fold(text: str) -> str:
    """Lowercase + strip Vietnamese diacritics, one output char per input char (spans line up)."""
    out = []
    for ch in unicodedata.normalize("NFC", text):
        base = "d" if ch in "đĐ" else unicodedata.normalize("NFD", ch)[0]
        out.append(base.lower())
    return "".join(out)


def _mask_names(text: str, known_names: list[str], repl) -> str:
    """Masks the full name and the given name (last token), optionally preceded by an honorific
    ("chị An", "a An"), ignoring case and diacritics. Known false positive: a given name that is
    also a common word ("An") masks "an toàn" too; leaking a name is worse than over-masking."""
    variants: dict[str, str] = {}  # folded variant -> folded full name (one placeholder per person)
    for raw in known_names:
        full = " ".join(_fold(raw or "").split())
        if len(full) < 2:
            continue
        variants[full] = full
        given = full.split()[-1]
        if len(given) >= 2 and given not in _HONORIFICS:
            variants.setdefault(given, full)
    if not variants:
        return text
    text = unicodedata.normalize("NFC", text)
    names = "|".join(re.escape(v).replace(r"\ ", r"\s+") for v in sorted(variants, key=len, reverse=True))
    pat = re.compile(rf"(?<!\w)(?:(?:{'|'.join(_HONORIFICS)})\s+)?({names})(?!\w)")
    folded, out, last = _fold(text), [], 0
    for m in pat.finditer(folded):
        # repl() needs a match object over the original text; reuse the same span.
        orig = re.compile(re.escape(text[m.start():m.end()])).match(text, m.start())
        out += [text[last:m.start()], repl(orig)]
        last = m.end()
    return "".join(out) + text[last:]


@dataclass(frozen=True)
class RedactResult:
    text: str
    mapping: dict[str, str] = field(default_factory=dict)  # placeholder -> original


def redact(text: str, known_names: list[str] | None = None) -> RedactResult:
    mapping: dict[str, str] = {}
    seen: dict[tuple[str, str], str] = {}

    def sub(kind: str):
        def _repl(m: re.Match[str]) -> str:
            original = m.group(0)
            key = (kind, re.sub(r"\D", "", original) if kind == "PHONE" else original.lower())
            if key not in seen:
                n = sum(1 for k in seen if k[0] == kind) + 1
                seen[key] = f"[{kind}_{n}]"
                mapping[seen[key]] = original
            return seen[key]

        return _repl

    text = _EMAIL.sub(sub("EMAIL"), text)
    text = _PHONE.sub(sub("PHONE"), text)
    text = _mask_names(text, [*(known_names or []), *_self_named(text)], sub("NAME"))
    return RedactResult(text, mapping)
