"""Tests for the Gopher map parser."""

from core.gophermap_parser import parse, GophermapItem, ParsedGophermap


class TestGophermapParser:
    """Test RFC 1436 gophermap parsing."""

    def test_parse_empty(self):
        result = parse("")
        assert isinstance(result, ParsedGophermap)
        assert result.items == []

    def test_parse_terminator(self):
        result = parse(".\r\n")
        assert result.items == []

    def test_parse_info_lines(self):
        raw = "iHello World\tfake\t(NULL)\t0\r\niSecond line\tfake\t(NULL)\t0\r\n.\r\n"
        result = parse(raw)
        assert len(result.items) == 2
        assert result.items[0].is_info
        assert result.items[0].display == "Hello World"
        assert result.info_lines == ["Hello World", "Second line"]
        assert result.menu_items == []

    def test_parse_menu_link(self):
        raw = "1About\t/about\tlocalhost\t7070\r\n.\r\n"
        result = parse(raw)
        assert len(result.items) == 1
        item = result.items[0]
        assert item.item_type == "1"
        assert item.display == "About"
        assert item.selector == "/about"
        assert item.host == "localhost"
        assert item.port == 7070
        assert item.type_name == "menu"
        assert not item.is_info
        assert result.menu_items == [item]

    def test_parse_text_link(self):
        raw = "0README\t/readme.txt\tlocalhost\t70\r\n.\r\n"
        result = parse(raw)
        assert len(result.menu_items) == 1
        assert result.menu_items[0].type_name == "text"

    def test_parse_mixed_content(self):
        raw = (
            "iWelcome\tfake\t(NULL)\t0\r\n"
            "1Directory\t/dir\tlocalhost\t7070\r\n"
            "0File\t/file.txt\tlocalhost\t7070\r\n"
            "7Search\t/search\tlocalhost\t7070\r\n"
            ".\r\n"
        )
        result = parse(raw)
        assert len(result.items) == 4
        assert len(result.info_lines) == 1
        assert len(result.menu_items) == 3

    def test_parse_incomplete_line_skipped(self):
        """Lines with fewer than 4 tab-separated parts (non-info) are skipped."""
        raw = "1Broken\t/broken\r\n.\r\n"
        result = parse(raw)
        assert result.menu_items == []

    def test_parse_default_port(self):
        """Empty port defaults to 70."""
        raw = "1Test\t/test\tlocalhost\t\r\n.\r\n"
        result = parse(raw)
        assert result.menu_items[0].port == 70

    def test_parse_invalid_port(self):
        """Non-integer port defaults to 70."""
        raw = "1Test\t/test\tlocalhost\tabc\r\n.\r\n"
        result = parse(raw)
        assert result.menu_items[0].port == 70

    def test_parse_stops_at_period(self):
        """Parsing stops at a line containing only '.'"""
        raw = "iLine 1\tfake\t(NULL)\t0\r\n.\r\niLine 2\tfake\t(NULL)\t0\r\n"
        result = parse(raw)
        assert len(result.items) == 1
        assert result.info_lines == ["Line 1"]

    def test_info_line_minimal(self):
        """Info line with no tabs."""
        raw = "iJust text\r\n.\r\n"
        result = parse(raw)
        assert len(result.items) == 1
        assert result.items[0].display == "Just text"

    def test_html_link(self):
        raw = "hWeb Link\tURL:https://example.com\tlocalhost\t7070\r\n.\r\n"
        result = parse(raw)
        assert len(result.menu_items) == 1
        assert result.menu_items[0].type_name == "html"
        assert result.menu_items[0].selector == "URL:https://example.com"
