/** 随请求发送的图片：base64 data URL，与助手附件同一种形状。 */

export interface ExtractionImageInput {
  name: string;
  mime_type: string;
  /** `data:image/png;base64,...` */
  data: string;
}
