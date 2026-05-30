import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import numpy as np, pandas as pd
from houseprice.data_load import load_dataset, labeled
from houseprice.features import build_features
from houseprice.eval import ape, mape, baseline_blended
from houseprice.model_v2 import oof_predict_bagged
df=load_dataset(); lab=labeled(df).reset_index(drop=True)
base=np.asarray(ape(lab.original_estimate, lab.final_price)); real=base>0.20
fp=lab.final_price.values
print(f"baseline blended {baseline_blended(lab):.2f} real {100*base[real].mean():.2f}")
for p in [0.3,0.4,0.5,0.6,0.7,0.8]:
    lo,mid,hi=oof_predict_bagged(lab, build_features, seeds=range(6), weight_power=p)
    cov=((fp>=lo)&(fp<=hi)).mean()
    print(f"power={p}: blended {mape(mid,fp):.2f}  real {mape(mid[real],fp[real]):.2f}  cov {100*cov:.1f}%")
print("DONE_PW")
