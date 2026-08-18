/** 经历参考资料：读取小型 UTF-8 文本并直接保存在资料表单中。 */
import { DeleteOutlined, EyeOutlined, FileTextOutlined, UploadOutlined } from "@ant-design/icons";
import { App, Button, Form, Input, Modal, Space, Tag, Typography, Upload } from "antd";
import type { UploadProps } from "antd";
import { useEffect, useRef, useState } from "react";

const MAX_FILE_BYTES = 200_000;
const MAX_FILE_NAME_CHARS = 255;
const SUPPORTED_EXTENSIONS = [".md", ".txt"];

interface Props {
  listName: string;
  fieldName: number;
  editable: boolean;
}

function hasSupportedExtension(fileName: string): boolean {
  const normalized = fileName.toLowerCase();
  return SUPPORTED_EXTENSIONS.some((extension) => normalized.endsWith(extension));
}

async function readUtf8Text(file: File): Promise<string> {
  const buffer = await file.arrayBuffer();
  try {
    return new TextDecoder("utf-8", { fatal: true }).decode(buffer).replace(/^\uFEFF/, "");
  } catch {
    throw new Error("文件不是有效的 UTF-8 编码，请转换编码后重试");
  }
}

export default function ReferenceFileField({ listName, fieldName, editable }: Props) {
  const { message } = App.useApp();
  const form = Form.useFormInstance();
  const [reading, setReading] = useState(false);
  const [viewing, setViewing] = useState(false);
  const readId = useRef(0);
  const fieldNameRef = useRef(fieldName);
  const editableRef = useRef(editable);
  fieldNameRef.current = fieldName;
  editableRef.current = editable;
  const fileName =
    (Form.useWatch([listName, fieldName, "reference_file_name"], form) as string | undefined) ?? "";
  const content =
    (Form.useWatch([listName, fieldName, "reference_content"], form) as string | undefined) ?? "";

  useEffect(
    () => () => {
      readId.current += 1;
    },
    [],
  );

  if (!editable && !fileName && !content) return null;

  const setReference = (name: string, text: string) => {
    const currentFieldName = fieldNameRef.current;
    form.setFieldValue([listName, currentFieldName, "reference_file_name"], name);
    form.setFieldValue([listName, currentFieldName, "reference_content"], text);
  };

  const beforeUpload: UploadProps["beforeUpload"] = (file) => {
    if (!editable) return Upload.LIST_IGNORE;
    if (!hasSupportedExtension(file.name)) {
      message.error("仅支持 .md 或 .txt 格式的总结文件");
      return Upload.LIST_IGNORE;
    }
    if (file.name.length > MAX_FILE_NAME_CHARS) {
      message.error("总结文件名不能超过 255 个字符");
      return Upload.LIST_IGNORE;
    }
    if (file.size > MAX_FILE_BYTES) {
      message.error("总结文件不能超过 200 KB");
      return Upload.LIST_IGNORE;
    }

    const currentReadId = ++readId.current;
    setReading(true);
    void readUtf8Text(file)
      .then((text) => {
        if (readId.current !== currentReadId || !editableRef.current) return;
        setReference(file.name, text);
        message.success("总结文件已添加，保存全部资料后生效");
      })
      .catch((error) => {
        if (readId.current === currentReadId) {
          message.error(error instanceof Error ? error.message : "读取总结文件失败");
        }
      })
      .finally(() => {
        if (readId.current === currentReadId) setReading(false);
      });
    return false;
  };

  const removeReference = () => {
    readId.current += 1;
    setReading(false);
    setReference("", "");
  };

  return (
    <div className="profile-reference-field">
      {editable ? (
        <>
          <Form.Item
            name={[fieldName, "reference_file_name"]}
            label="补充总结名称"
            extra="上传文件会自动填入名称；直接输入内容时可自定义名称"
          >
            <Input maxLength={MAX_FILE_NAME_CHARS} placeholder="如：项目总结.md" />
          </Form.Item>
          <Form.Item
            name={[fieldName, "reference_content"]}
            label="补充总结内容"
            extra="支持直接输入，最多 200,000 字符"
          >
            <Input.TextArea
              rows={5}
              maxLength={200_000}
              showCount
              placeholder="可直接粘贴或输入项目总结、工作成果、校园经历细节等内容"
              onChange={(event) => {
                if (event.target.value && !fileName) {
                  form.setFieldValue(
                    [listName, fieldName, "reference_file_name"],
                    "手动输入总结.md",
                  );
                }
              }}
            />
          </Form.Item>
          <Space wrap>
            <Upload
              accept=".md,.txt,text/markdown,text/plain"
              beforeUpload={beforeUpload}
              showUploadList={false}
              maxCount={1}
              disabled={reading}
            >
              <Button icon={<UploadOutlined />} loading={reading}>
                {fileName ? "替换文件" : "导入文件"}
              </Button>
            </Upload>
            {(fileName || content) && (
              <Button danger icon={<DeleteOutlined />} disabled={reading} onClick={removeReference}>
                移除总结
              </Button>
            )}
            {content && (
              <Button icon={<EyeOutlined />} onClick={() => setViewing(true)}>
                查看内容
              </Button>
            )}
          </Space>
        </>
      ) : (
        <Space wrap>
          <Space size={6}>
            <FileTextOutlined />
            <Typography.Text
              ellipsis={{ tooltip: fileName || "手动输入总结" }}
              style={{ maxWidth: "min(420px, 65vw)" }}
            >
              {fileName || "手动输入总结"}
            </Typography.Text>
            <Tag>{content.length.toLocaleString()} 字</Tag>
          </Space>
          <Button icon={<EyeOutlined />} disabled={!content} onClick={() => setViewing(true)}>
            查看内容
          </Button>
        </Space>
      )}
      <Modal
        title={fileName || "补充总结内容"}
        open={viewing}
        onCancel={() => setViewing(false)}
        footer={<Button onClick={() => setViewing(false)}>关闭</Button>}
        width={760}
        destroyOnHidden
      >
        <Typography.Text type="secondary">{content.length.toLocaleString()} 字</Typography.Text>
        <pre className="profile-reference-preview">{content}</pre>
      </Modal>
    </div>
  );
}
