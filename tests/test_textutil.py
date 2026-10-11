from addon.textutil import safe_html


def test_safe_html_keeps_formatting_and_colour():
    html = '<b>x</b><ul><li><span style="color:#3b82f6">term</span></li></ul><table><tr><td>a</td></tr></table>'
    assert safe_html(html) == html


def test_safe_html_drops_scripts_and_handlers():
    out = safe_html('a<script>alert(1)</script><img src=x onerror="alert(1)"><a href="javascript:alert(1)">l</a>'
                    '<iframe src=y></iframe><style>p{}</style>b')
    assert "script" not in out.lower() and "onerror" not in out and "javascript" not in out
    assert "iframe" not in out and "<style" not in out and out.startswith("a") and out.endswith("b")


def test_safe_html_blocks_parser_tricks():
    out = safe_html('<svg/onload=alert(1)><a href="jav&#x61;script:alert(1)">l</a><form action=javascript:x>'
                    '<meta http-equiv=refresh content="0;url=x"><img src="x.jpg" onerror=alert(1)>'
                    '<span style="background:url(javascript:x)">s</span>')
    assert "onload" not in out and "javascript" not in out.lower() and "jav&#x61;" not in out
    assert "<form" not in out and "<meta" not in out and "onerror" not in out and "<svg" not in out
    assert '<img src="x.jpg">' in out and "<span>s</span>" in out


def test_safe_html_keeps_links_entities_and_media():
    out = safe_html('<a href="https://example.com/a?b=1&amp;c=2">x</a> a&nbsp;&lt;b <img src="paste-1.png"><br>')
    assert out == '<a href="https://example.com/a?b=1&amp;c=2">x</a> a&nbsp;&lt;b <img src="paste-1.png"><br>'


def test_parse_json_reply_keeps_single_backslash_latex_u_commands():
    from addon.textutil import parse_json_reply
    assert parse_json_reply(r'{"a": "\(\uparrow x\) é"}')["a"] == "\\(\\uparrow x\\) é"
