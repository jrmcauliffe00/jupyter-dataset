import {
  JupyterFrontEnd,
  JupyterFrontEndPlugin
} from '@jupyterlab/application';

import { requestAPI } from './handler';

/**
 * Initialization data for the jupyter-dataset extension.
 */
const plugin: JupyterFrontEndPlugin<void> = {
  id: 'jupyter-dataset:plugin',
  description: 'A JupyterLab extension.',
  autoStart: true,
  activate: (app: JupyterFrontEnd) => {
    console.log('JupyterLab extension jupyter-dataset is activated!');

    requestAPI<any>('get-example')
      .then(data => {
        console.log(data);
      })
      .catch(reason => {
        console.error(
          `The jupyter-dataset server extension appears to be missing.\n${reason}`
        );
      });
  }
};

export default plugin;
