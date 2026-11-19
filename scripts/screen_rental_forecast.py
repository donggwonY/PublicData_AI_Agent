"""Exploratory within-file rent forecasting; no cross-redesign joining."""
import argparse, csv, hashlib, json
from pathlib import Path
from statistics import mean

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("source",type=Path); args=ap.parse_args()
    summaries=[]; scores=[]
    for f in sorted(args.source.glob("*임대*소규모*.csv")):
        raw=f.read_bytes(); rows=list(csv.reader(raw.decode("cp949").splitlines()))
        quarters=rows[0][4:]; data=[r for r in rows[3:] if len(r)>4 and r[1]=="대구"]
        summaries.append(dict(file=f.name,sha256=hashlib.sha256(raw).hexdigest(),quarters=quarters,daegu_rows=len(data)))
        if len(quarters)<8: continue
        for r in data:
            try: y=list(map(float,r[4:]))
            except ValueError: continue
            assert len(y)==len(quarters)
            for t in range(4,len(y)):
                h=y[t-4:t]; avg=mean(h)
                slope=sum((i-1.5)*(v-avg) for i,v in enumerate(h))/5
                preds={"last_quarter":h[-1],"same_quarter_last_year":h[0],"four_quarter_mean":avg,"four_quarter_linear":max(0,avg+2.5*slope)}
                for model,pred in preds.items():
                    scores.append(dict(file=f.name,area=r[2],quarter=quarters[t],model=model,actual=y[t],prediction=pred,absolute_error=abs(pred-y[t])))
    out=Path("docs/d05/topic_screening");out.mkdir(parents=True,exist_ok=True)
    metrics=[]
    for name in sorted({s["file"] for s in scores}):
        for model in sorted({s["model"] for s in scores}):
            ss=[s for s in scores if s["file"]==name and s["model"]==model]
            metrics.append(dict(file=name,model=model,n=len(ss),mae=mean(s["absolute_error"] for s in ss)))
    result=dict(files=summaries,metrics=metrics,unit="thousand KRW per square metre",scope="Exploratory current-vintage within-file backtest; no historical release/vintage validation, no independent final holdout; rows may include regional aggregates and are not independent",rule="Four prior quarters only; fixed models; never join files across redesign boundaries")
    (out/"rental_screening.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    with (out/"rental_predictions.csv").open("w",encoding="utf-8-sig",newline="") as fp:
        w=csv.DictWriter(fp,fieldnames=list(scores[0]));w.writeheader();w.writerows(scores)
    print(json.dumps(metrics,ensure_ascii=False,indent=2))
if __name__=="__main__": main()
