"""Launch the unmodified official harness with an explicit client environment."""
import json
import ipaddress
import os
from pathlib import Path
import subprocess
import sys
from psycopg2 import extensions

ROOT=Path(__file__).resolve().parents[1]
IMAGE='kloudkart-race-client:de03'


def linux_address():
    detail=json.loads(subprocess.check_output(['docker','inspect','kloudkart_rebuild'],text=True))[0]
    for network in detail['NetworkSettings']['Networks'].values():
        value=network.get('IPAddress')
        if value and ipaddress.ip_address(value).is_private and not ipaddress.ip_address(value).is_loopback:
            return value
    raise RuntimeError('Named PostgreSQL container has no private IPv4 bridge address')


def prepare_linux_client(log_path):
    # No client CSVs enter this build context; the Dockerfile copies no project files.
    p=subprocess.run(['docker','build','--tag',IMAGE,'--file',str(ROOT/'tests/phase3/Dockerfile.client'),
                      str(ROOT/'tests/phase3')],cwd=ROOT,capture_output=True,text=True,encoding='utf-8',errors='replace')
    log_path.write_text(p.stdout+p.stderr,encoding='utf-8')
    if p.returncode:
        raise RuntimeError('Test client build failed; inspect '+log_path.name)
    metadata=json.loads(subprocess.check_output(['docker','image','inspect',IMAGE],text=True))[0]
    version=subprocess.check_output(['docker','run','--rm',IMAGE,'python','-c',
        'import json,sys,psycopg2; print(json.dumps(dict(python=sys.version.split()[0],psycopg2=psycopg2.__version__.split()[0])))'],text=True)
    return dict(client='linux-docker',image=IMAGE,image_id=metadata['Id'],versions=json.loads(version),
                network='same network namespace as kloudkart_rebuild; TCP bridge address:5432 (not trusted loopback)',
                connections=400,harness_modified=False,connection_pool=False)


def run_race(dsn,arguments,client='linux'):
    parsed=extensions.parse_dsn(dsn)
    if (parsed.get('host'),parsed.get('port'))!=('127.0.0.1','5433'):
        raise RuntimeError('Refusing unexpected host endpoint for the official harness')
    if not parsed.get('dbname','').startswith('kloudkart_submission_'):
        raise RuntimeError('Official harness must use a disposable submission database')
    environment=os.environ.copy();environment['PYTHONIOENCODING']='utf-8'
    if client=='linux':
        environment['DATABASE_URL']=extensions.make_dsn(dsn,host=linux_address(),port=5432)
        command=['docker','run','--rm','--network','container:kloudkart_rebuild','--env','DATABASE_URL',
                 '--mount',f'type=bind,source={ROOT / "race_test.py"},target=/lab/race_test.py,readonly',
                 IMAGE,'python','/lab/race_test.py',*arguments]
    elif client=='windows':
        environment['DATABASE_URL']=dsn
        command=[sys.executable,str(ROOT/'race_test.py'),*arguments]
    else:
        raise RuntimeError('Unknown test client')
    return subprocess.run(command,cwd=ROOT,env=environment,capture_output=True,
                          text=True,encoding='utf-8',errors='replace')


def verify_linux_authentication(dsn):
    # Prove that the test route does not use the image's localhost trust rule.
    # The deliberate bad-password attempt happens outside all benchmark timers.
    environment=os.environ.copy()
    environment['DATABASE_URL']=extensions.make_dsn(dsn,host=linux_address(),port=5432)
    code='''import json,os,psycopg2
from psycopg2.extensions import make_dsn
try:
    psycopg2.connect(make_dsn(os.environ['DATABASE_URL'],password='intentionally-invalid-test-password'))
except psycopg2.OperationalError as exc:
    assert exc.pgcode=='28P01' or 'password authentication failed' in str(exc)
else:
    raise RuntimeError('Route accepted an invalid password')
with psycopg2.connect(os.environ['DATABASE_URL']) as c:
    with c.cursor() as cur:
        cur.execute('SELECT current_database(),system_identifier::text FROM pg_control_system()')
        database,cluster=cur.fetchone()
print(json.dumps(dict(wrong_password_rejected=True,correct_password_accepted=True,database=database,cluster=cluster)))
'''
    p=subprocess.run(['docker','run','--rm','--network','container:kloudkart_rebuild',
                      '--env','DATABASE_URL',IMAGE,'python','-c',code],env=environment,
                     capture_output=True,text=True,encoding='utf-8',errors='replace')
    if p.returncode:
        raise RuntimeError('Linux client authentication preflight failed')
    return json.loads(p.stdout)
