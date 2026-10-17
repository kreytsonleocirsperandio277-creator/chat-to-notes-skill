"""Extract readable source units without executing HTML or fetching resources."""
import argparse
import hashlib
import json
import re
from html.parser import HTMLParser
from pathlib import Path


class FragmentReader(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.resources = [], []
        self.skipped = 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.skipped += 1
        if self.skipped:
            return
        attrs = dict(attrs)
        if tag in ('div', 'p', 'br', 'li', 'tr', 'blockquote'):
            self.parts.append('\n')
        for key in ('src', 'href'):
            if attrs.get(key):
                ref = attrs[key]
                self.resources.append(ref)
                self.parts.append(' [资源入口：' + ref + '] ')
        if tag == 'img' and attrs.get('alt'):
            self.parts.append('[图片说明：' + attrs['alt'] + ']')

    def handle_endtag(self, tag):
        if tag in ('script', 'style') and self.skipped:
            self.skipped -= 1
        elif not self.skipped and tag in ('div', 'p', 'li', 'tr', 'blockquote'):
            self.parts.append('\n')

    def handle_data(self, data):
        if not self.skipped:
            self.parts.append(data)


def records_from_html(text):
    # Read only embedded JSON arrays; never evaluate JavaScript.
    starts = list(re.finditer(
        r'window\.__QCE_CHUNK__\s*\(\s*\{\s*id\s*:\s*(?:"[^"]*"|\x27[^\x27]*\x27)\s*,\s*messages\s*:\s*', text))
    if not starts:
        raise ValueError('不支持的HTML或未找到内嵌QCE消息。请检查是否依赖外部数据文件。')
    records = []
    chunk_counts = {}
    decoder = json.JSONDecoder()
    for start in starts:
        chunk, _ = decoder.raw_decode(text[start.end():].lstrip())
        if not isinstance(chunk, list):
            raise ValueError('QCE messages必须是JSON数组。')
        chunk_id = re.search(r'id\s*:\s*[\"\x27]([^\"\x27]+)', start.group()).group(1)
        if chunk_id in chunk_counts:
            raise ValueError('QCE分块ID重复：' + chunk_id)
        chunk_counts[chunk_id] = len(chunk)
        records.extend(chunk)
    manifests = list(re.finditer(r'window\.__QCE_MANIFEST__\s*\(\s*(?=\{)', text))
    for start in manifests:
        manifest, _ = decoder.raw_decode(text[start.end():])
        expected = manifest.get('stats', {}).get('totalMessages')
        if expected is not None and expected != len(records):
            raise ValueError('内嵌消息数与导出清单不一致，可能缺少外部分块。')
        for chunk in manifest.get('chunks', []):
            ident = chunk.get('id')
            if ident not in chunk_counts or (chunk.get('count') is not None and chunk['count'] != chunk_counts[ident]):
                raise ValueError('导出清单中的分块缺失或数量不符：' + str(ident))
    return records


def prepare(path):
    path = Path(path)
    raw = path.read_bytes()
    text = raw.decode('utf-8-sig')
    ext = path.suffix.lower()
    if ext in ('.html', '.htm'):
        records = records_from_html(text)
        fmt = 'qce-embedded-json'
    elif ext == '.json':
        records = json.loads(text)
        if isinstance(records, dict):
            records = records.get('messages')
        fmt = 'json-messages'
    elif ext in ('.txt', '.md', '.markdown'):
        records = [{'text': part.strip()} for part in re.split(r'\n[ \t]*\n', text.replace('\r\n', '\n')) if part.strip()]
        fmt = 'text-paragraphs'
    else:
        raise ValueError('支持UTF-8 TXT、Markdown、JSON和内嵌QCE HTML。')
    if not isinstance(records, list) or not records:
        raise ValueError('未取得消息，不能把空结果当成完成。')
    units, ids = [], set()
    for index, record in enumerate(records, 1):
        if not isinstance(record, dict):
            raise ValueError('每条消息必须是对象。')
        ident = str(record.get('id', f'u{index:06d}'))
        if not ident.strip() or ident in ids:
            raise ValueError('消息ID为空或重复：' + ident)
        ids.add(ident)
        if isinstance(record.get('html'), str) and record['html'].strip():
            parser = FragmentReader()
            parser.feed(record['html'])
            parser.close()
            body = '\n'.join(line.strip() for line in ''.join(parser.parts).splitlines() if line.strip())
            refs = list(dict.fromkeys(parser.resources))
        elif isinstance(record.get('text'), str):
            body, refs = record['text'], []
        else:
            raise ValueError('消息缺少可读的text/html：' + ident)
        units.append({'id': ident, 'order': index, 'speaker': str(record.get('name', record.get('speaker', ''))),
                      'time': str(record.get('date', record.get('timestamp', record.get('ts', '')))),
                      'text': body, 'resources': refs, 'source_record': record})
    return {'schema_version': 1, 'source_name': path.name, 'source_sha256': hashlib.sha256(raw).hexdigest(),
            'format': fmt, 'unit_count': len(units), 'units': units,
            'notice': '仅准备文字和资源入口。AI须阅读相关图片、转发和附件，并另行核对语义完整性。'}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('source', type=Path)
    ap.add_argument('--output', required=True, type=Path)
    args = ap.parse_args()
    try:
        if args.output.exists() or args.output.resolve() == args.source.resolve():
            raise ValueError('输出已存在或与输入相同，请另存新文件。')
        result = prepare(args.source)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open('x', encoding='utf-8') as out:
            json.dump(result, out, ensure_ascii=False, indent=2)
        print(json.dumps({'units': result['unit_count'], 'format': result['format']}, ensure_ascii=False))
    except (ValueError, OSError) as exc:
        ap.exit(2, str(exc) + '\n')


if __name__ == '__main__':
    main()
