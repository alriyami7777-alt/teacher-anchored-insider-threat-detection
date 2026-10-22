"""Pinned producing model with explicit construction and transfer contracts."""
import json
from pathlib import Path
import torch
from contracts import sha,phase_seed,reset_rng,state_hash

BASE=Path(__file__).resolve().parent

def verify_vendor():
    for item in json.loads((BASE/'SOURCE_PINS.json').read_text()):
        if sha(BASE/item['vendored_file'])!=item['vendored_sha256']:raise RuntimeError('Producing source drift')

def build(schema,width,partition,seed,condition):
    verify_vendor()
    from cert_stage2_producing.architecture import AttentionNodeEnsemble
    reset_rng(phase_seed(schema,partition,seed,'construct_L' if condition=='L' else 'construct_T'))
    model=AttentionNodeEnsemble(input_dim=width,hidden_size=64,dropout=.2,attention_dim=64,
        fusion_variant='attention_linear_reference' if condition=='L' else 'sparsemax_sigmoid_odst',
        node_num_layers=2,node_n_trees=4,node_depth=4,node_tree_dim=1,node_temperature=.5,node_dropout=0.,leaf_init_std=.05)
    if model.encoder_dim!=128 or [x.in_dim for x in model.node_head.layers]!=[128,132]:raise RuntimeError('ODST width drift')
    return model

def copy_encoder(teacher,precursor_state):
    copied={k:v for k,v in precursor_state.items() if k.startswith(('lstm.','attention.'))}
    expected={k for k in teacher.state_dict() if k.startswith(('lstm.','attention.'))}
    if set(copied)!=expected:raise RuntimeError('Precursor transfer allowlist mismatch')
    state=teacher.state_dict();state.update(copied);teacher.load_state_dict(state,strict=True)
    return sorted(copied)

def configure_model(model,condition,epoch):
    for p in model.parameters():p.requires_grad=False
    model.train()
    if condition=='L':modules=[model.lstm,model.attention,model.linear_head]
    elif condition=='T' and epoch<=3:
        modules=[model.node_head];model.lstm.eval();model.attention.eval();model.dropout.eval()
    else:modules=[model.lstm,model.attention,model.node_head]
    for module in modules:
        for p in module.parameters():p.requires_grad=True
    for p in model.node_head.output_head.parameters():p.requires_grad=False

def optimizer(model,condition,epoch):
    configure_model(model,condition,epoch)
    modules=[(model.lstm,0.001 if condition=='L' else 3e-5),(model.attention,0.001 if condition=='L' else 3e-5),
             (model.linear_head if condition=='L' else model.node_head,.001)]
    groups=[dict(params=[p for p in m.parameters() if p.requires_grad],lr=lr) for m,lr in modules if any(p.requires_grad for p in m.parameters())]
    return torch.optim.Adam(groups,betas=(.9,.999),eps=1e-8,weight_decay=0.,amsgrad=False,foreach=False,fused=False)

def training_seed(schema,partition,seed,condition):
    return phase_seed(schema,partition,seed,'student' if condition in ('C','G') else 'train_'+condition)

def loss(logit,label,positive_weight,targets=None):
    result=torch.nn.functional.binary_cross_entropy_with_logits(logit,label,pos_weight=logit.new_tensor(positive_weight),reduction='mean')
    return result if targets is None else result+.5*((logit-targets.detach())**2).mean()
