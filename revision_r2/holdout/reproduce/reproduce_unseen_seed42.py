"""Reproduce the seed-42 unseen-user (held-out) evaluation of the IEEE Access R2 revision.

Steps (run in order; each writes into the private work folder given by --work):
  check   verify that the published frozen code matches the hashes recorded when it ran
  split   rebuild the pre-registered 1,500 / 500 user split and check it against SPLIT_RECEIPT.json
  build   rebuild the development-user training tensors (TRAIN and VALIDATION periods only)
  train   retrain the seed-42 models with the frozen recipes (needs a CUDA GPU)
  score   score the 500 held-out users once and write the result table

Route "load" skips `train` and scores the published seed-42 checkpoints (holdout/checkpoints_seed42).

Data access: only CERT r5.2 rows dated 2010-01-02 to 2011-04-10 (the TRAIN and VALIDATION
periods) are read after preparation. Rows of the TEST period (from 2011-04-11) are never read.
The work folder holds user IDs, tensors and checkpoints; it must stay private and outside the repository.
"""
from __future__ import annotations

import argparse, hashlib, json, os, subprocess, sys, time
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
HOLDOUT = HERE.parent                       # revision_r2/holdout
CODE = HOLDOUT / 'code'                     # frozen code, published byte-for-byte
REPO = HOLDOUT.parents[1]
SEED = 42
FEATURES = ['total_events', 'logon_count', 'device_count', 'file_count', 'email_count', 'http_count',
            'active_duration_minutes', 'has_logon_activity', 'has_device_activity', 'has_file_activity',
            'has_email_activity', 'has_http_activity', 'is_active_day']
FIRST_DAY, TRAIN_END, VALIDATION_END = date(2010, 1, 2), date(2011, 2, 18), date(2011, 4, 10)
TRAIN_DAYS, VALIDATION_DAYS = 413, 51
# Training order: TRACE (TA2) needs all three teachers (T-OPT 42/52/62), each initialised from its precursor.
TRAIN_ORDER = [('AL_PRECURSOR', 42), ('AL_PRECURSOR', 52), ('AL_PRECURSOR', 62),
               ('T-OPT', 42), ('T-OPT', 52), ('T-OPT', 62),
               ('F00', 42), ('TA2', 42), ('XGBoost_40', 42)]
SCORED = [('TA2', 'TRACE'), ('F00', 'Task-only control (F00)'), ('XGBoost_40', 'XGBoost-40')]


def sha(path) -> str:
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def say(*a):
    print(*a, flush=True)


def load_json(p):
    return json.loads(Path(p).read_text(encoding='utf-8-sig'))


def work_dir(args) -> Path:
    w = Path(args.work).resolve()
    if w == REPO or REPO in w.parents:
        sys.exit('REFUSED: --work must be outside the repository (it will hold user IDs and tensors).')
    w.mkdir(parents=True, exist_ok=True)
    return w


def read_daily(dense, users, columns):
    import pandas as pd, pyarrow.dataset as ds
    predicate = (ds.field('interval_date') >= FIRST_DAY) & (ds.field('interval_date') <= VALIDATION_END)
    if users is not None:
        predicate = ds.field('user').isin(users) & predicate
    cols = list(dict.fromkeys(columns + ['interval_date']))
    frame = ds.dataset(dense, format='parquet').to_table(columns=cols, filter=predicate).to_pandas()
    frame['interval_date'] = pd.to_datetime(frame['interval_date'])
    assert frame.interval_date.max() <= pd.Timestamp(VALIDATION_END), 'TEST-period row returned'
    return frame


# ----------------------------------------------------------------------------------------------
# Frozen-code loader. The frozen modules hard-code the authors' Windows paths. They are imported
# from the published copy only, and their path constants are pointed at the private work folder.
# ----------------------------------------------------------------------------------------------
_RUNTIME = None
_ALLOWED: list[str] = []


def _strip():
    """Drop the authors' C:\\PhD entries that the frozen modules add to sys.path on import."""
    sys.path[:] = [p for p in sys.path if p in _ALLOWED]
FROZEN_MODULES = ('phase2_runtime', 'common', 'score', 'editor011_confirmation', 'editor012_rescue',
                  'prototype_v3_node', 'r52_locked_baselines', 'models')


def _assert_from_clone():
    for name, mod in list(sys.modules.items()):
        if name.split('.')[0] in FROZEN_MODULES and getattr(mod, '__file__', None):
            assert Path(mod.__file__).resolve().is_relative_to(CODE), f'{name} was imported from outside this clone: {mod.__file__}'


def aggregate40():
    """The frozen 40-summary function (code/parity_source). CPU only; no PyTorch needed."""
    if str(CODE / 'parity_source') not in sys.path:
        sys.path.insert(0, str(CODE / 'parity_source'))
    from r52_locked_baselines.data import aggregate_common13_windows
    _assert_from_clone()
    return aggregate_common13_windows


def frozen_runtime(work: Path, checkpoint_root: Path | None = None):
    global _RUNTIME
    if _RUNTIME is None:
        mine = [str(p) for p in (CODE / 'parity_source', CODE / 'producing_model', CODE / 'src', CODE, CODE / 'phase4')]
        sys.path[:0] = mine
        _ALLOWED[:] = list(sys.path)
        # Pre-import the dependencies so the frozen modules cannot load copies from outside this clone
        # (they insert the authors' C:\PhD paths into sys.path when imported).
        import models.sequence_ensemble, prototype_v3_node.architecture  # noqa: F401
        import editor011_confirmation.constants, editor011_confirmation.models, editor012_rescue.losses  # noqa: F401
        import r52_locked_baselines.data  # noqa: F401
        import phase2_runtime as rt
        _strip()
        import common as p4common          # phase4/common.py
        _strip()
        _assert_from_clone()
        _RUNTIME = (rt, p4common)
    rt, p4common = _RUNTIME
    root = checkpoint_root or work
    rt.ROOT, rt.OUT, rt.PRIVATE = CODE, work, root
    rt.gate = lambda: None                 # the authors' Phase-1 report gate does not apply here
    p4common.ROOT, p4common.OUT, p4common.PRIVATE = CODE, work, root
    return rt, p4common


# ----------------------------------------------------------------------------------------------
def cmd_check(args):
    """Compare the published code with the hashes recorded in the frozen manifests."""
    frozen = load_json(HOLDOUT / 'MODELS_FROZEN.json')
    phase4 = load_json(HOLDOUT / 'phase4' / 'MODELS_FROZEN_PHASE4.json')
    redacted = {e['file'] for e in load_json(CODE / 'REDACTIONS.json')['files']}
    ok = bad = 0
    for e in frozen['implementation_files'] + [frozen['scoring_script']]:
        rel = e['path'].split('r2_holdout\\', 1)[1].replace('\\', '/')
        p = CODE / rel
        if not p.exists():
            say('MISSING  ', rel); bad += 1; continue
        if sha(p) == e['sha256']:
            ok += 1
        elif rel in redacted:
            say('REDACTED ', rel, '(see code/REDACTIONS.json)')
        else:
            say('MISMATCH ', rel); bad += 1
    for name, h in phase4['files'].items():
        if sha(CODE / 'phase4' / name) == h:
            ok += 1
        else:
            say('MISMATCH  phase4/' + name); bad += 1
    say(f'check: {ok} files match the frozen hashes, {bad} problems')
    if bad:
        sys.exit(1)


def cmd_split(args):
    """Same rule as code/phase2_data.py (pre-registered): sort users; one default_rng(20261022);
    shuffle the insider stratum, then the non-insider stratum; take round(0.25 x size) of each."""
    import numpy as np, pyarrow.dataset as ds
    w = work_dir(args)
    users = sorted(set(read_daily(args.dense, None, ['user']).user.astype(str)))
    assert len(users) == 2000, len(users)
    insiders = set()
    for scenario in range(1, 5):
        for p in sorted((Path(args.answers) / f'r5.2-{scenario}').glob('r5.2-*.csv')):
            assert p.stat().st_size > 0
            insiders.add(p.stem.split('-')[-1])       # file names only; no answer content is read
    assert insiders and insiders <= set(users)
    strata = [sorted(insiders), sorted(set(users) - insiders)]
    rng = np.random.default_rng(20261022)
    sizes = [round(.25 * len(s)) for s in strata]
    adjustment = 500 - sum(sizes)
    assert abs(adjustment) <= 1
    if adjustment:
        sizes[int(np.argmax([len(s) for s in strata]))] += adjustment
    holdout = []
    for s, n in zip(strata, sizes):
        a = np.array(s); rng.shuffle(a); holdout.extend(a[:n].tolist())
    holdout = sorted(holdout); development = sorted(set(users) - set(holdout))
    for name, values in [('HOLDOUT', holdout), ('DEVELOPMENT', development)]:
        with (w / f'{name}_USERS.txt').open('w', encoding='utf-8', newline='\n') as f:
            f.write('\n'.join(values) + '\n')
    (w / 'INSIDERS.txt').write_text('\n'.join(sorted(insiders)) + '\n', encoding='utf-8', newline='\n')
    receipt = load_json(HOLDOUT / 'SPLIT_RECEIPT.json')['groups']
    all_ok = True
    for name, values in [('HOLDOUT', holdout), ('DEVELOPMENT', development)]:
        got = sha(w / f'{name}_USERS.txt'); want = receipt[name]['list_sha256']
        counts_ok = (len(values), len(set(values) & insiders)) == (receipt[name]['users'], receipt[name]['insider'])
        all_ok &= got == want and counts_ok
        say(f'{name:11s} users={len(values)} insiders={len(set(values) & insiders)} '
            f'list_sha256 {"MATCHES" if got == want else "DOES NOT MATCH"} SPLIT_RECEIPT.json')
    if not all_ok:
        sys.exit('split: the rebuilt split differs from the pre-registered one; stop here.')


def cmd_build(args):
    """Same computation as code/phase2_data.py, with windows taken from the daily table instead of
    the authors' intermediate tensor files: development users in sorted order, then windows by start day."""
    import numpy as np
    w = work_dir(args)
    dev = (w / 'DEVELOPMENT_USERS.txt').read_text(encoding='utf-8').splitlines()
    assert len(dev) == 1500
    daily = read_daily(args.dense, dev, ['user', 'interval_date', *FEATURES, 'is_malicious_interval'])
    daily = daily.sort_values(['user', 'interval_date'], kind='mergesort').reset_index(drop=True)
    assert set(daily.user) == set(dev) and len(daily) == 1500 * (TRAIN_DAYS + VALIDATION_DAYS)
    import pandas as pd
    train_days = daily.loc[daily.interval_date <= pd.Timestamp(TRAIN_END), FEATURES].to_numpy(dtype=np.float64)
    assert len(train_days) == 1500 * TRAIN_DAYS
    mean = train_days.mean(axis=0); scale = train_days.std(axis=0, ddof=0); scale[scale == 0] = 1
    (w / 'DEVELOPMENT_DAILY_SCALER.json').write_text(json.dumps({'features': FEATURES, 'mean': mean.tolist(), 'scale': scale.tolist(), 'fit_rows': len(train_days)}, indent=2), encoding='utf-8')
    say('scaler: fitted on', len(train_days), 'development TRAIN user-days')
    if args.scaler_only:
        return
    aggregate_common13_windows = aggregate40()
    groups = {u: g.reset_index(drop=True) for u, g in daily.groupby('user', sort=False)}
    tdir = w / 'tensors'; tdir.mkdir(exist_ok=True)
    manifest = load_json(HOLDOUT / 'DATA_MANIFEST.json')
    for split, lo, n_days in [('train', 0, TRAIN_DAYS), ('validation', TRAIN_DAYS, VALIDATION_DAYS)]:
        per_user = n_days - 19; n = 1500 * per_user
        X = np.lib.format.open_memmap(tdir / f'{split}_X.npy', mode='w+', dtype=np.float32, shape=(n, 20, 13))
        X40 = np.lib.format.open_memmap(tdir / f'{split}_X40.npy', mode='w+', dtype=np.float32, shape=(n, 40))
        y = np.empty(n, dtype=np.int8)
        for i, u in enumerate(dev):
            g = groups[u]; raw = g[FEATURES].to_numpy(dtype=np.float64)
            ix = lo + np.arange(per_user)[:, None] + np.arange(20)[None, :]
            pos = slice(i * per_user, (i + 1) * per_user)
            X[pos] = ((raw[ix] - mean) / scale).astype(np.float32)
            y[pos] = g.is_malicious_interval.to_numpy()[ix].max(axis=1)
            X40[pos] = aggregate_common13_windows(np.asarray(X[pos]))[0]
        assert np.isfinite(X).all() and np.isfinite(X40).all()
        X.flush(); X40.flush(); del X, X40
        np.save(tdir / f'{split}_y.npy', y, allow_pickle=False)
        want = manifest['splits'][split]
        say(f'{split}: windows={n} positives={int(y.sum())} (receipt: {receipt_count(split)})')
        for f in ('X', 'X40', 'y'):
            name = f'{split}_{f}.npy'
            say(f'  {name}: sha256 {"MATCHES" if sha(tdir / name) == want["files"][name] else "differs from"} DATA_MANIFEST.json')


def receipt_count(split):
    g = load_json(HOLDOUT / 'SPLIT_RECEIPT.json')['groups']['DEVELOPMENT']['periods'][split]
    return f"windows={g['windows']} positives={g['positive_windows']}"


def cmd_train(args):
    w = work_dir(args)
    (w / 'runs').mkdir(exist_ok=True)
    for model, seed in TRAIN_ORDER:
        result = w / 'runs' / f'{model}_seed{seed}.json'
        if result.exists():
            say('done already:', model, seed); continue
        say('training', model, 'seed', seed, '...')
        t0 = time.time()
        rc = subprocess.call([sys.executable, '-B', str(Path(__file__)), '_train_one', '--work', str(w), '--model', model, '--seed', str(seed)])
        if rc != 0 or not result.exists():
            sys.exit(f'train: {model} seed {seed} failed (exit {rc})')
        say(f'  finished in {time.time() - t0:.0f} s')


def cmd_train_one(args):
    w = work_dir(args)
    rt, _ = frozen_runtime(w)
    rt.train_run(args.model, args.seed, w / 'runs' / f'{args.model}_seed{args.seed}.json')


def holdout_cohort(w: Path, dense):
    """Same construction as score.py execute(): the 500 held-out users, TRAIN + VALIDATION periods."""
    import numpy as np, pandas as pd
    aggregate_common13_windows = aggregate40()
    users = (w / 'HOLDOUT_USERS.txt').read_text(encoding='utf-8').splitlines(); assert len(users) == 500
    sc = load_json(w / 'DEVELOPMENT_DAILY_SCALER.json'); feats = sc['features']; mean = np.array(sc['mean']); scale = np.array(sc['scale'])
    frame = read_daily(dense, users, ['user', 'interval_date', *feats, 'is_malicious_interval'])
    frame = frame.sort_values(['user', 'interval_date'], kind='mergesort')
    assert len(frame) == 500 * (TRAIN_DAYS + VALIDATION_DAYS)
    xs, tab, ys, cluster = [], [], [], []
    for ui, u in enumerate(users):
        group = frame.loc[frame.user == u]
        for lo, hi, expected in [('2010-01-02', '2011-02-18', TRAIN_DAYS), ('2011-02-19', '2011-04-10', VALIDATION_DAYS)]:
            g = group.loc[(group.interval_date >= lo) & (group.interval_date <= hi)]
            assert len(g) == expected and (g.interval_date.diff().dropna() == pd.Timedelta(days=1)).all()
            raw = g[feats].to_numpy(dtype=np.float64); labels = g.is_malicious_interval.to_numpy()
            ix = np.arange(expected - 19)[:, None] + np.arange(20)[None, :]
            X = ((raw[ix] - mean) / scale).astype(np.float32)
            xs.append(X); tab.append(aggregate_common13_windows(X)[0]); ys.extend(labels[ix].max(1)); cluster.extend([ui] * len(ix))
    X = np.concatenate(xs); X40 = np.concatenate(tab); y = np.array(ys, dtype=np.int8); cluster = np.array(cluster)
    assert np.isfinite(X).all() and np.isfinite(X40).all()
    return users, X, X40, y, cluster


def cmd_score(args):
    import numpy as np, csv
    from sklearn.metrics import average_precision_score, precision_score, recall_score
    w = work_dir(args)
    if args.route == 'load':
        ck = Path(args.checkpoints).resolve()
        frozen = {(m['model'], m['seed']): m for m in load_json(HOLDOUT / 'phase4' / 'MODELS_FROZEN_PHASE4.json')['models']}
        specs = {}
        for model, _ in SCORED:
            f = frozen[(model, SEED)]
            path = ck / 'checkpoints' / model / f'seed{SEED}' / ('best.json' if model == 'XGBoost_40' else 'best.pt')
            assert sha(path) == f['sha256'], f'{path} does not match the frozen SHA-256 in MODELS_FROZEN_PHASE4.json'
            specs[model] = dict(model=model, seed=SEED, checkpoint=str(path), threshold=f['threshold'])
        root = ck
    else:
        specs = {}
        for model, _ in SCORED:
            r = load_json(w / 'runs' / f'{model}_seed{SEED}.json')
            specs[model] = dict(model=model, seed=SEED, checkpoint=r['checkpoint'], threshold=r['threshold'])
        root = w
    rt, _ = frozen_runtime(w, checkpoint_root=root)
    import score as frozen_score                  # phase4/score.py: the sole inference function used in the paper
    _strip()
    _assert_from_clone()
    users, X, X40, y, cluster = holdout_cohort(w, args.dense)
    insider_set = set((w / 'INSIDERS.txt').read_text(encoding='utf-8').splitlines())
    insider = np.array([u in insider_set for u in users])
    device = frozen_score.setup_torch()
    rows = []
    for model, label in SCORED:
        spec = specs[model]
        p = frozen_score.predict(spec, X, X40, device)
        flag = p >= spec['threshold']
        detected = sum(bool((flag & (y == 1) & (cluster == ui)).any()) for ui in np.flatnonzero(insider))
        flagged_normal = len(set(np.unique(cluster[flag])) - set(np.flatnonzero(insider)))
        rows.append(dict(model=label, internal_name=model, seed=SEED, route=args.route, windows=len(y), positive_windows=int(y.sum()),
                         PR_AUC=round(float(average_precision_score(y, p)), 6), threshold=spec['threshold'],
                         precision=round(float(precision_score(y, flag, zero_division=0)), 6), recall=round(float(recall_score(y, flag, zero_division=0)), 6),
                         alerts_per_1000_windows=round(float(flag.mean() * 1000), 3),
                         heldout_insiders=int(insider.sum()), insiders_detected=int(detected),
                         heldout_normal_users=int((~insider).sum()), normal_users_flagged=int(flagged_normal)))
        say(f'scored {label}')
    out = w / 'results'; out.mkdir(exist_ok=True)
    path = out / f'unseen_users_seed42_{args.route}.csv'
    with path.open('w', newline='', encoding='utf-8') as f:
        wr = csv.DictWriter(f, fieldnames=list(rows[0])); wr.writeheader(); wr.writerows(rows)
    say('result table written to', path)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    def common(p, data=True):
        p.add_argument('--work', default=os.environ.get('R2_WORK'), required=os.environ.get('R2_WORK') is None,
                       help='private work folder outside the repository (env R2_WORK)')
        if data:
            p.add_argument('--dense', default=os.environ.get('CERT_R52_DENSE'), required=os.environ.get('CERT_R52_DENSE') is None,
                           help='r52_user_day_intervals_dense.parquet from data_prep (env CERT_R52_DENSE)')
    sub.add_parser('check')
    p = sub.add_parser('split'); common(p)
    p.add_argument('--answers', default=os.environ.get('CERT_R52_ANSWERS'), required=os.environ.get('CERT_R52_ANSWERS') is None,
                   help='CERT answers folder that contains r5.2-1 ... r5.2-4 (env CERT_R52_ANSWERS)')
    p = sub.add_parser('build'); common(p); p.add_argument('--scaler-only', action='store_true')
    p = sub.add_parser('train'); common(p, data=False)
    p = sub.add_parser('_train_one'); common(p, data=False); p.add_argument('--model', required=True); p.add_argument('--seed', type=int, required=True)
    p = sub.add_parser('score'); common(p); p.add_argument('--route', choices=['load', 'retrain'], required=True); p.add_argument('--checkpoints', default=str(HOLDOUT / 'checkpoints_seed42'), help='folder with checkpoints/<model>/seed42 (default: the published seed-42 checkpoints)')
    a = ap.parse_args()
    if a.cmd == 'score' and a.route == 'load' and not a.checkpoints:
        ap.error('--route load needs --checkpoints')
    {'check': cmd_check, 'split': cmd_split, 'build': cmd_build, 'train': cmd_train, '_train_one': cmd_train_one, 'score': cmd_score}[a.cmd](a)


if __name__ == '__main__':
    main()
