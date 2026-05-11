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

  private datasets: IDatasetEntry[] = [];
  private notebooks: string[] = [];
  private activeFilePath = '';
  private activeNotebookPath = '';

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

    const actionRow = document.createElement('div');
    actionRow.className = 'jp-DatasetsActions';
    this.refreshButton.className = 'jp-Button jp-mod-styled';
    this.refreshButton.textContent = 'Refresh';
    this.applyButton.className = 'jp-Button jp-mod-warn';
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
    this.datasets.forEach((dataset, index) => {
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
      let selectedFilePath = '';

      if (hasFiles) {
        if (!this.activeFilePath && index === 0) {
          this.activeFilePath = dataset.files[0].path;
        }
        selectedFilePath =
          dataset.files.find(file => file.path === this.activeFilePath)?.path ??
          dataset.files[0].path;

        dataset.files.forEach(file => {
          const fileButton = document.createElement('button');
          fileButton.className = 'jp-Button jp-mod-styled jp-DatasetsFileButton';
          if (file.path === selectedFilePath) {
            fileButton.classList.add('jp-DatasetsFileButton-active');
          }
          fileButton.textContent = file.path;
          fileButton.onclick = () => {
            this.activeFilePath = file.path;
            this.renderDatasetTiles();
          };
          filesContainer.appendChild(fileButton);
        });
      } else {
        const noFiles = document.createElement('div');
        noFiles.className = 'jp-DatasetsTileMeta';
        noFiles.textContent = 'No files available';
        filesContainer.appendChild(noFiles);
      }

      const editButton = document.createElement('button');
      editButton.className = 'jp-Button jp-mod-warn';
      editButton.textContent = 'Edit / Transform';
      editButton.disabled = !hasFiles;
      editButton.onclick = () => {
        this.activeFilePath = selectedFilePath;
        void this.apply();
      };

      tile.appendChild(title);
      tile.appendChild(meta);
      tile.appendChild(filesContainer);
      tile.appendChild(editButton);
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
      this.notebooks = notebookResponse.notebooks;
      if (!this.notebooks.includes(this.activeNotebookPath)) {
        this.activeNotebookPath = this.notebooks[0] ?? '';
      }
      this.renderDatasetTiles();
      this.setStatus(
        `Loaded ${this.datasets.length} dataset(s) and ${notebookResponse.notebooks.length} notebook(s).`,
        'success'
      );
    } catch (error) {
      const message =
        error instanceof Error ? error.message : 'Unknown error while refreshing.';
      this.setStatus(message, 'error');
    } finally {
      this.applyButton.disabled = false;
      this.refreshButton.disabled = false;
    }
  }

  private async apply(): Promise<void> {
    const datasetFile = this.activeFilePath;
    const notebookPath = this.activeNotebookPath;
    const cellTag = 'dataset-transform';
    const saveMode = 'subset';

    if (!datasetFile) {
      this.setStatus('Select a dataset file before applying.', 'error');
      return;
    }
    if (!notebookPath) {
      this.setStatus('Select a notebook before applying.', 'error');
      return;
    }

    this.applyButton.disabled = true;
    this.setStatus('Applying tagged notebook cell...', 'info');
    try {
      const response = await requestAPI<IApplyResponse>('apply', {
        method: 'POST',
        body: JSON.stringify({
          dataset_file: datasetFile,
          notebook_path: notebookPath,
          cell_tag: cellTag,
          save_mode: saveMode,
          subset_name: undefined
        }),
        headers: {
          'Content-Type': 'application/json'
        }
      });
      this.setStatus(
        `Applied tag "${response.cell_tag}" to ${response.dataset_file}. Output: ${response.output_file}`,
        'success'
      );
      await this.refresh();
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Apply failed.';
      this.setStatus(message, 'error');
    } finally {
      this.applyButton.disabled = false;
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
