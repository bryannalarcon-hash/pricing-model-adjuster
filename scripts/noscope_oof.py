import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import numpy as np, pandas as pd
from sklearn.model_selection import StratifiedKFold
from houseprice.data_load import load_dataset, labeled
from houseprice.features import build_features
from houseprice.eval import ape, mape, baseline_blended, stratify_key
from houseprice.model_v2 import ConformalPriceModelV2
df=load_dataset(); lab=labeled(df).reset_index(drop=True)
lab_idx=df.index[df.is_labeled].tolist()
scope=pd.read_parquet('data/processed/scope.parquet').reindex(lab_idx).reset_index(drop=True)
fp=lab.final_price.values; oe=lab.original_estimate.values
base=np.asarray(ape(oe,fp)); real=base>0.20
def oofrun(sc):
    X,_=build_features(lab, scope_df=sc)
    bl,rl=[],[]
    for s in range(8):
        mid=np.full(len(lab),np.nan)
        for tr,te in StratifiedKFold(5,shuffle=True,random_state=s).split(lab,stratify_key(lab)):
            m=ConformalPriceModelV2(weight_power=0.5,seed=s).fit(X.iloc[tr],fp[tr],oe[tr])
            mid[te]=m.predict(X.iloc[te],oe[te])[:,1]
        bl.append(mape(mid,fp)); rl.append(mape(mid[real],fp[real]))
    return np.mean(bl),np.std(bl),np.mean(rl),np.std(rl)
print(f"baseline blended {baseline_blended(lab):.2f} real {100*base[real].mean():.2f}")
b=oofrun(scope); print(f"with-scope: blended {b[0]:.2f}±{b[1]:.2f} real {b[2]:.2f}±{b[3]:.2f}")
b=oofrun(None);  print(f"no-scope  : blended {b[0]:.2f}±{b[1]:.2f} real {b[2]:.2f}±{b[3]:.2f}")
print("DONE_NS")
