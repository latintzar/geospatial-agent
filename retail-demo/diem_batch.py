"""Bounded DuckDB adapter using the recovered project's unmodified DIEM functions."""
import ast, math, os, warnings
from pathlib import Path
import duckdb, h3, numpy as np
SOURCE=Path(os.environ.get("GEOSPATIAL_SOURCE", Path(__file__).resolve().parent.parent)).resolve()
MATRIX=Path(os.environ.get("LONDON_MATRIX", Path(__file__).resolve().parent / "synthetic-example.parquet")).resolve()
# Extract the original pure functions without importing its optional cloud stack.
tree=ast.parse((SOURCE/'backend/tools/tools_diem_search.py').read_text())
nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in ('compute_diem_parameters','compute_diem')]
assert len(nodes)==2
ns={'np':np,'math':math,'Optional':__import__('typing').Optional,'Tuple':__import__('typing').Tuple}
exec(compile(ast.Module(body=nodes,type_ignores=[]),str(SOURCE/'backend/tools/tools_diem_search.py'),'exec'),ns)
compute_diem=ns['compute_diem']
def search(lat,lng,top_k=100,batch_size=512):
    db=duckdb.connect(); path=str(MATRIX); schema=db.execute('DESCRIBE SELECT * FROM read_parquet(?)',[path]).fetchall()
    numeric=('TINYINT','SMALLINT','INTEGER','BIGINT','HUGEINT','UTINYINT','USMALLINT','UINTEGER','UBIGINT','FLOAT','DOUBLE','DECIMAL')
    cols=[r[0] for r in schema if r[0]!='h3_index' and r[1].startswith(numeric)]
    if not cols: raise ValueError('No numeric features in matrix')
    query='SELECT h3_index,'+','.join('"'+x.replace('"','""')+'"' for x in cols)+' FROM read_parquet(?)'
    ref_hex=h3.latlng_to_cell(lat,lng,10); ref=None; mn=np.full(len(cols),np.inf);mx=np.full(len(cols),-np.inf)
    cursor=db.execute(query,[path])
    with warnings.catch_warnings():
        warnings.filterwarnings('ignore',message='All-NaN slice encountered')
        while rows:=cursor.fetchmany(batch_size):
            values=np.asarray([r[1:] for r in rows],dtype=np.float64)
            mn=np.fmin(mn,np.nanmin(values,axis=0));mx=np.fmax(mx,np.nanmax(values,axis=0))
            for i,r in enumerate(rows):
                if r[0]==ref_hex:ref=values[i].copy()
    if ref is None:raise ValueError('Selected location is outside the supplied matrix')
    mn[np.isinf(mn)]=np.nan;mx[np.isinf(mx)]=np.nan
    excluded=set(h3.grid_disk(ref_hex,15));results=[];total=0;sum_scores=0
    cursor=db.execute(query,[path])
    while rows:=cursor.fetchmany(batch_size):
        values=np.asarray([r[1:] for r in rows],dtype=np.float64);scores=compute_diem(ref,values,mn,mx)
        total+=len(scores);sum_scores+=float(scores.sum())
        results.extend((r[0],float(s)) for r,s in zip(rows,scores) if r[0] not in excluded)
    results.sort(key=lambda r:r[1],reverse=True);results=results[:max(1,min(top_k,1000))]
    # pandas rank(pct=True), including average rank for ties, as in the source.
    vals=np.array([x[1] for x in results]); ranks=np.empty(len(vals)); order=np.argsort(vals,kind='stable');i=0
    while i<len(order):
        j=i+1
        while j<len(order) and vals[order[j]]==vals[order[i]]:j+=1
        ranks[order[i:j]]=(i+1+j)/(2*len(vals));i=j
    matches=[{'hex':h,'similarity':s,'percentile':float(rank*100),'value':float(rank**2.5*100)} for (h,s),rank in zip(results,ranks)]
    rlat,rlng=h3.cell_to_latlng(ref_hex)
    return {'reference':{'hex':ref_hex,'lat':rlat,'lng':rlng,'description':None,'starter_pack':None,'top_scores':[]},'similar_hexes':matches,'stats':{'total_hexes':total,'feature_dimensions':len(cols),'top_k':top_k,'mean_similarity':sum_scores/total,'max_similarity':results[0][1] if results else 0,'min_similarity':results[-1][1] if results else 0}}
