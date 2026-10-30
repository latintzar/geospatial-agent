"""Create clearly synthetic features for local interface testing."""
import duckdb,h3,random
rng=random.Random(42); db=duckdb.connect();db.execute('CREATE TABLE points(h3_index VARCHAR, cafe_count DOUBLE, building_count DOUBLE, avg_building_height DOUBLE, avg_floors DOUBLE, building_density DOUBLE)')
for group,(lat,lon) in enumerate([(51.5117,-.124),(51.5255,-.078),(51.5136,-.135)]):
 for cell in [h3.latlng_to_cell(lat,lon,10)]+sorted(set(h3.grid_disk(h3.latlng_to_cell(lat,lon,10),3))-{h3.latlng_to_cell(lat,lon,10)})[:29]:
  db.execute('INSERT INTO points VALUES (?,?,?,?,?,?)',[cell,10+group*4+rng.random()*5,20+group*3+rng.random()*10,8+group+rng.random()*4,3+group+rng.random(),100+group*10+rng.random()*20])
db.execute("COPY points TO 'synthetic-example.parquet' (FORMAT PARQUET)")
