from __future__ import annotations

from digital_bast.web.bast_assembler import _body_only

_SAMPLE_HTML = """<!DOCTYPE html>
<html><head><style>
    body { margin: 20px; background-color: #f4f4f4; }
    .box { border: 1px solid black; }
    .box img { width: 45px; height: auto; }
    /* .disabled {
        color: red;
    } */
    .a, .b { color: blue; }
</style></head>
<body><div class="box"><img src="x.png"></div></body></html>"""


def test_body_only_scopes_every_selector_to_the_wrapper() -> None:
    out = _body_only(_SAMPLE_HTML, "my-section")

    # "body" becomes the wrapper class itself -- the div plays body's role.
    assert ".my-section {" in out
    # every other selector gets the wrapper as an ancestor, not left bare
    # (a real regression: an earlier version of this scoping left non-body
    # selectors completely unprefixed).
    assert ".my-section .box {" in out
    assert ".my-section .box img {" in out
    assert "\n.box {" not in out
    assert "\n.box img {" not in out


def test_body_only_scopes_comma_separated_selectors() -> None:
    out = _body_only(_SAMPLE_HTML, "my-section")

    assert ".my-section .a, .my-section .b {" in out


def test_body_only_strips_comments_without_desyncing_later_rules() -> None:
    out = _body_only(_SAMPLE_HTML, "my-section")

    # The commented-out ".disabled { color: red; }" rule contains a balanced
    # brace pair -- it must not be parsed as a real rule, and it must not
    # swallow/mangle the ".a, .b" rule that follows it.
    assert "disabled" not in out
    assert ".my-section .a, .my-section .b {" in out


def test_body_only_keeps_only_body_content_in_the_wrapper_div() -> None:
    out = _body_only(_SAMPLE_HTML, "my-section")

    assert out.count('<div class="my-section">') == 1
    assert '<img src="x.png">' in out
