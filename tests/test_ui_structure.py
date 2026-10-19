"""Basic static UI checks; these do not replace browser interaction tests."""
import re
import unittest
from html.parser import HTMLParser
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / 'static'


class Document(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.labels = []
        self.scripts = []
        self.styles = []
        self.language = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if 'id' in attrs:
            self.ids.append(attrs['id'])
        if tag == 'label' and 'for' in attrs:
            self.labels.append(attrs['for'])
        if tag == 'script' and 'src' in attrs:
            self.scripts.append(attrs['src'])
        if tag == 'link' and attrs.get('rel') == 'stylesheet':
            self.styles.append(attrs['href'])
        if tag == 'html':
            self.language = attrs.get('lang')


class StaticUITests(unittest.TestCase):
    def setUp(self):
        self.doc = Document()
        self.doc.feed((STATIC / 'index.html').read_text())

    def test_document_language_and_unique_ids(self):
        self.assertEqual(self.doc.language, 'ja')
        self.assertEqual(len(self.doc.ids), len(set(self.doc.ids)))

    def test_labels_point_to_static_controls(self):
        for target in self.doc.labels:
            self.assertIn(target, self.doc.ids)

    def test_script_and_style_use_supported_local_routes(self):
        self.assertEqual(self.doc.scripts, ['/app.js'])
        self.assertEqual(self.doc.styles, ['/styles.css'])
        for route in self.doc.scripts + self.doc.styles:
            self.assertTrue((STATIC / route.lstrip('/')).is_file())

    def test_javascript_static_id_references_exist(self):
        js = (STATIC / 'app.js').read_text()
        for element_id in re.findall(r"\$\([\"']([^\"']+)[\"']\)", js):
            self.assertIn(element_id, self.doc.ids)


if __name__ == '__main__':
    unittest.main()
