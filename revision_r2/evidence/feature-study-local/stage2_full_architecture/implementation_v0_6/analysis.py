"""Retrospective estimation; no outcome-dependent model or feature selection."""
import json
from pathlib import Path
import numpy as np
from sklearn.metrics import average_precision_score
from ap_statistics import paired_cluster_ap
from contracts import atomic_json,sha
from data import SCHEMAS,SEEDS


def analyze(run,manifest,control):
    from runner import complete_fit,event
    panels={};reference=None
    for schema in SCHEMAS:
        for condition in ('L','T','C','G'):
            scores=[];aps=[]
            for seed in SEEDS:
                if control.requested():control.paused(reason='Analysis boundary; deterministic analysis restarts')
                folder=run/f'outer_{condition}_{schema}_seed{seed}'
                result=complete_fit(folder)
                with np.load(folder/'PREDICTIONS_LOCAL.npz',allow_pickle=False) as p:
                    key={n:p[n].copy() for n in ('user','start_date','end_date','sequence_id','label_task','label')}
                    if reference is None:reference=key
                    elif any(not np.array_equal(reference[n],key[n]) for n in reference):raise RuntimeError('Prediction key pairing failed')
                    scores.append(p['probability'].copy());aps.append(result['average_precision'])
            panels[(condition,schema)]=dict(scores=np.stack(scores),seed_ap=aps)
    y=reference['label'];users=np.unique(reference['user']);ui=np.searchsorted(users,reference['user'])
    contrasts=[]
    for partition in ('inner','outer'):
        for schema in SCHEMAS:
            for seed in SEEDS:
                c=json.loads((run/f'{partition}_C_{schema}_seed{seed}'/'RUN_IDENTITY.json').read_text())
                g=json.loads((run/f'{partition}_G_{schema}_seed{seed}'/'RUN_IDENTITY.json').read_text())
                if any(c[k]!=g[k] for k in ('starting_state_sha256','training_rng_seed')):raise RuntimeError('C/G pairing identity mismatch')
                pc=json.loads((run/f'{partition}_C_{schema}_seed{seed}'/'PAIRING.json').read_text())
                pg=json.loads((run/f'{partition}_G_{schema}_seed{seed}'/'PAIRING.json').read_text())
                if pc!=pg:raise RuntimeError('C/G shuffle or first-batch dropout masks differ')
    comparisons=[(c,s,c,'F13') for c in ('L','T','C','G') for s in ('F6_PRIMITIVES','F29')]
    comparisons += [('G',s,'C',s) for s in SCHEMAS]
    comparisons += [('T',s,'L',s) for s in SCHEMAS]
    for ac,aschema,bc,bschema in comparisons:
        event('analysis_contrast',arm=f'{ac}/{aschema}',reference=f'{bc}/{bschema}')
        if control.requested():control.paused(reason='Bootstrap boundary; deterministic analysis restarts')
        a=panels[(ac,aschema)]['scores'];b=panels[(bc,bschema)]['scores']
        summary,_=paired_cluster_ap(y,a,b,ui,len(users))
        summary.pop('primary_improvement_rule_met');summary.pop('practical_gain_margin')
        role='PRIMARY_RETROSPECTIVE_ESTIMATION' if (ac,aschema,bc,bschema)==('G','F29','G','F13') else ('SECONDARY_EXPLORATORY_MINUS_0.005_BENCHMARK' if (ac,aschema,bc,bschema)==('G','F6_PRIMITIVES','G','F13') else 'EXPLORATORY_UNCORRECTED')
        contrasts.append(dict(role=role,arm=f'{ac}/{aschema}',reference=f'{bc}/{bschema}',per_seed_ap_difference=(np.asarray(panels[(ac,aschema)]['seed_ap'])-panels[(bc,bschema)]['seed_ap']).tolist(),**summary))
    offsets=[]
    for offset in range(20):
        idx=np.flatnonzero(np.arange(len(y))%32%20==offset)
        values={f'{c}/{s}':[float(average_precision_score(y[idx],p[idx])) if len(np.unique(y[idx]))==2 else None for p in panels[(c,s)]['scores']] for c,s in panels}
        differences=[]
        for ac,aschema,bc,bschema in comparisons:
            av=values[f'{ac}/{aschema}'];bv=values[f'{bc}/{bschema}']
            differences.append(dict(arm=f'{ac}/{aschema}',reference=f'{bc}/{bschema}',mean_seed_ap_difference=float(np.mean(np.asarray(av)-bv)) if all(v is not None for v in av+bv) else None))
        offsets.append(dict(offset=offset,windows=len(idx),positives=int(y[idx].sum()),seed_ap=values,contrasts=differences,bootstrap=False))
    ensembles={}
    for schema in SCHEMAS:
        folder=run/f'outer_teacher_ensemble_{schema}';record=json.loads((folder/'COMPLETE.json').read_text())
        for name,checksum in record['artifacts'].items():
            if sha(folder/name)!=checksum:raise RuntimeError('Teacher ensemble artifact drift')
        ensembles[schema]=json.loads((folder/'RESULT.json').read_text())
    atomic_json(run/'ANALYSIS.json',dict(evidence_role='OUTCOME_EXPOSED_RETROSPECTIVE_ESTIMATION',confirmatory_claim=False,
        multiplicity_adjusted=False,seeds=list(SEEDS),panels={f'{c}/{s}':dict(seed_ap=p['seed_ap'],mean_seed_ap=float(np.mean(p['seed_ap']))) for (c,s),p in panels.items()},
        paired_contrasts=contrasts,teacher_ensemble_reference=ensembles,nonoverlapping_offsets=offsets,
        limitations=['Historical validation exposure','Three fitted seeds','Intervals condition on fitted models and observed calendar','Guidance and teacher ensembling are mixed in G versus C','F29 adds at most 15 distinct channels','T − L includes both the ODST head and the extra teacher training after the L encoder is copied; it is not a pure head effect.']))
