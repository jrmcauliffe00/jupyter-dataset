import json
import re
from pathlib import Path

import nbformat
import pandas as pd
from jupyter_dataset import handlers


async def test_get_example(jp_fetch):
    # When
    response = await jp_fetch("jupyter-dataset", "get-example")

    # Then
    assert response.code == 200
    payload = json.loads(response.body)
    assert payload == {
        "data": "This is /jupyter-dataset/get-example endpoint!"
    }


async def test_list_datasets_and_notebooks(jp_fetch, jp_serverapp, tmp_path, monkeypatch):
    dataset_root = tmp_path / "datasets"
    dataset_dir = dataset_root / "demo"
    dataset_dir.mkdir(parents=True)
    data_file = dataset_dir / "sample.csv"
    data_file.write_text("value,name\n1,a\n2,b\n", encoding="utf-8")
    monkeypatch.setattr(handlers, "DATASET_ROOT", dataset_root)

    notebook_path = Path(jp_serverapp.root_dir) / "transform.ipynb"
    notebook = nbformat.v4.new_notebook(
        cells=[nbformat.v4.new_code_cell("result = df", metadata={"tags": ["dataset-transform"]})]
    )
    nbformat.write(notebook, notebook_path)

    datasets_response = await jp_fetch("jupyter-dataset", "datasets")
    notebooks_response = await jp_fetch("jupyter-dataset", "notebooks")

    assert datasets_response.code == 200
    assert notebooks_response.code == 200

    datasets_payload = json.loads(datasets_response.body)
    notebooks_payload = json.loads(notebooks_response.body)

    assert datasets_payload["dataset_root"] == str(dataset_root)
    assert len(datasets_payload["datasets"]) == 1
    assert datasets_payload["datasets"][0]["name"] == "demo"
    assert datasets_payload["datasets"][0]["files"][0]["path"] == "demo/sample.csv"

    assert "transform.ipynb" in notebooks_payload["notebooks"]


async def test_apply_creates_subset_by_default(jp_fetch, jp_serverapp, tmp_path, monkeypatch):
    dataset_root = tmp_path / "datasets"
    dataset_dir = dataset_root / "demo"
    dataset_dir.mkdir(parents=True)
    data_file = dataset_dir / "sample.csv"
    pd.DataFrame({"value": [1, 2, 3], "name": ["a", "b", "c"]}).to_csv(
        data_file, index=False
    )
    monkeypatch.setattr(handlers, "DATASET_ROOT", dataset_root)

    notebook_path = Path(jp_serverapp.root_dir) / "transform.ipynb"
    notebook = nbformat.v4.new_notebook(
        cells=[
            nbformat.v4.new_code_cell(
                "result = df[df['value'] >= 2]",
                metadata={"tags": ["dataset-transform"]},
            )
        ]
    )
    nbformat.write(notebook, notebook_path)

    response = await jp_fetch(
        "jupyter-dataset",
        "apply",
        method="POST",
        body=json.dumps(
            {
                "dataset_file": "demo/sample.csv",
                "notebook_path": "transform.ipynb",
                "cell_tag": "dataset-transform",
                "save_mode": "subset",
            }
        ),
        headers={"Content-Type": "application/json"},
    )
    assert response.code == 200
    payload = json.loads(response.body)
    assert payload["status"] == "ok"
    assert payload["dataset_file"] == "demo/sample.csv"
    assert re.match(r"^demo__\d{8}T\d{6}Z/sample\.csv$", payload["output_file"])
    assert payload["output_file"].endswith("/sample.csv")
    assert payload["rows"] == 2

    original_df = pd.read_csv(data_file)
    assert len(original_df) == 3

    output_path = dataset_root / payload["output_file"]
    subset_df = pd.read_csv(output_path)
    assert subset_df["value"].tolist() == [2, 3]


async def test_apply_uses_custom_new_dataset_name(
    jp_fetch, jp_serverapp, tmp_path, monkeypatch
):
    dataset_root = tmp_path / "datasets"
    dataset_dir = dataset_root / "demo"
    dataset_dir.mkdir(parents=True)
    data_file = dataset_dir / "sample.csv"
    pd.DataFrame({"value": [1, 2, 3], "name": ["a", "b", "c"]}).to_csv(
        data_file, index=False
    )
    monkeypatch.setattr(handlers, "DATASET_ROOT", dataset_root)

    notebook_path = Path(jp_serverapp.root_dir) / "transform.ipynb"
    notebook = nbformat.v4.new_notebook(
        cells=[
            nbformat.v4.new_code_cell(
                "result = df[df['value'] >= 2]",
                metadata={"tags": ["dataset-transform"]},
            )
        ]
    )
    nbformat.write(notebook, notebook_path)

    response = await jp_fetch(
        "jupyter-dataset",
        "apply",
        method="POST",
        body=json.dumps(
            {
                "dataset_file": "demo/sample.csv",
                "notebook_path": "transform.ipynb",
                "cell_tag": "dataset-transform",
                "save_mode": "subset",
                "new_dataset_name": "education_subset",
            }
        ),
        headers={"Content-Type": "application/json"},
    )
    assert response.code == 200
    payload = json.loads(response.body)
    assert payload["output_file"] == "education_subset/sample.csv"


async def test_apply_fails_for_missing_tag(jp_fetch, jp_serverapp, tmp_path, monkeypatch):
    dataset_root = tmp_path / "datasets"
    dataset_dir = dataset_root / "demo"
    dataset_dir.mkdir(parents=True)
    data_file = dataset_dir / "sample.csv"
    data_file.write_text("value\n1\n2\n", encoding="utf-8")
    monkeypatch.setattr(handlers, "DATASET_ROOT", dataset_root)

    notebook_path = Path(jp_serverapp.root_dir) / "transform.ipynb"
    notebook = nbformat.v4.new_notebook(
        cells=[nbformat.v4.new_code_cell("result = df")]
    )
    nbformat.write(notebook, notebook_path)

    response = await jp_fetch(
        "jupyter-dataset",
        "apply",
        method="POST",
        body=json.dumps(
            {
                "dataset_file": "demo/sample.csv",
                "notebook_path": "transform.ipynb",
                "cell_tag": "dataset-transform",
            }
        ),
        headers={"Content-Type": "application/json"},
    )
    assert response.code == 400
    payload = json.loads(response.body)
    assert "No code cell found" in payload["reason"]