export interface Permission {
  id: string
  name: string
  description: string
  resource: string
  action: string
}

export interface Role {
  id: string
  name: string
  description: string
  permissions: Permission[]
  isDefault?: boolean
}

export interface User {
  id: string
  name: string
  email: string
  roles: Role[]
  avatar?: string
}

export interface RBACProps {
  users: User[]
  roles: Role[]
  permissions: Permission[]
  onAssignRole?: (userId: string, roleId: string) => void
  onRemoveRole?: (userId: string, roleId: string) => void
  onCreateRole?: (role: Omit<Role, 'id'>) => void
  onUpdateRole?: (role: Role) => void
  onDeleteRole?: (roleId: string) => void
}

export interface RoleGateProps {
  user: User
  requiredRoles?: string[]
  requiredPermissions?: string[]
  fallback?: boolean
}
