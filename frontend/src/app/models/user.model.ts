/** Espeja `UserResponse` y `UserUpdate`. */
export interface UserResponse {
  id: number;
  username: string;
  email: string;
}

export interface UserUpdate {
  email?: string;
  new_password?: string;
  current_password: string;
}
