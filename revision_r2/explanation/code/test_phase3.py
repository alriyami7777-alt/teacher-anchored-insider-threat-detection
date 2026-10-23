"""CPU-only synthetic tests. Never imports or executes the HOLDOUT script."""
import ast
import hashlib
from pathlib import Path
import tempfile
import unittest
import numpy as np
from phase3_engine import *
from run_phase3 import gate_ready,MARKER

class Tests(unittest.TestCase):
    def test_pseudonym(self):
        self.assertEqual(pseudonym('synthetic_user'),'U_'+hashlib.sha256(b'synthetic_user').hexdigest()[:10])
        self.assertEqual(len(pseudonym('synthetic_user')),12)

    def test_ig_linear_all_targets_and_completeness(self):
        import torch
        torch.set_num_threads(2)
        class Forward:
            device='cpu'
            def __call__(self,x):
                v=x.reshape(len(x),-1) @ torch.arange(260,dtype=torch.float32)/260
                trees=v[:,None]*torch.arange(1,9,dtype=torch.float32)[None,:]
                return torch.cat((trees,trees.mean(1,keepdim=True)),1)
        x=np.random.default_rng(5).normal(size=(3,20,13)).astype(np.float32)
        b=np.full((20,13),.2,np.float32)
        a,d,r,e=integrated_gradients(Forward(),x,b,batch_size=2)
        expected=(x-b)[:,None]*np.arange(260).reshape(1,1,20,13)/260
        expected=expected*np.arange(1,9).reshape(1,8,1,1)
        np.testing.assert_allclose(a[:,:8],expected,atol=5e-6,rtol=2e-6)
        np.testing.assert_allclose(a[:,-1],a[:,:8].mean(1),atol=1e-5,rtol=2e-6)
        self.assertLess(float(e.max()),2e-5)

    def test_aggregation_schema(self):
        x=np.arange(2*20*13,dtype=np.float32).reshape(2,20,13)
        a=aggregate40(x)
        self.assertEqual(a.shape,(2,40)); self.assertEqual(len(SUMMARY_NAMES),40)
        np.testing.assert_allclose(a[:,0],x[:,:,0].sum(1))
        np.testing.assert_allclose(a[:,3],x[:,:,0].std(1))
        np.testing.assert_allclose(a[:,28],x[:,:,7].sum(1))
        self.assertEqual(sum(map(len,group_columns('XGBoost_40','source'))),30)
        self.assertEqual(sum(map(len,group_columns('XGBoost_40','raw_feature'))),40)

    def test_interventions_sign_reference_and_random(self):
        x=np.array([[3,2,-1,-4],[1,0,0,0]],np.float32)
        reference=np.array([.5,.5,.5,.5],np.float32)
        attr=x-reference
        groups=[np.array([j]) for j in range(4)]
        result=interventions(lambda z:z.sum(1),x,reference,attr,groups,[1,3],draws=200)
        self.assertEqual(result[(1,1)]['signed_change'][0],2.5)
        self.assertEqual(result[(1,-1)]['signed_change'][0],4.5)
        self.assertEqual(result[(1,1)]['random_accuracy'][0],1)
        self.assertTrue(np.isnan(result[(3,1)]['signed_change']).all())
        # Every random draw is signed correctly; duplicates retain draw weight.
        self.assertGreater(result[(1,1)]['random_signed_change'][0],1.5)

    def test_replace_whole_feature_all_days(self):
        x=np.ones((2,20,13),np.float32); b=np.zeros((20,13),np.float32)
        attr=np.tile(np.arange(1,14),(2,1))
        r=interventions(lambda z:z.sum((1,2)),x,b,attr,group_columns('TA2','feature'),[3])
        np.testing.assert_equal(r[(3,1)]['signed_change'],60)

    def test_cluster_weighting_pairing_and_missingness(self):
        users=np.array(['U_a','U_a','U_b']); values=np.array([1.,1.,0.])
        s=cluster_summary(np.column_stack((values,values*2)),users)
        self.assertAlmostEqual(s['mean'][0],2/3)
        np.testing.assert_allclose(s['ci_low'][1],s['ci_low'][0]*2)
        np.testing.assert_allclose(s['ci_high'][1],s['ci_high'][0]*2)
        s=cluster_summary([np.nan,np.nan,1],users)
        self.assertEqual(s['n_valid'][0],1)

    def test_paired_primary_direction_and_joint_eligibility(self):
        y=np.array([1,0,1]); users=np.array(['U_a','U_b','U_c'])
        ta={}; xg={}
        for seed in SEEDS:
            ta[seed]={}; xg[seed]={}
            for sign in (1,-1):
                ta[seed][(3,sign)]={'accuracy':np.ones(3),'random_accuracy':np.full(3,.5)}
                xg[seed][(3,sign)]={'accuracy':np.array([0.,1.,np.nan]),'random_accuracy':np.full(3,.5)}
        r=paired_primary(ta,xg,users,y)
        s=[a for a in r if a['seed']=='mean_of_seeds' and a['stratum']=='overall' and
           a['sign']=='class_supporting' and a['metric']=='TA2_minus_XGBoost_directional_accuracy'][0]
        self.assertEqual(s['n_paired'],2); self.assertEqual(s['estimate'],.5)

    def test_gpu_gate_exact_end(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'report.md'; self.assertFalse(gate_ready(p))
            p.write_text(MARKER+'\n\n'); self.assertTrue(gate_ready(p))
            p.write_text(MARKER+'\nSCORING_COMPLETE'); self.assertFalse(gate_ready(p))
            p.write_text('NOT_'+MARKER); self.assertFalse(gate_ready(p))

    def test_holdout_script_syntax_only(self):
        # Explicitly parse without running or importing this script.
        ast.parse(Path('holdout_explanation_scoring.py').read_text())

if __name__=='__main__': unittest.main(verbosity=2)
