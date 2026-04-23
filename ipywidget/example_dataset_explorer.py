"""Notebook widget for browsing tabular datasets mounted in /opt/datasets."""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

try:
    _ipython_display = importlib.import_module("IPython.display")
    HTML = _ipython_display.HTML
    display = _ipython_display.display
except ModuleNotFoundError:  # pragma: no cover - depends on notebook env
    class HTML(str):
        """Fallback HTML wrapper when IPython is unavailable."""

    def display(*objects) -> None:
        for obj in objects:
            print(obj)

try:
    pd = importlib.import_module("pandas")
    EmptyDataError = importlib.import_module("pandas.errors").EmptyDataError
except ModuleNotFoundError:  # pragma: no cover - depends on notebook env
    pd = None
    EmptyDataError = ValueError

try:
    widgets = importlib.import_module("ipywidgets")
except ModuleNotFoundError:  # pragma: no cover - depends on notebook env
    widgets = None


DEFAULT_DATASET_ROOT = Path("/opt/datasets")
SUPPORTED_EXTENSIONS = (".csv", ".tsv", ".parquet", ".json", ".jsonl")


@dataclass
class DatasetInfo:
    """Simple metadata about a dataset directory."""

    name: str
    path: Path


def _human_size(size_bytes: int) -> str:
    """Convert byte counts to a readable string."""
    units = ("B", "KB", "MB", "GB", "TB")
    size = float(size_bytes)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} {unit}"
        size /= 1024
    return f"{size_bytes} B"


def _list_dataset_dirs(dataset_root: Path) -> list[DatasetInfo]:
    """Return direct child directories from a dataset root."""
    if not dataset_root.exists() or not dataset_root.is_dir():
        return []

    dataset_dirs = []
    for path in sorted(dataset_root.iterdir()):
        if path.is_dir():
            dataset_dirs.append(DatasetInfo(name=path.name, path=path))
    return dataset_dirs


def _iter_supported_files(dataset_dir: Path) -> Iterable[Path]:
    """Yield supported tabular files recursively from a dataset directory."""
    for path in sorted(dataset_dir.rglob("*")):
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
            yield path


def _read_dataframe(path: Path, preview_rows: int) -> pd.DataFrame:
    """Read a DataFrame using pandas based on file extension."""
    if pd is None:
        raise ModuleNotFoundError(
            "pandas is required to read dataset files. Install it with `pip install pandas`."
        )

    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path, nrows=preview_rows)
    if suffix == ".tsv":
        return pd.read_csv(path, sep="\t", nrows=preview_rows)
    if suffix == ".parquet":
        return pd.read_parquet(path).head(preview_rows)
    if suffix == ".json":
        return pd.read_json(path).head(preview_rows)
    if suffix == ".jsonl":
        return pd.read_json(path, lines=True).head(preview_rows)
    raise ValueError(f"Unsupported file extension: {suffix}")


class DatasetExplorerWidget:
    """Interactive notebook explorer for mounted datasets."""

    def __init__(self, dataset_root: str | Path = DEFAULT_DATASET_ROOT, preview_rows: int = 20):
        if widgets is None:
            raise ModuleNotFoundError(
                "ipywidgets is not installed. Install it with `pip install ipywidgets` "
                "or via your Jupyter environment package manager."
            )
        if pd is None:
            raise ModuleNotFoundError(
                "pandas is not installed. Install it with `pip install pandas` "
                "or via your Jupyter environment package manager."
            )

        self.dataset_root = Path(dataset_root)
        self.preview_rows = max(1, int(preview_rows))

        self.dataset_dropdown = widgets.Dropdown(description="Dataset", options=[])
        self.file_dropdown = widgets.Dropdown(description="File", options=[])
        self.preview_rows_input = widgets.BoundedIntText(
            value=self.preview_rows,
            min=1,
            max=10000,
            step=1,
            description="Rows",
        )
        self.refresh_button = widgets.Button(description="Refresh", button_style="info")
        self.load_button = widgets.Button(description="Load Preview", button_style="success")
        self.status = widgets.HTML("")
        self.output = widgets.Output(layout={"border": "1px solid #ddd", "padding": "6px"})

        self.dataset_dropdown.observe(self._on_dataset_change, names="value")
        self.preview_rows_input.observe(self._on_preview_rows_change, names="value")
        self.refresh_button.on_click(self._on_refresh_click)
        self.load_button.on_click(self._on_load_click)

        self._refresh_datasets()

    def render(self) -> widgets.VBox:
        """Return the top-level widget container."""
        controls = widgets.HBox([self.dataset_dropdown, self.file_dropdown])
        actions = widgets.HBox([self.preview_rows_input, self.refresh_button, self.load_button])
        return widgets.VBox([controls, actions, self.status, self.output])

    def _set_status(self, message: str, level: str = "info") -> None:
        color_by_level = {
            "info": "#0b5ed7",
            "success": "#146c43",
            "warning": "#997404",
            "error": "#b02a37",
        }
        color = color_by_level.get(level, color_by_level["info"])
        self.status.value = f"<span style='color: {color};'><strong>{message}</strong></span>"

    def _on_preview_rows_change(self, change: dict) -> None:
        self.preview_rows = max(1, int(change["new"]))

    def _on_refresh_click(self, _button: object) -> None:
        self._refresh_datasets()

    def _on_load_click(self, _button: object) -> None:
        self._load_selected_file()

    def _on_dataset_change(self, _change: dict) -> None:
        self._refresh_files()

    def _refresh_datasets(self) -> None:
        dataset_infos = _list_dataset_dirs(self.dataset_root)
        if not dataset_infos:
            self.dataset_dropdown.options = [("<no datasets found>", "")]
            self.dataset_dropdown.value = ""
            self.file_dropdown.options = [("<no files found>", "")]
            self.file_dropdown.value = ""
            if not self.dataset_root.exists():
                self._set_status(
                    f"Dataset root does not exist: {self.dataset_root}",
                    level="warning",
                )
            else:
                self._set_status(
                    f"No dataset folders found in {self.dataset_root}",
                    level="warning",
                )
            with self.output:
                self.output.clear_output()
            return

        self.dataset_dropdown.options = [(info.name, str(info.path)) for info in dataset_infos]
        self.dataset_dropdown.value = str(dataset_infos[0].path)
        self._set_status(
            f"Found {len(dataset_infos)} dataset folder(s) in {self.dataset_root}",
            level="success",
        )
        self._refresh_files()

    def _refresh_files(self) -> None:
        dataset_value = self.dataset_dropdown.value or ""
        dataset_path = Path(dataset_value) if dataset_value else None

        if dataset_path is None or not dataset_path.exists():
            self.file_dropdown.options = [("<no files found>", "")]
            self.file_dropdown.value = ""
            self._set_status("Select a dataset folder to list files.", level="info")
            return

        files = list(_iter_supported_files(dataset_path))
        if not files:
            self.file_dropdown.options = [("<no supported files found>", "")]
            self.file_dropdown.value = ""
            self._set_status(
                f"No supported tabular files in {dataset_path}. "
                f"Supported: {', '.join(SUPPORTED_EXTENSIONS)}",
                level="warning",
            )
            return

        self.file_dropdown.options = [
            (str(file_path.relative_to(dataset_path)), str(file_path)) for file_path in files
        ]
        self.file_dropdown.value = str(files[0])
        self._set_status(f"Found {len(files)} supported file(s).", level="success")

    def _load_selected_file(self) -> None:
        file_value = self.file_dropdown.value or ""
        if not file_value:
            self._set_status("No file selected.", level="warning")
            return

        file_path = Path(file_value)
        if not file_path.exists():
            self._set_status(f"File not found: {file_path}", level="error")
            return

        with self.output:
            self.output.clear_output()
            try:
                dataframe = _read_dataframe(file_path, self.preview_rows)
            except EmptyDataError:
                self._set_status(f"File is empty: {file_path}", level="warning")
                display(HTML(f"<p><strong>{file_path.name}</strong> is empty.</p>"))
                return
            except Exception as exc:  # broad by design for notebook UX
                self._set_status(f"Failed to read file: {exc}", level="error")
                display(HTML(f"<pre>{type(exc).__name__}: {exc}</pre>"))
                return

            file_size = _human_size(file_path.stat().st_size)
            metadata_html = (
                "<div>"
                f"<p><strong>Path:</strong> {file_path}</p>"
                f"<p><strong>Size:</strong> {file_size}</p>"
                f"<p><strong>Preview rows shown:</strong> {len(dataframe)}</p>"
                f"<p><strong>Columns:</strong> {len(dataframe.columns)}</p>"
                "</div>"
            )
            display(HTML(metadata_html))
            if not dataframe.empty:
                dtype_frame = dataframe.dtypes.rename("dtype").to_frame()
                display(HTML("<p><strong>Column types:</strong></p>"))
                display(dtype_frame)
            display(HTML("<p><strong>Data preview:</strong></p>"))
            display(dataframe)

            self._set_status(f"Loaded {file_path.name} successfully.", level="success")


def display_dataset_explorer(
    dataset_root: str | Path = DEFAULT_DATASET_ROOT, preview_rows: int = 20
) -> DatasetExplorerWidget:
    """Create and display the dataset explorer in a notebook cell."""
    explorer = DatasetExplorerWidget(dataset_root=dataset_root, preview_rows=preview_rows)
    display(explorer.render())
    return explorer

