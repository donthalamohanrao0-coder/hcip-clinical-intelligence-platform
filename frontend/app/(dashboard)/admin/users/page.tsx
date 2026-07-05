'use client';

import { useState, useEffect, useCallback } from 'react';
import { useAuth } from '@/context/auth-context';
import { Header } from '@/components/layout/header';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Alert, AlertDescription } from '@/components/ui/alert';
import {
  AlertCircle,
  CheckCircle2,
  Edit2,
  Loader2,
  Plus,
  Search,
  Shield,
  Trash2,
  Users,
  X,
} from 'lucide-react';
import { KNOWLEDGE_BASES, ROLE_COLORS, ROLE_LABELS, ROLE_KB_ACCESS } from '@/lib/types';
import type { User, UserRole } from '@/lib/types';
import { cn } from '@/lib/utils';

function timeAgo(iso?: string): string {
  if (!iso) return 'Never';
  const diff  = Date.now() - new Date(iso).getTime();
  const hours = Math.floor(diff / 3600000);
  if (hours < 1)  return 'Just now';
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

function getInitials(name: string): string {
  return name.split(' ').map(n => n[0]).slice(0, 2).join('').toUpperCase();
}

// Modal: Create/Edit User
interface UserFormProps {
  initial?:  Partial<User>;
  orgId:     string;
  onSave:    (data: Omit<User, 'id' | 'created_at' | 'last_login'> & { password?: string }) => void;
  onCancel:  () => void;
  isLoading: boolean;
}

function UserFormModal({ initial, orgId, onSave, onCancel, isLoading }: UserFormProps) {
  const [name,        setName]        = useState(initial?.name ?? '');
  const [email,       setEmail]       = useState(initial?.email ?? '');
  const [role,        setRole]        = useState<UserRole>(initial?.role ?? 'physician');
  const [password,    setPassword]    = useState('');
  const [confirmPwd,  setConfirmPwd]  = useState('');
  const [allowedKbs,  setAllowedKbs]  = useState<string[]>(initial?.allowed_kb_ids ?? ROLE_KB_ACCESS['physician']);
  const [error,       setError]       = useState('');

  const isEdit = Boolean(initial?.id);

  const handleRoleChange = (r: UserRole) => {
    setRole(r);
    setAllowedKbs(ROLE_KB_ACCESS[r]);
  };

  const toggleKb = (kbId: string) => {
    setAllowedKbs(prev =>
      prev.includes(kbId) ? prev.filter(k => k !== kbId) : [...prev, kbId],
    );
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim() || !email.trim()) { setError('Name and email are required.'); return; }
    if (!isEdit && !password)          { setError('Password is required.'); return; }
    if (!isEdit && password !== confirmPwd) { setError('Passwords do not match.'); return; }
    setError('');
    onSave({ name, email, role, organization_id: orgId, allowed_kb_ids: allowedKbs, is_active: initial?.is_active ?? true, password });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4">
      <div className="w-full max-w-lg rounded-xl border bg-background shadow-xl">
        <div className="flex items-center justify-between border-b px-6 py-4">
          <h2 className="text-base font-semibold">{isEdit ? 'Edit User' : 'Add Team Member'}</h2>
          <button onClick={onCancel} className="text-muted-foreground hover:text-foreground">
            <X className="h-4 w-4" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4 p-6">
          {error && (
            <Alert variant="destructive">
              <AlertCircle className="h-4 w-4" />
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}

          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label>Full Name</Label>
              <Input value={name} onChange={e => setName(e.target.value)} placeholder="Dr. Jane Smith" required />
            </div>
            <div className="space-y-2">
              <Label>Email</Label>
              <Input type="email" value={email} onChange={e => setEmail(e.target.value)} placeholder="jane@hospital.org" required />
            </div>
          </div>

          <div className="space-y-2">
            <Label>Role</Label>
            <Select value={role} onValueChange={v => handleRoleChange(v as UserRole)}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {(Object.entries(ROLE_LABELS) as [UserRole, string][]).map(([val, lbl]) => (
                  <SelectItem key={val} value={val}>{lbl}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {!isEdit && (
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label>Password</Label>
                <Input type="password" value={password} onChange={e => setPassword(e.target.value)} placeholder="••••••••" />
              </div>
              <div className="space-y-2">
                <Label>Confirm Password</Label>
                <Input type="password" value={confirmPwd} onChange={e => setConfirmPwd(e.target.value)} placeholder="••••••••" />
              </div>
            </div>
          )}

          <div className="space-y-2">
            <Label>Library Access</Label>
            <div className="grid grid-cols-1 gap-2">
              {KNOWLEDGE_BASES.map(kb => (
                <label key={kb.id} className="flex items-center gap-3 rounded-lg border px-3 py-2 cursor-pointer hover:bg-accent">
                  <input
                    type="checkbox"
                    checked={allowedKbs.includes(kb.id)}
                    onChange={() => toggleKb(kb.id)}
                    className="h-4 w-4 rounded border-gray-300 text-primary"
                  />
                  <div className="min-w-0">
                    <p className="text-sm font-medium">{kb.label}</p>
                    <p className="text-xs text-muted-foreground">{kb.description}</p>
                  </div>
                </label>
              ))}
            </div>
          </div>

          <div className="flex justify-end gap-3 border-t pt-4">
            <Button type="button" variant="outline" onClick={onCancel}>Cancel</Button>
            <Button type="submit" disabled={isLoading}>
              {isLoading && <Loader2 className="h-4 w-4 animate-spin" />}
              {isEdit ? 'Save Changes' : 'Create User'}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}

// Confirm delete dialog
function DeleteDialog({ user, onConfirm, onCancel, isLoading }: {
  user: User; onConfirm: () => void; onCancel: () => void; isLoading: boolean;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4">
      <div className="w-full max-w-sm rounded-xl border bg-background shadow-xl p-6 space-y-4">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-full bg-destructive/10">
            <Trash2 className="h-5 w-5 text-destructive" />
          </div>
          <div>
            <h2 className="font-semibold">Remove User</h2>
            <p className="text-sm text-muted-foreground">This action cannot be undone.</p>
          </div>
        </div>
        <p className="text-sm">
          Are you sure you want to remove <strong>{user.name}</strong> from the platform?
        </p>
        <div className="flex justify-end gap-3">
          <Button variant="outline" onClick={onCancel}>Cancel</Button>
          <Button variant="destructive" onClick={onConfirm} disabled={isLoading}>
            {isLoading && <Loader2 className="h-4 w-4 animate-spin" />}
            Remove User
          </Button>
        </div>
      </div>
    </div>
  );
}

export default function AdminUsersPage() {
  const { user: currentUser, token } = useAuth();

  const [users,       setUsers]       = useState<User[]>([]);
  const [isLoadingUsers, setIsLoadingUsers] = useState(true);
  const [loadError,   setLoadError]   = useState<string | null>(null);
  const [search,      setSearch]      = useState('');
  const [roleFilter,  setRoleFilter]  = useState<string>('all');
  const [showCreate,  setShowCreate]  = useState(false);
  const [editUser,    setEditUser]    = useState<User | null>(null);
  const [deleteUser,  setDeleteUser]  = useState<User | null>(null);
  const [isSaving,    setIsSaving]    = useState(false);
  const [toast,       setToast]       = useState<string | null>(null);

  const showToast = (msg: string) => {
    setToast(msg);
    setTimeout(() => setToast(null), 3000);
  };

  const fetchUsers = useCallback(async () => {
    setIsLoadingUsers(true);
    setLoadError(null);
    try {
      const resp = await fetch('/api/admin/users', {
        headers: { 'X-API-Token': token ?? '' },
      });
      const data = await resp.json();
      if (!resp.ok || data.success === false) {
        throw new Error(data.error || 'Failed to load users');
      }
      setUsers(data.users ?? []);
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : 'Failed to load users');
    } finally {
      setIsLoadingUsers(false);
    }
  }, [token]);

  useEffect(() => {
    if (token) fetchUsers();
  }, [token, fetchUsers]);

  const handleCreate = useCallback(async (data: Omit<User, 'id' | 'created_at' | 'last_login'> & { password?: string }) => {
    setIsSaving(true);
    try {
      const resp = await fetch('/api/admin/users', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json', 'X-API-Token': token ?? '' },
        body:    JSON.stringify(data),
      });
      const result = await resp.json();
      if (!resp.ok || result.success === false) {
        throw new Error(result.detail || result.error || 'Failed to create user');
      }
      setUsers(prev => [result.data, ...prev]);
      setShowCreate(false);
      showToast('User created successfully');
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Failed to create user');
    } finally {
      setIsSaving(false);
    }
  }, [token]);

  const handleEdit = useCallback(async (data: Omit<User, 'id' | 'created_at' | 'last_login'> & { password?: string }) => {
    if (!editUser) return;
    setIsSaving(true);
    try {
      const resp = await fetch(`/api/admin/users/${editUser.id}`, {
        method:  'PATCH',
        headers: { 'Content-Type': 'application/json', 'X-API-Token': token ?? '' },
        body:    JSON.stringify(data),
      });
      const result = await resp.json();
      if (!resp.ok || result.success === false) {
        throw new Error(result.detail || result.error || 'Failed to update user');
      }
      setUsers(prev => prev.map(u => u.id === editUser.id ? result.data : u));
      setEditUser(null);
      showToast('User updated');
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Failed to update user');
    } finally {
      setIsSaving(false);
    }
  }, [editUser, token]);

  const handleDelete = useCallback(async () => {
    if (!deleteUser) return;
    setIsSaving(true);
    try {
      const resp = await fetch(`/api/admin/users/${deleteUser.id}`, {
        method:  'DELETE',
        headers: { 'X-API-Token': token ?? '' },
      });
      if (!resp.ok && resp.status !== 204) {
        const result = await resp.json().catch(() => ({}));
        throw new Error(result.detail || result.error || 'Failed to remove user');
      }
      setUsers(prev => prev.filter(u => u.id !== deleteUser.id));
      setDeleteUser(null);
      showToast('User removed');
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Failed to remove user');
    } finally {
      setIsSaving(false);
    }
  }, [deleteUser, token]);

  const toggleActive = useCallback(async (userId: string) => {
    const target = users.find(u => u.id === userId);
    if (!target) return;
    try {
      const resp = await fetch(`/api/admin/users/${userId}`, {
        method:  'PATCH',
        headers: { 'Content-Type': 'application/json', 'X-API-Token': token ?? '' },
        body:    JSON.stringify({ is_active: !target.is_active }),
      });
      const result = await resp.json();
      if (!resp.ok || result.success === false) {
        throw new Error(result.detail || result.error || 'Failed to update user');
      }
      setUsers(prev => prev.map(u => u.id === userId ? result.data : u));
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Failed to update user');
    }
  }, [users, token]);

  const filtered = users.filter(u => {
    const matchSearch = !search || u.name.toLowerCase().includes(search.toLowerCase()) || u.email.toLowerCase().includes(search.toLowerCase());
    const matchRole   = roleFilter === 'all' || u.role === roleFilter;
    return matchSearch && matchRole;
  });

  const stats = {
    total:      users.length,
    active:     users.filter(u => u.is_active).length,
    admins:     users.filter(u => u.role === 'admin').length,
    physicians: users.filter(u => u.role === 'physician').length,
  };

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      <Header
        title="User Management"
        description="Manage clinical staff accounts and access control"
        badge="Admin"
      />

      {/* Toast */}
      {toast && (
        <div className="fixed bottom-6 right-6 z-50 flex items-center gap-2 rounded-lg border bg-background px-4 py-3 shadow-lg">
          <CheckCircle2 className="h-4 w-4 text-green-500" />
          <span className="text-sm">{toast}</span>
        </div>
      )}

      {showCreate && (
        <UserFormModal
          orgId={currentUser?.organization_id ?? ''}
          onSave={handleCreate}
          onCancel={() => setShowCreate(false)}
          isLoading={isSaving}
        />
      )}
      {editUser && (
        <UserFormModal
          initial={editUser}
          orgId={currentUser?.organization_id ?? ''}
          onSave={handleEdit}
          onCancel={() => setEditUser(null)}
          isLoading={isSaving}
        />
      )}
      {deleteUser && (
        <DeleteDialog user={deleteUser} onConfirm={handleDelete} onCancel={() => setDeleteUser(null)} isLoading={isSaving} />
      )}

      <div className="flex-1 overflow-auto">
        <div className="mx-auto max-w-6xl space-y-6 p-6">

          {/* Stats row */}
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            {[
              { label: 'Total Users',  value: stats.total,      icon: Users,  color: 'text-blue-600'   },
              { label: 'Active',       value: stats.active,     icon: CheckCircle2, color: 'text-green-600' },
              { label: 'Admins',       value: stats.admins,     icon: Shield, color: 'text-purple-600' },
              { label: 'Physicians',   value: stats.physicians, icon: Users,  color: 'text-indigo-600' },
            ].map(s => (
              <Card key={s.label}>
                <CardContent className="p-4">
                  <div className="flex items-center gap-1.5 text-muted-foreground">
                    <s.icon className={cn('h-3.5 w-3.5', s.color)} />
                    <span className="text-xs">{s.label}</span>
                  </div>
                  <p className="mt-2 text-2xl font-bold">{s.value}</p>
                </CardContent>
              </Card>
            ))}
          </div>

          {/* Controls */}
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex flex-1 gap-3">
              <div className="relative flex-1 max-w-xs">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                <Input
                  className="pl-9"
                  placeholder="Search users..."
                  value={search}
                  onChange={e => setSearch(e.target.value)}
                />
              </div>
              <Select value={roleFilter} onValueChange={setRoleFilter}>
                <SelectTrigger className="w-36">
                  <SelectValue placeholder="All roles" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All roles</SelectItem>
                  {(Object.entries(ROLE_LABELS) as [UserRole, string][]).map(([val, lbl]) => (
                    <SelectItem key={val} value={val}>{lbl}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <Button onClick={() => setShowCreate(true)}>
              <Plus className="h-4 w-4" />
              Add User
            </Button>
          </div>

          {/* Table */}
          <Card>
            <CardContent className="p-0">
              {isLoadingUsers ? (
                <div className="flex flex-col items-center gap-3 py-16 text-center text-muted-foreground">
                  <Loader2 className="h-8 w-8 animate-spin opacity-40" />
                  <p className="text-sm">Loading users…</p>
                </div>
              ) : loadError ? (
                <div className="flex flex-col items-center gap-3 py-16 text-center text-muted-foreground">
                  <AlertCircle className="h-10 w-10 text-destructive/50" />
                  <p className="font-medium text-destructive">{loadError}</p>
                  <Button variant="outline" onClick={fetchUsers}>Retry</Button>
                </div>
              ) : filtered.length === 0 ? (
                <div className="flex flex-col items-center gap-3 py-16 text-center text-muted-foreground">
                  <Users className="h-12 w-12 opacity-20" />
                  <p className="font-medium">No users found</p>
                  <p className="text-sm">Try adjusting your search or filters.</p>
                  <Button onClick={() => setShowCreate(true)}>
                    <Plus className="h-4 w-4" />
                    Add your first team member
                  </Button>
                </div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full">
                    <thead>
                      <tr className="border-b bg-muted/30">
                        {['User', 'Role', 'Libraries', 'Status', 'Last Login', 'Actions'].map(h => (
                          <th key={h} className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                            {h}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody className="divide-y">
                      {filtered.map(user => (
                        <tr key={user.id} className="hover:bg-muted/20 transition-colors">
                          {/* User */}
                          <td className="px-4 py-3">
                            <div className="flex items-center gap-3">
                              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-bold text-primary">
                                {getInitials(user.name)}
                              </div>
                              <div>
                                <p className="text-sm font-medium">{user.name}</p>
                                <p className="text-xs text-muted-foreground">{user.email}</p>
                              </div>
                            </div>
                          </td>
                          {/* Role */}
                          <td className="px-4 py-3">
                            <span className={cn(
                              'inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium',
                              ROLE_COLORS[user.role],
                            )}>
                              {ROLE_LABELS[user.role]}
                            </span>
                          </td>
                          {/* Libraries */}
                          <td className="px-4 py-3">
                            <div className="flex items-center gap-1.5">
                              <span className="text-sm font-medium">{user.allowed_kb_ids.length}</span>
                              <span className="text-xs text-muted-foreground">
                                / {KNOWLEDGE_BASES.length} libraries
                              </span>
                            </div>
                          </td>
                          {/* Status */}
                          <td className="px-4 py-3">
                            <button
                              onClick={() => toggleActive(user.id)}
                              className={cn(
                                'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium transition-colors',
                                user.is_active
                                  ? 'bg-green-50 text-green-700 border-green-200 hover:bg-green-100'
                                  : 'bg-gray-50 text-gray-500 border-gray-200 hover:bg-gray-100',
                              )}
                            >
                              <span className={cn('h-1.5 w-1.5 rounded-full', user.is_active ? 'bg-green-500' : 'bg-gray-400')} />
                              {user.is_active ? 'Active' : 'Inactive'}
                            </button>
                          </td>
                          {/* Last Login */}
                          <td className="px-4 py-3">
                            <span className="text-xs text-muted-foreground">{timeAgo(user.last_login)}</span>
                          </td>
                          {/* Actions */}
                          <td className="px-4 py-3">
                            <div className="flex items-center gap-1">
                              <button
                                onClick={() => setEditUser(user)}
                                className="flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground transition-colors"
                                title="Edit user"
                              >
                                <Edit2 className="h-3.5 w-3.5" />
                              </button>
                              <button
                                onClick={() => setDeleteUser(user)}
                                className="flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground hover:bg-destructive/10 hover:text-destructive transition-colors"
                                title="Remove user"
                              >
                                <Trash2 className="h-3.5 w-3.5" />
                              </button>
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </CardContent>
          </Card>

        </div>
      </div>
    </div>
  );
}
