import { App } from "antd";
import { useCallback, useEffect, useState } from "react";
import {
  activateDataset,
  createDataset,
  deleteDataset,
  exportAllDatasets,
  exportDataset,
  importDataset,
  listDatasets,
  renameDataset,
} from "../../api/settings";
import type { DatasetInfo } from "../../types";
import { downloadBlob } from "../../utils/download";
import { reloadPage } from "../../utils/navigation";

/** 设置页「数据」页里数据集的加载、导出、导入、切换、重命名、删除与新建。 */
export function useSettingsDatasets() {
  const { message } = App.useApp();
  const [datasets, setDatasets] = useState<DatasetInfo[]>([]);
  const [datasetsLoading, setDatasetsLoading] = useState(true);
  const [datasetExporting, setDatasetExporting] = useState(false);
  const [datasetImporting, setDatasetImporting] = useState(false);
  const [switchingDatasetId, setSwitchingDatasetId] = useState<string | null>(null);
  const [renamingDatasetId, setRenamingDatasetId] = useState<string | null>(null);
  const [deletingDatasetId, setDeletingDatasetId] = useState<string | null>(null);
  const [renameTarget, setRenameTarget] = useState<DatasetInfo | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [datasetCreating, setDatasetCreating] = useState(false);
  const [createDatasetOpen, setCreateDatasetOpen] = useState(false);
  const [createDatasetName, setCreateDatasetName] = useState("");

  const loadDatasetList = useCallback(async () => {
    setDatasetsLoading(true);
    try {
      setDatasets(await listDatasets());
    } catch (err) {
      message.error(err instanceof Error ? err.message : "加载数据集失败");
    } finally {
      setDatasetsLoading(false);
    }
  }, [message]);

  useEffect(() => {
    void loadDatasetList();
  }, [loadDatasetList]);

  const runDatasetExport = async (dataset: DatasetInfo) => {
    if (datasetExporting) return;
    setDatasetExporting(true);
    try {
      const { blob, filename } = await exportDataset(dataset.id);
      downloadBlob(blob, filename);
      message.success(`已导出「${dataset.name}」到浏览器的下载目录`);
    } catch (err) {
      message.error(err instanceof Error ? err.message : "导出数据集失败");
    } finally {
      setDatasetExporting(false);
    }
  };

  const runExportAllDatasets = async () => {
    if (datasetExporting) return;
    setDatasetExporting(true);
    try {
      const { blob, filename } = await exportAllDatasets();
      downloadBlob(blob, filename);
      message.success(`已把全部 ${datasets.length} 份数据集导出到浏览器的下载目录`);
    } catch (err) {
      message.error(err instanceof Error ? err.message : "导出全部数据集失败");
    } finally {
      setDatasetExporting(false);
    }
  };

  const importDatasetFile = async (file: File, name: string) => {
    if (datasetImporting) return;
    setDatasetImporting(true);
    try {
      const created = await importDataset(file, name);
      await loadDatasetList();
      // "导出全部数据集"产生的包里会随行带上其余几份，导入时它们也各成一份新数据集。
      // 只报主数据集的名字会让用户以为另外几份没被恢复。
      const extras = created.restored_datasets?.length ?? 0;
      message.success(
        extras > 0
          ? `已导入数据集「${created.name}」，并随包恢复了另外 ${extras} 份数据集；当前数据未受影响`
          : `已导入数据集「${created.name}」，当前数据未受影响`,
      );
    } catch (err) {
      message.error(err instanceof Error ? err.message : "导入备份失败");
    } finally {
      setDatasetImporting(false);
    }
  };

  const switchDataset = async (dataset: DatasetInfo) => {
    if (switchingDatasetId !== null) return;
    setSwitchingDatasetId(dataset.id);
    try {
      await activateDataset(dataset.id);
      message.success(`已切换到「${dataset.name}」，正在重新加载页面`);
      // 整页重载：切换后所有本地状态都要按新数据集重建。失败时保留 loading 以便重试。
      window.setTimeout(reloadPage, 800);
    } catch (err) {
      message.error(err instanceof Error ? err.message : "切换数据集失败");
      setSwitchingDatasetId(null);
    }
  };

  const confirmDatasetRename = async () => {
    if (!renameTarget || renamingDatasetId !== null) return;
    setRenamingDatasetId(renameTarget.id);
    try {
      await renameDataset(renameTarget.id, renameValue);
      setRenameTarget(null);
      await loadDatasetList();
      message.success("已重命名");
    } catch (err) {
      message.error(err instanceof Error ? err.message : "重命名失败");
    } finally {
      setRenamingDatasetId(null);
    }
  };

  const removeDataset = async (dataset: DatasetInfo) => {
    if (deletingDatasetId !== null) return;
    setDeletingDatasetId(dataset.id);
    try {
      await deleteDataset(dataset.id);
      await loadDatasetList();
      message.success(`已删除「${dataset.name}」，可在 data/datasets/.trash/ 找回`);
    } catch (err) {
      message.error(err instanceof Error ? err.message : "删除数据集失败");
    } finally {
      setDeletingDatasetId(null);
    }
  };

  const createEmptyDataset = async () => {
    const name = createDatasetName.trim();
    if (!name) {
      message.warning("请填写数据集名称");
      return;
    }
    if (datasetCreating) return;
    setDatasetCreating(true);
    try {
      const created = await createDataset(name);
      await loadDatasetList();
      setCreateDatasetOpen(false);
      setCreateDatasetName("");
      message.success(`已新建数据集「${created.name}」，可在列表里切换到它`);
    } catch (err) {
      message.error(err instanceof Error ? err.message : "新建数据集失败");
    } finally {
      setDatasetCreating(false);
    }
  };

  return {
    datasets,
    datasetsLoading,
    datasetExporting,
    datasetImporting,
    switchingDatasetId,
    renamingDatasetId,
    deletingDatasetId,
    renameTarget,
    renameValue,
    datasetCreating,
    createDatasetOpen,
    createDatasetName,
    loadDatasetList,
    runDatasetExport,
    runExportAllDatasets,
    importDatasetFile,
    switchDataset,
    confirmDatasetRename,
    removeDataset,
    createEmptyDataset,
    setRenameTarget,
    setRenameValue,
    setCreateDatasetOpen,
    setCreateDatasetName,
  };
}
