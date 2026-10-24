import json

import duckdb
import pandas as pd

from crypto_strategy_lab.feature_research import _write_parquet_atomic


def test_sr_json_snapshots_export_in_small_groups_without_changing_rows(tmp_path):
    frame=pd.DataFrame(dict(index=range(5000),snapshot=[json.dumps(dict(index=i,zones=[{'low':i,'high':i+1}]*20)) for i in range(5000)]))
    path=tmp_path/'sr_zones.parquet'
    _write_parquet_atomic(frame,path)
    con=duckdb.connect()
    try:
        metadata=con.execute('SELECT DISTINCT row_group_id,row_group_num_rows FROM parquet_metadata(?)',[str(path)]).fetchall()
        assert len(metadata)>1 and max(n for _,n in metadata)<=2048
        restored=con.execute('SELECT * FROM read_parquet(?) ORDER BY index',[str(path)]).df()
        pd.testing.assert_frame_equal(restored,frame)
    finally:
        con.close()
