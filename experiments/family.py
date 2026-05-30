import os, sys
sys.path.insert(0, os.path.dirname(__file__)); sys.path.insert(0, os.path.join(os.path.dirname(__file__),"..","src"))
import numpy as np, pandas as pd
from harness import evaluate, get_labeled
from models import _X, _resid, LGBMResidual

class SkResidual:
    def __init__(self, ctor, weighted=True): self.ctor=ctor; self.weighted=weighted
    def fit(self, lab):
        X=_X(lab); self.names=list(X.columns); self.m=self.ctor()
        w=1/np.clip(lab.final_price.values,1,None)**0.5; w/=w.mean()
        try: self.m.fit(X,_resid(lab.final_price,lab.original_estimate), sample_weight=w if self.weighted else None)
        except TypeError: self.m.fit(X,_resid(lab.final_price,lab.original_estimate))
        return self
    def predict(self, lab):
        oe=np.clip(lab.original_estimate.values.astype(float),1,None)
        from houseprice.features import align_to
        return oe*np.exp(self.m.predict(align_to(_X(lab),self.names)))

class PointEnsemble:
    def __init__(self, objs): self.objs=objs
    def fit(self, lab): self.ms=[LGBMResidual(objective=o, n_jobs=1).fit(lab) for o in self.objs]; return self
    def predict(self, lab):
        oe=np.clip(lab.original_estimate.values.astype(float),1,None)
        rs=[np.log(np.clip(m.predict(lab),1,None)/oe) for m in self.ms]
        return oe*np.exp(np.mean(rs,axis=0))

from sklearn.ensemble import RandomForestRegressor, ExtraTreesRegressor, HistGradientBoostingRegressor
from sklearn.neural_network import MLPRegressor
facs={
 "lgbm_wl2 (ref)": lambda: __import__('models').WeightedLGBM(objective="regression",power=0.5,n_jobs=1),
 "hist_gb": lambda: SkResidual(lambda: HistGradientBoostingRegressor(max_depth=4,learning_rate=0.05,max_iter=300,l2_regularization=1.0)),
 "random_forest": lambda: SkResidual(lambda: RandomForestRegressor(n_estimators=400,max_depth=8,min_samples_leaf=5,n_jobs=1)),
 "extra_trees": lambda: SkResidual(lambda: ExtraTreesRegressor(n_estimators=400,max_depth=10,min_samples_leaf=5,n_jobs=1)),
 "mlp": lambda: SkResidual(lambda: MLPRegressor(hidden_layer_sizes=(64,32),alpha=0.01,max_iter=500,early_stopping=True), weighted=False),
 "ens_l2_huber_fair": lambda: PointEnsemble(["regression","huber","fair"]),
}
lab=get_labeled()
from houseprice.eval import ape, baseline_blended
b=np.asarray(ape(lab.original_estimate,lab.final_price)); print(f"baseline blended {baseline_blended(lab):.2f} real {100*b[b>0.2].mean():.2f}")
for n,f in facs.items():
    try:
        r=evaluate(f,lab,seeds=range(6)); print(f"{n:18s} blended {r['blended']:.2f}±{r['blended_std']:.2f}  real {r['real']:.2f}±{r['real_std']:.2f}")
    except Exception as e: print(f"{n:18s} ERROR {str(e)[:60]}")
print("DONE_FAM")
