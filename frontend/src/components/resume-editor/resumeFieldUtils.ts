/** 简历编辑器共享的多行字段转换。 */

export const splitLines = (value: string): string[] =>
  value
    .split(/\r?\n/)
    .map((item) => item.trim())
    .filter(Boolean);

export const multilineItemProps = {
  getValueProps: (value: string[] | undefined) => ({ value: (value ?? []).join("\n") }),
  normalize: (value: string) => splitLines(value),
};
