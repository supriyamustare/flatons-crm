import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import type { Role, User } from "../lib/types";

export interface NewUser {
  email: string;
  full_name: string;
  role: Role;
  password: string;
}

export interface UserChanges {
  full_name?: string;
  role?: Role;
  is_active?: boolean;
  password?: string;
}

const USERS_KEY = ["users"] as const;

export function useUsers() {
  return useQuery({
    queryKey: USERS_KEY,
    queryFn: async () => (await api.get<User[]>("/users")).data,
  });
}

export function useCreateUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: NewUser) => (await api.post<User>("/users", body)).data,
    onSuccess: () => qc.invalidateQueries({ queryKey: USERS_KEY }),
  });
}

export function useUpdateUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, changes }: { id: number; changes: UserChanges }) =>
      (await api.patch<User>(`/users/${id}`, changes)).data,
    onSuccess: () => qc.invalidateQueries({ queryKey: USERS_KEY }),
  });
}

export function useDeactivateUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: number) => {
      await api.delete(`/users/${id}`);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: USERS_KEY }),
  });
}

export function useChangeMyPassword() {
  return useMutation({
    mutationFn: async (body: { current_password: string; new_password: string }) => {
      await api.post("/users/me/password", body);
    },
  });
}
