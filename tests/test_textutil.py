from addon.textutil import safe_html


def test_safe_html_keeps_formatting_and_colour():
    html = '<b>x</b><ul><li><span style="color:#3b82f6">term</span></li></ul><table><tr><td>a</td></tr></table>'
    assert safe_html(html) == html


def test_safe_html_drops_scripts_and_handlers():
    out = safe_html('a<script>alert(1)</script><img src=x onerror="alert(1)"><a href="javascript:alert(1)">l</a>'
                    '<iframe src=y></iframe><style>p{}</style>b')
    assert "script" not in out.lower() and "onerror" not in out and "javascript" not in out
    assert "iframe" not in out and "<style" not in out and out.startswith("a") and out.endswith("b")
