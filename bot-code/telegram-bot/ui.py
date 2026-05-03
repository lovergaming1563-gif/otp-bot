"""Premium UI helpers — consistent box-drawing style for all bot messages.

Every user-facing message uses these primitives so the look stays uniform across
welcome / profile / buy / order / deposit / refund / promo / support flows.
"""

# Visual constants
DIV  = "━━━━━━━━━━━━━━━━━━━━━"
BAR  = "─────────────────────"
TOP  = "┏━━━━━━━━━━━━━━━━━━━━━┓"
BOT  = "┗━━━━━━━━━━━━━━━━━━━━━┛"
BTOP = "┌─────────────────────"
BBOT = "└─────────────────────"


def header(title: str, emoji_l: str = "✨", emoji_r: str = "✨") -> str:
    """Premium banner header."""
    return f"{TOP}\n  {emoji_l}  *{title}*  {emoji_r}\n{BOT}"


def section(title: str, emoji: str = "▸") -> str:
    return f"{emoji}  *{title}*"


def field(label: str, value: str, emoji: str = "•") -> str:
    """Aligned field row: emoji  Label  ›  value"""
    return f"{emoji}  *{label}*  ›  {value}"


def card(lines: list) -> str:
    """Wrap lines in a card frame."""
    body = "\n".join(f"│  {l}" for l in lines)
    return f"{BTOP}\n{body}\n{BBOT}"


def footer(text: str = "Thanks for choosing us!", emoji: str = "🙏") -> str:
    return f"{emoji} _{text}_"


def safe_md(text: str) -> str:
    """Strip / replace Markdown-breaking chars from user/external content."""
    if not text:
        return ""
    return (text.replace("*", "·")
                .replace("_", " ")
                .replace("`", "'")
                .replace("[", "(")
                .replace("]", ")"))
