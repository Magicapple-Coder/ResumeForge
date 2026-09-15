/** 可按需读取已保存密钥的输入控件。 */

import { LoadingOutlined } from "@ant-design/icons";
import { Input } from "antd";
import { useEffect, useRef, useState } from "react";
import { API_KEY_MASK, isMaskedApiKey } from "./SettingsConfig";

interface Props {
  id?: string;
  value?: string;
  onChange?: (value: string) => void;
  editing: boolean;
  disabled: boolean;
  resetToken: number;
  onReveal: () => Promise<string>;
  onRevealError: (message: string) => void;
}

export default function ApiKeyInput({
  id,
  value = "",
  onChange,
  editing,
  disabled,
  resetToken,
  onReveal,
  onRevealError,
}: Props) {
  const [visible, setVisible] = useState(false);
  const [revealedKey, setRevealedKey] = useState("");
  const [revealing, setRevealing] = useState(false);
  const revealRequestId = useRef(0);
  const maskedReference = isMaskedApiKey(value) ? value : "";

  useEffect(() => {
    revealRequestId.current += 1;
    setVisible(false);
    setRevealedKey("");
    setRevealing(false);
  }, [editing, resetToken]);

  useEffect(
    () => () => {
      revealRequestId.current += 1;
    },
    [],
  );

  const changeVisibility = async (nextVisible: boolean) => {
    if (!nextVisible) {
      revealRequestId.current += 1;
      setVisible(false);
      setRevealedKey("");
      setRevealing(false);
      return;
    }
    if (!maskedReference) {
      setVisible(true);
      return;
    }
    if (revealing) return;

    const requestId = ++revealRequestId.current;
    setRevealing(true);
    try {
      const apiKey = await onReveal();
      if (requestId !== revealRequestId.current) return;
      setRevealedKey(apiKey);
      setVisible(true);
    } catch (error) {
      if (requestId !== revealRequestId.current) return;
      setVisible(false);
      setRevealedKey("");
      onRevealError(error instanceof Error ? error.message : "读取 API Key 失败");
    } finally {
      if (requestId === revealRequestId.current) setRevealing(false);
    }
  };

  const displayedValue = maskedReference ? (visible ? revealedKey : API_KEY_MASK) : value;

  return (
    <Input.Password
      id={id}
      value={displayedValue}
      placeholder="sk-...（无需鉴权时可留空）"
      autoComplete="off"
      readOnly={!editing || Boolean(maskedReference && visible)}
      disabled={disabled || revealing}
      suffix={revealing ? <LoadingOutlined spin /> : undefined}
      visibilityToggle={{
        visible,
        onVisibleChange: (nextVisible) => void changeVisibility(nextVisible),
      }}
      onChange={(event) => {
        if (!editing || (maskedReference && visible)) return;
        onChange?.(event.target.value);
      }}
    />
  );
}
