import {
  JupyterFrontEnd,
  JupyterFrontEndPlugin
} from '@jupyterlab/application';
import { Widget } from '@lumino/widgets';

import { requestAPI } from './handler';

interface IFileEntry {
  name: string;
  path: string;
  size_bytes: number;
}

interface IDatasetEntry {
  name: string;
  path: string;
  files: IFileEntry[];
}

interface IDatasetListResponse {
  dataset_root: string;
  supported_extensions: string[];
  datasets: IDatasetEntry[];
}

interface INotebookListResponse {
  notebook_root: string;
  notebooks: string[];
  notebook_entries?: INotebookEntry[];
}

interface ITransformCellEntry {
  index: number;
  name: string;
  cell_tag: string;
  tags: string[];
  preview: string;
}

interface INotebookEntry {
  path: string;
  transform_cells: ITransformCellEntry[];
}

interface ITransformationOption {
  key: string;
  name: string;
  cellTag: string;
  notebookPath: string;
  cellIndex: number;
  preview: string;
}

interface IApplyResponse {
  status: string;
  dataset_file: string;
  output_file: string;
  save_mode: string;
  cell_tag: string;
  cell_index: number;
  rows: number;
  columns: number;
}

class DatasetSidebar extends Widget {
  private readonly statusNode = document.createElement('div');
  private readonly applyButton = document.createElement('button');
  private readonly refreshButton = document.createElement('button');
  private readonly tilesContainer = document.createElement('div');
  private readonly transformSelect = document.createElement('select');
  private readonly transformControl = document.createElement('div');
  private readonly outputNameInput = document.createElement('input');
  private readonly outputNameControl = document.createElement('div');

  private datasets: IDatasetEntry[] = [];
  private notebookEntries: INotebookEntry[] = [];
  private transformations: ITransformationOption[] = [];
  private activeFilePath = '';
  private activeTransformationKey = '';

  constructor() {
    super();
    this.id = 'jupyter-dataset-sidebar';
    this.title.label = 'Datasets';
    this.title.caption = 'Dataset operations';
    this.title.closable = true;
    this.addClass('jp-DatasetsSidebar');

    this.tilesContainer.className = 'jp-DatasetsTiles';
    this.node.appendChild(this.tilesContainer);
    this.renderDatasetTiles();

    this.transformControl.className = 'jp-DatasetsControl';
    const transformLabel = document.createElement('label');
    transformLabel.className = 'jp-DatasetsLabel';
    transformLabel.textContent = 'Transformation';
    this.transformSelect.className = 'jp-DatasetsSelect';
    this.transformSelect.onchange = () => {
      this.activeTransformationKey = this.transformSelect.value;
      this.renderDatasetTiles();
      this.updateActionState();
    };
    this.transformControl.appendChild(transformLabel);
    this.transformControl.appendChild(this.transformSelect);
    this.node.appendChild(this.transformControl);

    this.outputNameControl.className = 'jp-DatasetsControl';
    const outputNameLabel = document.createElement('label');
    outputNameLabel.className = 'jp-DatasetsLabel';
    outputNameLabel.textContent = 'New dataset name (optional)';
    this.outputNameInput.className = 'jp-DatasetsInput';
    this.outputNameInput.type = 'text';
    this.outputNameInput.placeholder = 'Defaults to <source-name>__<timestamp>';
    this.outputNameControl.appendChild(outputNameLabel);
    this.outputNameControl.appendChild(this.outputNameInput);
    this.node.appendChild(this.outputNameControl);

    const actionRow = document.createElement('div');
    actionRow.className = 'jp-DatasetsActions';
    this.refreshButton.className = 'jp-Button jp-mod-styled';
    this.refreshButton.textContent = 'Refresh';
    this.applyButton.className = 'jp-Button jp-mod-styled jp-DatasetsApplyButton';
    this.applyButton.textContent = 'Apply';
    actionRow.appendChild(this.refreshButton);
    actionRow.appendChild(this.applyButton);
    this.node.appendChild(actionRow);

    this.statusNode.className = 'jp-DatasetsStatus';
    this.statusNode.textContent = 'Loading datasets and notebooks...';
    this.node.appendChild(this.statusNode);

    this.refreshButton.onclick = () => {
      void this.refresh();
    };
    this.applyButton.onclick = () => {
      void this.apply();
    };
  }

  private isReadyToApply(datasetPath = this.activeFilePath): boolean {
    return Boolean(datasetPath && this.getActiveTransformation());
  }

  private getActiveTransformation(): ITransformationOption | undefined {
    return this.transformations.find(
      transformation => transformation.key === this.activeTransformationKey
    );
  }

  private ensureActiveTransformationSelection(): void {
    const hasActiveTransformation = this.transformations.some(
      transformation => transformation.key === this.activeTransformationKey
    );
    if (!hasActiveTransformation) {
      this.activeTransformationKey = this.transformations[0]?.key ?? '';
    }
  }

  private renderTransformControl(): void {
    this.transformSelect.replaceChildren();
    this.transformations.forEach(transformation => {
      const option = document.createElement('option');
      option.value = transformation.key;
      const preview = transformation.preview ? ` - ${transformation.preview}` : '';
      option.textContent = `${transformation.name}${preview}`;
      option.selected = transformation.key === this.activeTransformationKey;
      this.transformSelect.appendChild(option);
    });

    this.transformSelect.disabled = this.transformations.length === 0;
  }

  private updateActionState(): void {
    const isReady = this.isReadyToApply();
    this.applyButton.disabled = !isReady;
    this.applyButton.classList.toggle('jp-DatasetsApplyButton-ready', isReady);
    this.applyButton.classList.toggle('jp-DatasetsApplyButton-disabled', !isReady);
  }

  private renderDatasetTiles(): void {
    this.tilesContainer.replaceChildren();

    const hasActiveFile = this.datasets.some(dataset =>
      dataset.files.some(file => file.path === this.activeFilePath)
    );
    if (!hasActiveFile) {
      this.activeFilePath = '';
    }

    if (this.datasets.length === 0) {
      const msg = document.createElement('div');
      msg.className = 'jp-DatasetsTileEmpty';
      msg.textContent = 'No datasets found';
      this.tilesContainer.appendChild(msg);
      return;
    }
    this.datasets.forEach(dataset => {
      const tile = document.createElement('section');
      tile.className = 'jp-DatasetsTile';
      const title = document.createElement('div');
      title.className = 'jp-DatasetsTileTitle';
      title.textContent = dataset.name;
      const meta = document.createElement('div');
      meta.className = 'jp-DatasetsTileMeta';
      meta.textContent = `${dataset.files.length} file(s)`;
      const filesContainer = document.createElement('div');
      filesContainer.className = 'jp-DatasetsFileButtons';
      const hasFiles = dataset.files.length > 0;
      const isActiveDataset =
        hasFiles && dataset.files.some(file => file.path === this.activeFilePath);
      let selectedFilePath = '';

      if (isActiveDataset) {
        tile.classList.add('jp-DatasetsTile-active');
      }

      if (hasFiles) {
        selectedFilePath =
          dataset.files.find(file => file.path === this.activeFilePath)?.path ?? '';
        tile.onclick = () => {
          if (!isActiveDataset) {
            this.activeFilePath = dataset.files[0].path;
            this.renderDatasetTiles();
            this.updateActionState();
          }
        };

        dataset.files.forEach(file => {
          const fileButton = document.createElement('button');
          fileButton.className = 'jp-Button jp-mod-styled jp-DatasetsFileButton';
          if (file.path === selectedFilePath && isActiveDataset) {
            fileButton.classList.add('jp-DatasetsFileButton-active');
          }
          fileButton.textContent = file.path;
          fileButton.onclick = event => {
            event.stopPropagation();
            this.activeFilePath = file.path;
            this.renderDatasetTiles();
            this.updateActionState();
          };
          filesContainer.appendChild(fileButton);
        });
      } else {
        const noFiles = document.createElement('div');
        noFiles.className = 'jp-DatasetsTileMeta';
        noFiles.textContent = 'No files available';
        filesContainer.appendChild(noFiles);
      }

      tile.appendChild(title);
      tile.appendChild(meta);
      tile.appendChild(filesContainer);
      this.tilesContainer.appendChild(tile);
    });
  }

  async refresh(): Promise<void> {
    this.setStatus('Loading datasets and notebooks...', 'info');
    this.applyButton.disabled = true;
    this.refreshButton.disabled = true;
    try {
      const [datasetResponse, notebookResponse] = await Promise.all([
        requestAPI<IDatasetListResponse>('datasets'),
        requestAPI<INotebookListResponse>('notebooks')
      ]);
      this.datasets = datasetResponse.datasets;
      this.notebookEntries =
        notebookResponse.notebook_entries ??
        notebookResponse.notebooks.map(path => ({ path, transform_cells: [] }));
      this.transformations = this.notebookEntries.flatMap(notebook =>
        notebook.transform_cells.map(cell => ({
          key: `${notebook.path}:${cell.index}`,
          name: cell.name,
          cellTag: cell.cell_tag,
          notebookPath: notebook.path,
          cellIndex: cell.index,
          preview: cell.preview
        }))
      );
      this.ensureActiveTransformationSelection();
      this.renderTransformControl();
      this.renderDatasetTiles();
      this.updateActionState();
      this.setStatus(
        `Loaded ${this.datasets.length} dataset(s) and ${this.transformations.length} transformation(s).`,
        'success'
      );
    } catch (error) {
      const message =
        error instanceof Error ? error.message : 'Unknown error while refreshing.';
      this.setStatus(message, 'error');
    } finally {
      this.refreshButton.disabled = false;
      this.updateActionState();
    }
  }

  private async apply(): Promise<void> {
    const datasetFile = this.activeFilePath;
    const selectedTransformation = this.getActiveTransformation();
    const saveMode = 'subset';
    const newDatasetName = this.outputNameInput.value.trim() || undefined;

    if (!datasetFile) {
      this.setStatus('Select a dataset file before applying.', 'error');
      return;
    }
    if (!selectedTransformation) {
      this.setStatus('Select a transformation before applying.', 'error');
      return;
    }

    this.applyButton.disabled = true;
    this.applyButton.classList.add('jp-DatasetsApplyButton-disabled');
    this.applyButton.classList.remove('jp-DatasetsApplyButton-ready');
    this.setStatus('Applying tagged notebook cell...', 'info');
    try {
      const response = await requestAPI<IApplyResponse>('apply', {
        method: 'POST',
        body: JSON.stringify({
          dataset_file: datasetFile,
          notebook_path: selectedTransformation.notebookPath,
          cell_tag: selectedTransformation.cellTag,
          cell_index: selectedTransformation.cellIndex,
          save_mode: saveMode,
          new_dataset_name: newDatasetName
        }),
        headers: {
          'Content-Type': 'application/json'
        }
      });
      this.setStatus(
        `Applied "${selectedTransformation.name}" to ${response.dataset_file}. Output: ${response.output_file}`,
        'success'
      );
      await this.refresh();
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Apply failed.';
      this.setStatus(message, 'error');
    } finally {
      this.updateActionState();
    }
  }

  private setStatus(message: string, kind: 'info' | 'success' | 'error'): void {
    this.statusNode.textContent = message;
    this.statusNode.dataset.kind = kind;
  }
}

/**
 * Initialization data for the jupyter-dataset extension.
 */
const plugin: JupyterFrontEndPlugin<void> = {
  id: 'jupyter-dataset:plugin',
  description: 'A JupyterLab extension.',
  autoStart: true,
  activate: (app: JupyterFrontEnd) => {
    const sidebar = new DatasetSidebar();
    app.shell.add(sidebar, 'left', { rank: 850 });
    void sidebar.refresh();
  }
};

export default plugin;
