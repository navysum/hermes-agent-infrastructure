#!/usr/bin/env python3
from __future__ import annotations
import importlib.util, json, sys
from pathlib import Path
from datetime import datetime, timezone
import pandas as pd

spec = importlib.util.spec_from_file_location('opt', '/root/bots/forexbot/shadow/scalping_mtf_optimizer.py')
opt = importlib.util.module_from_spec(spec); sys.modules['opt'] = opt; spec.loader.exec_module(opt)
orig_signal = opt.signal_side

def eval_run(invert=False, count=8000):
    if invert:
        opt.signal_side = lambda df, i, p: -orig_signal(df, i, p)
    else:
        opt.signal_side = orig_signal
    out = []
    for pair in opt.PAIRS:
        raw = opt.fetch_history_robust(pair, count, use_cache=True)
        feat = opt.prep(raw)
        for p in opt.make_grid():
            trades = opt.run_backtest(feat, pair, p)
            tr, oos = opt.split_by_time(trades)
            if len(trades) >= 12 and len(oos) >= 4:
                out.append({'pair':pair,'invert':invert,'params':opt.asdict(p),'overall':opt.summarize(trades),'train_70pct':opt.summarize(tr),'oos_30pct':opt.summarize(oos),'trades':trades})
    return out

normal = eval_run(False)
inv = eval_run(True)
allres = normal + inv
rank = sorted(allres, key=lambda r: (r['oos_30pct']['expectancy_r'], r['oos_30pct']['profit_factor'] or 0, r['overall']['expectancy_r'], r['oos_30pct']['trades']), reverse=True)
combo = {}
for r in allres:
    key = json.dumps({'invert':r['invert'], **r['params']}, sort_keys=True)
    combo.setdefault(key, {'invert':r['invert'], 'params':r['params'], 'trades':[]})['trades'].extend(r['trades'])
combor=[]
for v in combo.values():
    trades=sorted(v['trades'], key=lambda x: x['entry_time'])
    tr,oos=opt.split_by_time(trades)
    if len(trades)>=40 and len(oos)>=10:
        combor.append({'invert':v['invert'],'params':v['params'],'overall':opt.summarize(trades),'train_70pct':opt.summarize(tr),'oos_30pct':opt.summarize(oos)})
combor=sorted(combor, key=lambda r:(r['oos_30pct']['expectancy_r'], r['oos_30pct']['profit_factor'] or 0, r['overall']['expectancy_r']), reverse=True)
ts=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
outdir=Path('/root/bots/forexbot/shadow/results'); outdir.mkdir(parents=True, exist_ok=True)
summary={'generated_at_utc':ts,'purpose':'Test whether the rejected strategy families are better inverted/faded rather than followed. Read-only shadow backtest.','top_combined':combor[:20],'top_pair':[{k:v for k,v in r.items() if k!='trades'} for r in rank[:40]]}
path=outdir/f'scalping_mtf_fliptest_summary_{ts}.json'; path.write_text(json.dumps(summary,indent=2),encoding='utf-8')
print(json.dumps({'summary_path':str(path),'top_combined':combor[:8],'top_pair':[{k:v for k,v in r.items() if k!='trades'} for r in rank[:12]]},indent=2))
