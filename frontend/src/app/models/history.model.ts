/** Espeja `HistoryResponse` y `HistoryUpdate`. Solo `spanish_text` es editable. */
export interface HistoryEntry {
  readonly id: number;
  readonly user_id: number;
  readonly predicted_label: string;
  readonly spanish_text: string;
  readonly confidence: number;
  readonly mode: string;
  readonly created_at: string;
}

export interface HistoryUpdate {
  spanish_text: string;
}
