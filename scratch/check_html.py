from html.parser import HTMLParser

class MyParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.stack = []
        self.depth = 0
    def handle_starttag(self, tag, attrs):
        if tag in ['body', 'div', 'main', 'section', 'aside', 'header']:
            cls = next((v for k, v in attrs if k == 'class'), '')
            pid = next((v for k, v in attrs if k == 'id'), '')
            print('  ' * self.depth + f'<{tag} id=\"{pid}\" class=\"{cls}\">')
            self.depth += 1
            self.stack.append(tag)
    def handle_endtag(self, tag):
        if tag in ['body', 'div', 'main', 'section', 'aside', 'header']:
            self.depth -= 1
            print('  ' * self.depth + f'</{tag}>')
            if self.stack:
                self.stack.pop()

parser = MyParser()
parser.feed(open('ui/static/gui.html', encoding='utf-8').read())
