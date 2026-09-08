export enum SignType {
  FINGERSPELLING = 'fingerspelling',
  STATIC = 'static',
  DYNAMIC = 'dynamic',
}

export interface SignDefinition {
  id: string;
  gloss: string;
  type: SignType;
  spanishText: string;
  description?: string;
  handshape?: string;
  movement?: string;
  location?: string;
  facialExpression?: string;
  category?: string;
}

export interface Sign {
  id: string;
  gloss: string;
  type: SignType;
  spanishText: string;
}
