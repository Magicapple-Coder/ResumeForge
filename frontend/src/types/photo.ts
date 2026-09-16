/** 个人照片（可保存多张，选择其中一张用于简历）。 */

export interface ProfilePhoto {
  id: number;
  name: string;
  /** 受限的 base64 图片 data URL。 */
  image: string;
  /** 当前用于简历的那一张；同一时间只有一张为 true。 */
  is_primary: boolean;
  created_at: string;
}

export const MAX_PROFILE_PHOTOS = 8;
