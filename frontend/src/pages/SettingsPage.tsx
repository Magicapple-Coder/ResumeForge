/** 设置页：大模型配置（含预设与连通测试）。 */
import { CloseOutlined, EditOutlined, SaveOutlined } from "@ant-design/icons";
import { App, Button, Form, Typography } from "antd";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  activateDataset,
  deleteDataset,
  deleteLLMConfigRecord,
  exportDataset,
  getLLMConfig,
  importDataset,
  listDatasets,
  listLLMConfigRecords,
  listLLMModels,
  renameDataset,
  revealLLMApiKey,
  saveLLMConfig,
  saveLLMConfigRecord,
  testLLM,
} from "../api/settings";
import { deleteSkill, importSkill, listSkills, setSkillEnabled } from "../api/skill";
import { LLM_PRESETS } from "../config";
import DatasetsCard from "../components/settings/DatasetsCard";
import LLMConfigCard from "../components/settings/LLMConfigCard";
import LLMConfigRecordsCard from "../components/settings/LLMConfigRecordsCard";
import SkillsCard from "../components/settings/SkillsCard";
import UpdateCard from "../components/settings/UpdateCard";
import {
  API_KEY_MASK,
  CUSTOM_PRESET,
  MANUAL_PRESET,
  configFromFormValues,
  configFromRecord,
  formValuesFromConfig,
  isMaskedApiKey,
  sameConfig,
  type SettingsFormValues,
} from "../components/settings/SettingsConfig";
import SkillEditorModal from "../components/skills/SkillEditorModal";
import type {
  AssistantSkill,
  DatasetInfo,
  LLMConfig,
  LLMConfigRecord,
  LLMModelsResult,
  LLMTestResult,
} from "../types";
import { downloadBlob } from "../utils/download";
import { reloadPage } from "../utils/navigation";

export default function SettingsPage() {
  const [form] = Form.useForm<SettingsFormValues>();
  const { message } = App.useApp();
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [editing, setEditing] = useState(false);
  const [testResult, setTestResult] = useState<LLMTestResult | null>(null);
  const savedValues = useRef<SettingsFormValues | null>(null);
  const [records, setRecords] = useState<LLMConfigRecord[]>([]);
  const [recordsLoading, setRecordsLoading] = useState(true);
  const [activeRecordId, setActiveRecordId] = useState<number | null>(null);
  const [recordModalOpen, setRecordModalOpen] = useState(false);
  const [recordName, setRecordName] = useState("");
  const [recordSaving, setRecordSaving] = useState(false);
  const [recordApplyingId, setRecordApplyingId] = useState<number | null>(null);
  const [recordDeletingId, setRecordDeletingId] = useState<number | null>(null);
  const [apiKeyResetToken, setApiKeyResetToken] = useState(0);

  const resetRevealedApiKey = useCallback(() => setApiKeyResetToken((current) => current + 1), []);

  const [skills, setSkills] = useState<AssistantSkill[]>([]);
  const [skillsLoading, setSkillsLoading] = useState(true);
  const [skillImporting, setSkillImporting] = useState(false);
  const [skillTogglingId, setSkillTogglingId] = useState<number | null>(null);
  const [skillDeletingId, setSkillDeletingId] = useState<number | null>(null);
  const [skillEditorOpen, setSkillEditorOpen] = useState(false);
  const [skillEditorId, setSkillEditorId] = useState<number | null>(null);

  const loadSkillList = useCallback(async () => {
    setSkillsLoading(true);
    try {
      setSkills(await listSkills());
    } catch (err) {
      message.error(err instanceof Error ? err.message : "加载技能失败");
    } finally {
      setSkillsLoading(false);
    }
  }, [message]);

  useEffect(() => {
    void loadSkillList();
  }, [loadSkillList]);

  const importSkillFile = async (file: File) => {
    if (skillImporting) return;
    setSkillImporting(true);
    try {
      const saved = await importSkill(file);
      await loadSkillList();
      message.success(`已导入技能「${saved.name}」`);
    } catch (err) {
      message.error(err instanceof Error ? err.message : "导入技能失败");
    } finally {
      setSkillImporting(false);
    }
  };

  const toggleSkill = async (skill: AssistantSkill, enabled: boolean) => {
    if (skillTogglingId !== null) return;
    setSkillTogglingId(skill.id);
    try {
      const updated = await setSkillEnabled(skill.id, enabled);
      setSkills((current) => current.map((item) => (item.id === updated.id ? updated : item)));
      message.success(`已${enabled ? "启用" : "停用"}「${skill.name}」`);
    } catch (err) {
      message.error(err instanceof Error ? err.message : "切换技能状态失败");
    } finally {
      setSkillTogglingId(null);
    }
  };

  const removeSkill = async (skill: AssistantSkill) => {
    if (skillDeletingId !== null) return;
    setSkillDeletingId(skill.id);
    try {
      await deleteSkill(skill.id);
      setSkills((current) => current.filter((item) => item.id !== skill.id));
      message.success(`已删除技能「${skill.name}」`);
    } catch (err) {
      message.error(err instanceof Error ? err.message : "删除技能失败");
    } finally {
      setSkillDeletingId(null);
    }
  };

  const [datasets, setDatasets] = useState<DatasetInfo[]>([]);
  const [datasetsLoading, setDatasetsLoading] = useState(true);
  const [datasetExporting, setDatasetExporting] = useState(false);
  const [datasetImporting, setDatasetImporting] = useState(false);
  const [switchingDatasetId, setSwitchingDatasetId] = useState<string | null>(null);
  const [renamingDatasetId, setRenamingDatasetId] = useState<string | null>(null);
  const [deletingDatasetId, setDeletingDatasetId] = useState<string | null>(null);
  const [renameTarget, setRenameTarget] = useState<DatasetInfo | null>(null);
  const [renameValue, setRenameValue] = useState("");

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

  const importDatasetFile = async (file: File, name: string) => {
    if (datasetImporting) return;
    setDatasetImporting(true);
    try {
      const created = await importDataset(file, name);
      await loadDatasetList();
      message.success(`已导入数据集「${created.name}」，当前数据未受影响`);
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

  // 同时加载当前配置与记录，避免页面先显示一套配置、稍后又跳变到另一套状态。
  useEffect(() => {
    setRecordsLoading(true);
    void Promise.all([getLLMConfig(), listLLMConfigRecords()])
      .then(([config, loadedRecords]) => {
        const values = formValuesFromConfig(config);
        form.setFieldsValue(values);
        savedValues.current = values;
        setRecords(loadedRecords);
        setActiveRecordId(loadedRecords.find((record) => sameConfig(record, config))?.id ?? null);
      })
      .catch((err) => message.error(err instanceof Error ? err.message : "加载配置失败"))
      .finally(() => setRecordsLoading(false));
  }, [form, message]);

  const applyPreset = (provider: string) => {
    if (!editing) return;
    // 自定义模式保留当前内容，避免用户误点后丢失已经填写的接口信息。
    if (provider === CUSTOM_PRESET) {
      resetRevealedApiKey();
      form.setFieldValue("provider", CUSTOM_PRESET);
      return;
    }
    // 纯手动配置则是要一套空表单：清掉预设会填的那两项，自己从头填。
    // 不动 API Key——预设本来就不碰它，顺手清掉等于替用户删密钥。
    if (provider === MANUAL_PRESET) {
      resetRevealedApiKey();
      form.setFieldsValue({ provider: MANUAL_PRESET, base_url: "", model: "" });
      return;
    }
    const preset = LLM_PRESETS.find((item) => item.provider === provider);
    if (!preset) return;
    resetRevealedApiKey();
    form.setFieldsValue({
      provider: preset.provider,
      base_url: preset.base_url,
      model: preset.model,
    });
  };

  const revealSavedApiKey = async () => (await revealLLMApiKey()).api_key;

  /** 收集表单值并剔除前端专用的 preset 字段 */
  const collectValues = async (): Promise<LLMConfig | null> => {
    try {
      const values = await form.validateFields();
      return configFromFormValues(values);
    } catch {
      return null;
    }
  };

  const save = async () => {
    if (!editing || saving || testing) return;
    const values = await collectValues();
    if (!values) return;
    setSaving(true);
    try {
      const saved = await saveLLMConfig(values);
      const nextValues = formValuesFromConfig(saved);
      form.setFieldsValue(nextValues);
      savedValues.current = nextValues;
      setActiveRecordId(records.find((record) => sameConfig(record, saved))?.id ?? null);
      resetRevealedApiKey();
      setEditing(false);
      setTestResult(null);
      message.success("配置已保存，可在下方保存为记录");
    } catch (err) {
      message.error(err instanceof Error ? err.message : "保存失败");
    } finally {
      setSaving(false);
    }
  };

  /** 按表单里当前填的 Base URL / API Key 拉取可用模型（失败原因由后端给出）。 */
  const fetchModels = async (): Promise<LLMModelsResult> => {
    const values = form.getFieldsValue(true) as SettingsFormValues;
    try {
      return await listLLMModels({
        base_url: values.base_url ?? "",
        api_key: values.api_key ?? "",
      });
    } catch (err) {
      return {
        models: [],
        message: err instanceof Error ? err.message : "获取模型列表失败",
      };
    }
  };

  const test = async () => {
    if (saving || testing) return;
    const values = await collectValues();
    if (!values) return;
    setTesting(true);
    setTestResult(null);
    try {
      setTestResult(await testLLM(values));
    } catch (err) {
      setTestResult({
        ok: false,
        latency_ms: null,
        message: err instanceof Error ? err.message : "测试失败",
      });
    } finally {
      setTesting(false);
    }
  };

  const openRecordModal = () => {
    if (editing || recordSaving || !savedValues.current) return;
    setRecordName("");
    setRecordModalOpen(true);
  };

  const saveRecord = async () => {
    const name = recordName.trim();
    const saved = savedValues.current;
    if (!name) {
      message.warning("请填写配置记录名称");
      return;
    }
    if (!saved) {
      message.warning("当前配置尚未加载完成");
      return;
    }

    setRecordSaving(true);
    try {
      const record = await saveLLMConfigRecord({ name, ...configFromFormValues(saved) });
      setRecords((current) => [record, ...current.filter((item) => item.id !== record.id)]);
      setActiveRecordId(record.id);
      setRecordModalOpen(false);
      message.success("配置记录已保存");
    } catch (err) {
      message.error(err instanceof Error ? err.message : "保存配置记录失败");
    } finally {
      setRecordSaving(false);
    }
  };

  const applyRecord = async (record: LLMConfigRecord) => {
    if (editing || saving || testing || recordApplyingId !== null) return;
    resetRevealedApiKey();
    setRecordApplyingId(record.id);
    try {
      const saved = await saveLLMConfig(configFromRecord(record));
      const nextValues = formValuesFromConfig(saved);
      form.setFieldsValue(nextValues);
      savedValues.current = nextValues;
      setActiveRecordId(record.id);
      setTestResult(null);
      message.success(`已切换到配置「${record.name}」`);
    } catch (err) {
      message.error(err instanceof Error ? err.message : "切换配置失败");
    } finally {
      setRecordApplyingId(null);
    }
  };

  const removeRecord = async (record: LLMConfigRecord) => {
    if (recordDeletingId !== null || recordApplyingId !== null) return;
    const wasActive = activeRecordId === record.id;
    setRecordDeletingId(record.id);
    try {
      await deleteLLMConfigRecord(record.id);
      setRecords((current) => current.filter((item) => item.id !== record.id));
      if (wasActive) {
        // The current app setting is independent from its saved record. Reload it
        // so the form no longer keeps a reference to the deleted record's key.
        try {
          const currentConfig = await getLLMConfig();
          const nextValues = formValuesFromConfig(currentConfig);
          form.setFieldsValue(nextValues);
          savedValues.current = nextValues;
        } catch (refreshError) {
          // A failed refresh must still make the stale record reference unusable.
          const currentValues = form.getFieldsValue(true) as SettingsFormValues;
          const nextValues = {
            ...currentValues,
            api_key: isMaskedApiKey(currentValues.api_key) ? API_KEY_MASK : currentValues.api_key,
          };
          form.setFieldsValue(nextValues);
          savedValues.current = nextValues;
          message.warning(
            refreshError instanceof Error
              ? `配置记录已删除，但当前配置刷新失败：${refreshError.message}`
              : "配置记录已删除，但当前配置刷新失败",
          );
        }
        resetRevealedApiKey();
        setActiveRecordId(null);
      }
      message.success("配置记录已删除");
    } catch (err) {
      message.error(err instanceof Error ? err.message : "删除配置记录失败");
    } finally {
      setRecordDeletingId(null);
    }
  };

  const cancelEditing = () => {
    if (saving || testing) return;
    if (savedValues.current) {
      form.resetFields();
      form.setFieldsValue(savedValues.current);
    }
    setTestResult(null);
    resetRevealedApiKey();
    setEditing(false);
  };

  return (
    <div className={`settings-page${editing ? " is-editing" : ""}`}>
      <div className="settings-page-header">
        <div>
          <Typography.Title level={3} style={{ margin: 0 }}>
            设置
          </Typography.Title>
          <Typography.Text type="secondary">
            配置简历生成、岗位需求解读和求职助手等 AI 功能使用的模型服务
          </Typography.Text>
        </div>
        <div className="profile-page-header-actions">
          {editing ? (
            <>
              <Button icon={<CloseOutlined />} disabled={saving || testing} onClick={cancelEditing}>
                取消
              </Button>
              <Button
                type="primary"
                icon={<SaveOutlined />}
                loading={saving}
                disabled={testing}
                onClick={() => void save()}
              >
                保存配置
              </Button>
            </>
          ) : (
            <Button icon={<EditOutlined />} onClick={() => setEditing(true)}>
              编辑设置
            </Button>
          )}
        </div>
      </div>

      <LLMConfigCard
        form={form}
        editing={editing}
        saving={saving}
        testing={testing}
        testResult={testResult}
        apiKeyResetToken={apiKeyResetToken}
        onPresetChange={applyPreset}
        onResetApiKey={resetRevealedApiKey}
        onRevealApiKey={revealSavedApiKey}
        onRevealError={(error) => message.error(error)}
        onTest={() => void test()}
        onFetchModels={fetchModels}
      />

      <LLMConfigRecordsCard
        records={records}
        recordsLoading={recordsLoading}
        activeRecordId={activeRecordId}
        editing={editing}
        saving={saving}
        testing={testing}
        recordSaving={recordSaving}
        recordApplyingId={recordApplyingId}
        recordDeletingId={recordDeletingId}
        recordModalOpen={recordModalOpen}
        recordName={recordName}
        onOpenRecordModal={openRecordModal}
        onApplyRecord={(record) => void applyRecord(record)}
        onRemoveRecord={(record) => void removeRecord(record)}
        onRecordNameChange={setRecordName}
        onSaveRecord={() => void saveRecord()}
        onCloseRecordModal={() => {
          if (!recordSaving) setRecordModalOpen(false);
        }}
      />

      <SkillsCard
        skills={skills}
        loading={skillsLoading}
        importing={skillImporting}
        togglingId={skillTogglingId}
        deletingId={skillDeletingId}
        onImport={(file) => void importSkillFile(file)}
        onToggle={(skill, enabled) => void toggleSkill(skill, enabled)}
        onDelete={(skill) => void removeSkill(skill)}
        onOpen={(skill) => {
          setSkillEditorId(skill.id);
          setSkillEditorOpen(true);
        }}
      />

      <DatasetsCard
        datasets={datasets}
        loading={datasetsLoading}
        exporting={datasetExporting}
        importing={datasetImporting}
        switchingId={switchingDatasetId}
        renamingId={renamingDatasetId}
        deletingId={deletingDatasetId}
        renameTarget={renameTarget}
        renameValue={renameValue}
        onExport={(dataset) => void runDatasetExport(dataset)}
        onImport={(file, name) => void importDatasetFile(file, name)}
        onActivate={(dataset) => void switchDataset(dataset)}
        onOpenRename={(dataset) => {
          setRenameTarget(dataset);
          setRenameValue(dataset.name);
        }}
        onRenameValueChange={setRenameValue}
        onConfirmRename={() => void confirmDatasetRename()}
        onCancelRename={() => {
          if (renamingDatasetId === null) setRenameTarget(null);
        }}
        onDelete={(dataset) => void removeDataset(dataset)}
      />

      <UpdateCard />

      {/* 设置页里点技能名查看详情，与技能工作台共用同一个编辑弹窗。 */}
      <SkillEditorModal
        open={skillEditorOpen}
        skillId={skillEditorId}
        onClose={() => setSkillEditorOpen(false)}
        onSaved={() => void loadSkillList()}
      />
    </div>
  );
}
