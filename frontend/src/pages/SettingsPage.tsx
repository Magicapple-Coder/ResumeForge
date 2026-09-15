/** 设置页：大模型配置（含预设与连通测试）。 */
import { CloseOutlined, EditOutlined, SaveOutlined } from "@ant-design/icons";
import { App, Button, Form, Typography } from "antd";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  applyBackup,
  deleteLLMConfigRecord,
  exportBackup,
  getLLMConfig,
  listLLMConfigRecords,
  revealLLMApiKey,
  saveLLMConfig,
  saveLLMConfigRecord,
  testLLM,
  uploadBackup,
} from "../api/settings";
import { LLM_PRESETS } from "../config";
import DataBackupCard from "../components/settings/DataBackupCard";
import LLMConfigCard from "../components/settings/LLMConfigCard";
import LLMConfigRecordsCard from "../components/settings/LLMConfigRecordsCard";
import {
  API_KEY_MASK,
  CUSTOM_PRESET,
  configFromFormValues,
  configFromRecord,
  formValuesFromConfig,
  isMaskedApiKey,
  sameConfig,
  type SettingsFormValues,
} from "../components/settings/SettingsConfig";
import type { BackupPreview, LLMConfig, LLMConfigRecord, LLMTestResult } from "../types";
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

  const [backupExporting, setBackupExporting] = useState(false);
  const [backupUploading, setBackupUploading] = useState(false);
  const [backupApplying, setBackupApplying] = useState(false);
  // 上传成功后先展示预览，用户确认之前不会改动任何数据。
  const [backupPreview, setBackupPreview] = useState<BackupPreview | null>(null);

  const runBackupExport = async () => {
    if (backupExporting) return;
    setBackupExporting(true);
    try {
      const { blob, filename } = await exportBackup();
      downloadBlob(blob, filename);
      message.success("备份已导出到浏览器的下载目录");
    } catch (err) {
      message.error(err instanceof Error ? err.message : "导出备份失败");
    } finally {
      setBackupExporting(false);
    }
  };

  const selectBackupFile = async (file: File) => {
    if (backupUploading) return;
    setBackupUploading(true);
    try {
      setBackupPreview(await uploadBackup(file));
    } catch (err) {
      message.error(err instanceof Error ? err.message : "读取备份文件失败");
    } finally {
      setBackupUploading(false);
    }
  };

  const confirmBackupRestore = async () => {
    if (!backupPreview || backupApplying) return;
    setBackupApplying(true);
    try {
      await applyBackup(backupPreview.token);
      setBackupPreview(null);
      message.success("恢复完成，正在重新加载页面");
      // 稍等提示可见再整页重载：恢复后所有本地状态都要按新数据重建。
      window.setTimeout(reloadPage, 800);
    } catch (err) {
      // 失败时保留弹窗，用户可以重试或取消。
      message.error(err instanceof Error ? err.message : "恢复备份失败");
    } finally {
      setBackupApplying(false);
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

      <DataBackupCard
        exporting={backupExporting}
        uploading={backupUploading}
        applying={backupApplying}
        preview={backupPreview}
        onExport={() => void runBackupExport()}
        onSelectFile={(file) => void selectBackupFile(file)}
        onConfirmRestore={() => void confirmBackupRestore()}
        onCancelRestore={() => {
          if (!backupApplying) setBackupPreview(null);
        }}
      />
    </div>
  );
}
