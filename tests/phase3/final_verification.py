"""Read-only final fingerprints, deployment/configuration and source checks."""
import json
import subprocess
from datetime import datetime,timezone
from run_experiment import ROOT,HERE,LOGS,connect,safety,hashes,queries,sha,write

def main():
    baseline=json.loads((LOGS/'baseline.json').read_text())
    c,_,_=connect()
    try:
        current_hashes=json.loads(json.dumps(hashes(c)))
        current_safety=json.loads(json.dumps(safety(c)))
        environment=json.loads(json.dumps(queries(c,HERE/'inspect_environment.sql')))
        with c.cursor() as cur:
            cur.execute("SELECT prosrc FROM pg_proc WHERE oid='public.place_order(bigint,bigint,integer)'::regprocedure")
            body=cur.fetchone()[0]
        expected=(ROOT/'functions/phase3_place_order.sql').read_text(encoding='utf-8').split('$$')[1]
        source_changes=[]
        missing=[]
        for name,digest in baseline['file_sha256'].items():
            path=ROOT/name
            if not path.exists():missing.append(name)
            elif sha(path)!=digest:source_changes.append(name)
        # README may be updated to point to the completed work; no other initial
        # file is intentionally edited, including Phase 2 docs and local CSVs.
        out={
            'historical_fingerprints_equal':current_hashes==baseline['historical_fingerprints'],
            'historical_fingerprints':current_hashes,
            'counts_orphans_and_fixtures_equal':current_safety==baseline['safety'],
            'safety':current_safety,
            'settings_unchanged':environment[0]==baseline['environment'][0],
            'indexes_unchanged':environment[1]==baseline['environment'][1],
            'triggers_unchanged':environment[2]==baseline['environment'][2],
            'deployed_function_matches_final_sql':body.strip()==expected.strip(),
            'baseline_files_missing':missing,
            'baseline_files_changed':source_changes,
            'only_expected_file_changes':not missing and set(source_changes)<= {'README.md'},
            'race_test_unchanged':sha(ROOT/'race_test.py')==baseline['file_sha256']['race_test.py'],
            'git_branch':subprocess.check_output(['git','branch','--show-current'],cwd=ROOT,text=True).strip(),
            'git_head_unchanged':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()==baseline['git_head'],
        }
        stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        path=LOGS/f'final_verification_{stamp}.json'
        write(path,out)
        checked=('historical_fingerprints_equal','counts_orphans_and_fixtures_equal','settings_unchanged',
                 'indexes_unchanged','triggers_unchanged','deployed_function_matches_final_sql',
                 'only_expected_file_changes','race_test_unchanged','git_head_unchanged')
        print(json.dumps({'log':path.relative_to(ROOT).as_posix(),**{k:out[k] for k in checked},'git_branch':out['git_branch']}))
        assert all(out[k] for k in checked) and out['git_branch']=='new'
    finally:
        c.close()

if __name__=='__main__':
    try:main()
    except Exception as exc:
        print(json.dumps({'error_type':type(exc).__name__,'sqlstate':getattr(exc,'pgcode',None)}))
        raise SystemExit(1) from None
