"""Validate required submission files, template headings, links and source hashes."""
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = {
    'docs/data_findings.md': ['Summary','Reconciliation','Findings, ranked by risk',
                              'Looked wrong, is not wrong','Could not verify'],
    'docs/client_memo.md': ['What I found','What I built','What I recommend','What I could not stand behind'],
    'docs/improvement.md': ['The problem it solves','What I built','What it is worth to Nana','What it cost'],
    'docs/performance_report.md': ['Target','Method','Results','Before / after','Caveats'],
}
ADR_HEADINGS = ['Context','Decision','Alternatives considered','Consequences','What this survives']


def main():
    checked = []
    for name, headings in EXPECTED.items():
        source = (ROOT/name).read_text(encoding='utf-8')
        assert re.findall(r'^## (.+)$',source,re.M) == headings, name+' template headings'
        checked.append(name)
    adrs = sorted((ROOT/'decisions').glob('ADR-*.md'))
    assert len(adrs)==6
    for number, path in enumerate(adrs,1):
        source = path.read_text(encoding='utf-8')
        assert path.name.startswith(f'ADR-{number:03d}-')
        assert re.findall(r'^## (.+)$',source,re.M)==ADR_HEADINGS
        assert '- **Status:** Accepted' in source and '- **Date:** 2026-11-27' in source
        assert len(re.findall(r'^### Alternative ',source,re.M))>=2
        assert all(x in source for x in ('**Decision owner:**','**What this buys:**','**What this costs:**',
                                        '**What it costs the client if I am wrong:**',
                                        '**What would make me revisit this:**'))
        checked.append(path.relative_to(ROOT).as_posix())
    memo = (ROOT/'docs/client_memo.md').read_text(encoding='utf-8')
    words = len(memo.split())
    assert words <= 450, 'Memo length exceeds a one-page business memo'
    evidence = json.loads((ROOT/'tests/final_evidence.json').read_text())
    assert evidence['all_checks_passed']
    for name, digest in evidence['protected_file_sha256'].items():
        assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest, name+' changed'
    for name in ('schema.sql','load.sql','race_test.py'):
        original = subprocess.check_output(['git','show',f'HEAD:{name}'],cwd=ROOT)
        assert hashlib.sha256(original).hexdigest()==hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
    for name in ['README.md','docs/submission_checklist.md',*EXPECTED,*(str(p.relative_to(ROOT)) for p in adrs)]:
        p = ROOT/name
        for target in re.findall(r'\[[^\]]*\]\(([^)]+)\)',p.read_text(encoding='utf-8')):
            if '://' in target or target.startswith('#'):
                continue
            assert (p.parent/target.split('#')[0]).exists(),f'{name}: missing link {target}'
    subprocess.run(['git','diff','--check'],cwd=ROOT,check=True,capture_output=True)
    out = dict(template_files_checked=checked,exactly_six_adrs=True,memo_words=words,
               all_local_document_links_resolve=True,original_sources_and_csvs_unchanged=True,
               git_diff_check_passed=True,passed=True)
    (ROOT/'tests/final_documentation_checks.json').write_text(json.dumps(out,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(out))


if __name__=='__main__':
    main()
