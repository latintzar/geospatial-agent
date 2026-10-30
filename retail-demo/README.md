# Retail location similarity example

A working companion to the recovered Leo similarity code. Select one of three example locations to compare synthetic H3 feature vectors. The values are generated examples, not observations of London. Search runs the historical Leo calibrated-distance approximation in `backend/tools/tools_diem_search.py`.

```sh
python -m venv .venv
. .venv/bin/activate
pip install -r retail-demo/requirements.txt
python retail-demo/server.py
```

Open http://127.0.0.1:18869. Run `python retail-demo/create_synthetic.py` from the retail-demo directory to regenerate the sample. The original privately verified matrix contains 131,596 London H3 cells and 1,956 numeric features; its precise upstream contributor ledger remains unresolved, so it is not included. No global matrix has been verified. The score is Leo’s independently expressed approximation inspired by DIEM, not the published reference implementation.
