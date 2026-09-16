/** 随请求发送的图片或文档：base64 data URL，与助手附件同一种形状。 */

export interface ExtractionImageInput {
  name: string;
  mime_type: string;
  /** `data:image/png;base64,...` */
  data: string;
}

/** 文档（pdf/docx）：文字由后端在本机提取，前端只传原始文件。 */
export interface ExtractionDocumentInput {
  name: string;
  mime_type: string;
  /** `data:application/pdf;base64,...` */
  data: string;
}
