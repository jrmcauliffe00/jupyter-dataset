import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import nbformat
import pandas as pd
import tornado
from jupyter_server.base.handlers import APIHandler
from jupyter_server.utils import url_path_join

DATASET_ROOT = Path("/opt/datasets")
SUPPORTED_EXTENSIONS = (".csv", ".tsv", ".parquet", ".json", ".jsonl")
DEFAULT_CELL_TAG = "dataset-transform"
SAVE_MODE_SUBSET = "subset"
SAVE_MODE_IN_PLACE = "in_place"
SAVE_MODES = {SAVE_MODE_SUBSET, SAVE_MODE_IN_PLACE}


def _resolve_path(raw_path: str, root_dir: Path) -> Path:
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = root_dir / candidate
    return candidate.resolve()


def _require_within_root(path: Path, root_dir: Path, label: str) -> None:
    try:
        path.relative_to(root_dir)
    except ValueError as exc:
        raise tornado.web.HTTPError(
            400, reason=f"{label} must live under {root_dir}"
        ) from exc


def _is_supported_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS


def _iter_supported_files(dataset_dir: Path) -> list[Path]:
    return [
        path
        for path in sorted(dataset_dir.rglob("*"))
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
    ]


def _read_dataframe(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path)
    if suffix == ".tsv":
        return pd.read_csv(path, sep="\t")
    if suffix == ".parquet":
        return pd.read_parquet(path)
    if suffix == ".json":
        return pd.read_json(path)
    if suffix == ".jsonl":
        return pd.read_json(path, lines=True)
    raise tornado.web.HTTPError(400, reason=f"Unsupported file extension: {suffix}")


def _write_dataframe(path: Path, dataframe: pd.DataFrame) -> None:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        dataframe.to_csv(path, index=False)
        return
    if suffix == ".tsv":
        dataframe.to_csv(path, sep="\t", index=False)
        return
    if suffix == ".parquet":
        dataframe.to_parquet(path, index=False)
        return
    if suffix == ".json":
        dataframe.to_json(path, orient="records")
        return
    if suffix == ".jsonl":
        dataframe.to_json(path, orient="records", lines=True)
        return
    raise tornado.web.HTTPError(400, reason=f"Unsupported file extension: {suffix}")


def _subset_output_path(source_path: Path, subset_name: str | None) -> Path:
    subsets_dir = source_path.parent / "subsets"
    subsets_dir.mkdir(parents=True, exist_ok=True)

    if subset_name:
        safe_subset_name = "".join(
            ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in subset_name
        ).strip("_")
    else:
        safe_subset_name = ""

    if not safe_subset_name:
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        safe_subset_name = f"{source_path.stem}__subset__{timestamp}"

    return subsets_dir / f"{safe_subset_name}{source_path.suffix.lower()}"


def _read_notebook(notebook_path: Path) -> dict[str, Any]:
    try:
        return nbformat.read(notebook_path, as_version=4)
    except Exception as exc:
        raise tornado.web.HTTPError(
            400, reason=f"Failed to read notebook {notebook_path}: {exc}"
        ) from exc


def _find_tagged_code_cell(notebook: dict[str, Any], cell_tag: str) -> tuple[int, str]:
    for index, cell in enumerate(notebook.get("cells", [])):
        if cell.get("cell_type") != "code":
            continue
        tags = cell.get("metadata", {}).get("tags", [])
        if cell_tag in tags:
            return index, cell.get("source", "")
    raise tornado.web.HTTPError(
        400, reason=f"No code cell found with tag '{cell_tag}'."
    )


def _notebook_root(handler: APIHandler) -> Path:
    contents_manager = handler.settings.get("contents_manager")
    if contents_manager is None:
        raise tornado.web.HTTPError(500, reason="Contents manager unavailable.")
    return Path(contents_manager.root_dir).resolve()


class RouteHandler(APIHandler):
    @tornado.web.authenticated
    def get(self) -> None:
        self.finish(json.dumps({"data": "This is /jupyter-dataset/get-example endpoint!"}))


class DatasetListHandler(APIHandler):
    @tornado.web.authenticated
    def get(self) -> None:
        datasets = []
        if DATASET_ROOT.exists() and DATASET_ROOT.is_dir():
            for dataset_dir in sorted(DATASET_ROOT.iterdir()):
                if not dataset_dir.is_dir():
                    continue
                files = _iter_supported_files(dataset_dir)
                datasets.append(
                    {
                        "name": dataset_dir.name,
                        "path": str(dataset_dir),
                        "files": [
                            {
                                "name": file_path.name,
                                "path": file_path.relative_to(DATASET_ROOT).as_posix(),
                                "size_bytes": file_path.stat().st_size,
                            }
                            for file_path in files
                        ],
                    }
                )

        self.finish(
            json.dumps(
                {
                    "dataset_root": str(DATASET_ROOT),
                    "supported_extensions": list(SUPPORTED_EXTENSIONS),
                    "datasets": datasets,
                }
            )
        )


class NotebookListHandler(APIHandler):
    @tornado.web.authenticated
    def get(self) -> None:
        notebook_root = _notebook_root(self)
        notebooks: list[str] = []
        for path in sorted(notebook_root.rglob("*.ipynb")):
            if ".ipynb_checkpoints" in path.parts:
                continue
            notebooks.append(path.relative_to(notebook_root).as_posix())

        self.finish(
            json.dumps({"notebook_root": str(notebook_root), "notebooks": notebooks})
        )


class ApplyDatasetHandler(APIHandler):
    @tornado.web.authenticated
    def post(self) -> None:
        body = self.get_json_body() or {}
        dataset_file = (body.get("dataset_file") or "").strip()
        notebook_path_value = (body.get("notebook_path") or "").strip()
        cell_tag = (body.get("cell_tag") or DEFAULT_CELL_TAG).strip()
        save_mode = (body.get("save_mode") or SAVE_MODE_SUBSET).strip()
        subset_name = (body.get("subset_name") or "").strip() or None

        if not dataset_file:
            raise tornado.web.HTTPError(400, reason="dataset_file is required.")
        if not notebook_path_value:
            raise tornado.web.HTTPError(400, reason="notebook_path is required.")
        if not cell_tag:
            raise tornado.web.HTTPError(400, reason="cell_tag is required.")
        if save_mode not in SAVE_MODES:
            raise tornado.web.HTTPError(
                400,
                reason=f"save_mode must be one of: {', '.join(sorted(SAVE_MODES))}",
            )

        resolved_dataset_path = _resolve_path(dataset_file, DATASET_ROOT)
        _require_within_root(resolved_dataset_path, DATASET_ROOT.resolve(), "dataset_file")
        if not _is_supported_file(resolved_dataset_path):
            raise tornado.web.HTTPError(
                400,
                reason=(
                    "dataset_file must reference an existing supported file under "
                    f"{DATASET_ROOT}"
                ),
            )

        notebook_root = _notebook_root(self)
        resolved_notebook_path = _resolve_path(notebook_path_value, notebook_root)
        _require_within_root(resolved_notebook_path, notebook_root, "notebook_path")
        if (
            not resolved_notebook_path.exists()
            or resolved_notebook_path.suffix.lower() != ".ipynb"
        ):
            raise tornado.web.HTTPError(
                400,
                reason="notebook_path must reference an existing .ipynb file.",
            )

        output_path = (
            _subset_output_path(resolved_dataset_path, subset_name)
            if save_mode == SAVE_MODE_SUBSET
            else resolved_dataset_path
        )

        original_df = _read_dataframe(resolved_dataset_path)
        notebook = _read_notebook(resolved_notebook_path)
        cell_index, cell_source = _find_tagged_code_cell(notebook, cell_tag)

        execution_scope: dict[str, Any] = {
            "df": original_df.copy(),
            "pd": pd,
            "dataset_path": str(resolved_dataset_path),
            "save_mode": save_mode,
            "subset_output_path": str(output_path),
        }

        try:
            exec(cell_source, {}, execution_scope)
        except Exception as exc:
            raise tornado.web.HTTPError(
                400,
                reason=(
                    f"Execution failed for tagged cell '{cell_tag}' in "
                    f"{resolved_notebook_path}: {exc}"
                ),
            ) from exc

        result_df = execution_scope.get("result", execution_scope["df"])
        if not isinstance(result_df, pd.DataFrame):
            raise tornado.web.HTTPError(
                400,
                reason="Tagged cell must produce a pandas DataFrame in variable `result`.",
            )

        _write_dataframe(output_path, result_df)
        self.finish(
            json.dumps(
                {
                    "status": "ok",
                    "dataset_file": resolved_dataset_path.relative_to(DATASET_ROOT)
                    .as_posix(),
                    "output_file": output_path.relative_to(DATASET_ROOT).as_posix(),
                    "save_mode": save_mode,
                    "cell_tag": cell_tag,
                    "cell_index": cell_index,
                    "rows": int(result_df.shape[0]),
                    "columns": int(result_df.shape[1]),
                }
            )
        )


def setup_handlers(web_app: Any) -> None:
    host_pattern = ".*$"
    base_url = web_app.settings["base_url"]
    handlers = [
        (
            url_path_join(base_url, "jupyter-dataset", "get-example"),
            RouteHandler,
        ),
        (
            url_path_join(base_url, "jupyter-dataset", "datasets"),
            DatasetListHandler,
        ),
        (
            url_path_join(base_url, "jupyter-dataset", "notebooks"),
            NotebookListHandler,
        ),
        (
            url_path_join(base_url, "jupyter-dataset", "apply"),
            ApplyDatasetHandler,
        ),
    ]
    web_app.add_handlers(host_pattern, handlers)
