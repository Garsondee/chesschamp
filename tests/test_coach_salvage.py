"""_salvage_chat: best-effort recovery when a model ignores JSON mode and/or a tight
max_tokens truncates the response mid-string. Pure string logic — no network.

This is a regression test for a real bug: a "propose" call once returned a raw, truncated
JSON blob straight into the chat UI because the fallback path just echoed the raw text.
"""

from chesscoach.coach import _salvage_chat


def test_recovers_a_complete_fenced_json_block():
    text = '```json\n{"chat": "clean short reply"}\n```'
    assert _salvage_chat(text) == "clean short reply"


def test_recovers_text_truncated_mid_string():
    # The actual failure mode: max_tokens cut the response off before the closing quote.
    text = '```json\n{\n  "chat": "Qh5 looks tempting, but Nf6 kicks it and you lose tem'
    assert _salvage_chat(text) == "Qh5 looks tempting, but Nf6 kicks it and you lose tem"


def test_unescapes_common_json_escapes():
    text = r'{"chat": "He said \"no\" and left"}'
    assert _salvage_chat(text) == 'He said "no" and left'


def test_falls_back_gracefully_when_there_is_no_chat_field():
    text = '{"unexpected": "shape"}'
    result = _salvage_chat(text)
    assert result and not result.startswith("{")


def test_never_returns_raw_json_to_the_player():
    """The whole point of this function: whatever comes out must not look like JSON/markdown."""
    for junk in ['```json\n{"nope": true}', "{", "", "   ", "```\n```"]:
        result = _salvage_chat(junk)
        assert not result.strip().startswith("{")
        assert not result.strip().startswith("```")
