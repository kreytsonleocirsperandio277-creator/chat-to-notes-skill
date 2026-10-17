"""Keep unmapped text in a final appendix; this is not a semantic completeness test."""
import argparse
import json
from pathlib import Path


def finalize(source, draft, coverage):
    units = source.get('units')
    if not isinstance(units, list) or not units:
        raise ValueError('source.json必须有非空units数组。')
    if not isinstance(coverage, dict):
        raise ValueError('去向表必须是以单元ID为键的对象。')
    ids = [u.get('id') for u in units]
    if any(not isinstance(i, str) or not i.strip() for i in ids) or len(set(ids)) != len(ids):
        raise ValueError('来源单元ID为空或重复。')
    unknown = set(coverage) - set(ids)
    if unknown:
        raise ValueError('去向表含未知ID：' + ', '.join(sorted(unknown)))
    appended, results = [], []
    for unit in units:
        ident = unit['id']
        if not isinstance(unit.get('text'), str):
            raise ValueError('来源单元缺少text：' + ident)
        entry = coverage.get(ident)
        result = {'id': ident}
        if entry is None:
            reason = '未登记去向'
        elif not isinstance(entry, dict) or entry.get('status') not in ('body', 'appendix', 'excluded'):
            raise ValueError('非法去向记录：' + ident)
        elif entry['status'] == 'excluded':
            why = entry.get('reason')
            if not isinstance(why, str) or not why.strip():
                raise ValueError('删除须有明确理由：' + ident)
            result.update(status='excluded', reason=why)
            results.append(result)
            continue
        else:
            evidence = entry.get('evidence')
            if isinstance(evidence, str) and evidence.strip() and evidence in draft:
                result.update(status=entry['status'], evidence=evidence)
                results.append(result)
                continue
            reason = '未提供可定位证据或证据不在稿件中'
        appended.append(unit)
        result.update(status='appended', reason=reason)
        results.append(result)
    output = draft.rstrip()
    if appended:
        output += '\n\n# 暂存与补充：尚未归类的重要内容\n\n以下内容按来源保留，尚待进一步组织。资源入口相对于原始材料，交付前需检查并整理引用。\n'
        for unit in appended:
            label = ' · '.join(str(v) for v in (unit['id'], unit.get('speaker'), unit.get('time')) if v)
            output += '\n## ' + label.replace('\n', ' ') + '\n\n'
            output += '\n'.join('> ' + line for line in unit['text'].split('\n')) + '\n'
            for ref in unit.get('resources', []):
                output += '\n资源入口（原始路径）：`' + str(ref).replace('`', '\\`') + '`\n'
    report = {'schema_version': 1, 'source_units': len(units), 'appended_units': len(appended),
              'excluded_units': sum(r['status'] == 'excluded' for r in results), 'results': results,
              'semantic_completeness_verified': False,
              'notice': '去向核对不证明语义零遗漏。AI仍须检查每条消息中的多个事项、细节和图文。'}
    return output + '\n', report


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('source', type=Path)
    ap.add_argument('draft', type=Path)
    ap.add_argument('coverage', type=Path)
    ap.add_argument('--output', required=True, type=Path)
    ap.add_argument('--report', required=True, type=Path)
    args = ap.parse_args()
    try:
        inputs = {p.resolve() for p in (args.source, args.draft, args.coverage)}
        outputs = [args.output, args.report]
        if args.output.resolve() == args.report.resolve() or any(p.exists() or p.resolve() in inputs for p in outputs):
            raise ValueError('输出不能覆盖已有文件、输入或另一个输出，请另存新文件。')
        source = json.loads(args.source.read_text(encoding='utf-8-sig'))
        coverage = json.loads(args.coverage.read_text(encoding='utf-8-sig'))
        result, report = finalize(source, args.draft.read_text(encoding='utf-8-sig'), coverage)
        for p in outputs:
            p.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open('x', encoding='utf-8') as f:
            f.write(result)
        with args.report.open('x', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(json.dumps({'source_units': report['source_units'], 'appended_units': report['appended_units']}, ensure_ascii=False))
    except (ValueError, OSError) as exc:
        ap.exit(2, str(exc) + '\n')


if __name__ == '__main__':
    main()
