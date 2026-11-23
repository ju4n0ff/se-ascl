/** Espeja `UserCreate`, `UserLogin` y `Token` de backend/app/schemas/schemas.py. */
export interface UserCreate {
  username: string;
  email: string;
  password: string;
}

export interface UserLogin {
  username: string;
  password: string;
}

export interface Token {
  access_token: string;
  token_type: string;
}
