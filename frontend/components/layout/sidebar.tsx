'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { cn } from '@/lib/utils';
import { useAuth } from '@/context/auth-context';
import { ROLE_COLORS } from '@/lib/types';
import type { UserRole } from '@/lib/types';
import {
  Heart,
  LayoutDashboard,
  BookOpenCheck,
  Upload,
  Database,
  ClipboardList,
  Users,
  Server,
  Settings,
  LogOut,
  ChevronRight,
} from 'lucide-react';

interface NavItem {
  href:  string;
  label: string;
  icon:  React.ElementType;
}

interface NavSection {
  title:  string;
  items:  NavItem[];
  roles?: UserRole[];    // if set, only these roles see this section
}

const NAV_SECTIONS: NavSection[] = [
  {
    title: 'MAIN',
    items: [
      { href: '/dashboard', label: 'Dashboard',      icon: LayoutDashboard },
      { href: '/query',     label: 'Clinical AI',    icon: BookOpenCheck   },
    ],
  },
  {
    title: 'LIBRARY',
    items: [
      { href: '/documents', label: 'Documents',     icon: Database      },
      { href: '/upload',    label: 'Upload',        icon: Upload        },
      { href: '/history',   label: 'Query History', icon: ClipboardList },
    ],
  },
  {
    title: 'ADMIN',
    roles: ['admin'],
    items: [
      { href: '/admin/users',           label: 'User Management', icon: Users    },
      { href: '/admin/knowledge-bases', label: 'Libraries',       icon: Server   },
      { href: '/settings',              label: 'System Settings', icon: Settings },
    ],
  },
];

// Per-role nav rules for KNOWLEDGE section items
const ROLE_ITEM_ACCESS: Record<string, UserRole[]> = {
  '/upload': ['admin', 'physician'],
};

function getInitials(name: string): string {
  return name
    .split(' ')
    .map(n => n[0])
    .slice(0, 2)
    .join('')
    .toUpperCase();
}

export function Sidebar() {
  const pathname         = usePathname();
  const { user, logout } = useAuth();
  const role             = (user?.role ?? 'physician') as UserRole;

  const isVisible = (section: NavSection, item?: NavItem): boolean => {
    // Section-level role filter
    if (section.roles && !section.roles.includes(role)) return false;
    // Item-level role filter
    if (item && ROLE_ITEM_ACCESS[item.href] && !ROLE_ITEM_ACCESS[item.href].includes(role)) return false;
    return true;
  };

  return (
    <aside className="flex h-screen w-[260px] shrink-0 flex-col border-r bg-card">

      {/* Logo */}
      <div className="flex items-center gap-3 border-b px-5 py-4">
        <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-primary shadow-sm">
          <Heart className="h-4.5 w-4.5 text-primary-foreground" strokeWidth={2.5} />
        </div>
        <div className="leading-tight">
          <p className="text-sm font-bold tracking-tight text-foreground">HCIP</p>
          <p className="text-[10px] text-muted-foreground">Clinical Intelligence</p>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex flex-1 flex-col gap-4 overflow-y-auto p-3 pt-4">
        {NAV_SECTIONS.map(section => {
          if (!isVisible(section)) return null;

          const visibleItems = section.items.filter(item => isVisible(section, item));
          if (visibleItems.length === 0) return null;

          return (
            <div key={section.title}>
              <p className="mb-1.5 px-3 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/60">
                {section.title}
              </p>
              <div className="space-y-0.5">
                {visibleItems.map(({ href, label, icon: Icon }) => {
                  const active = pathname === href || (href !== '/dashboard' && pathname.startsWith(href));
                  return (
                    <Link
                      key={href}
                      href={href}
                      className={cn(
                        'group flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-all duration-150',
                        active
                          ? 'bg-primary text-primary-foreground shadow-sm'
                          : 'text-muted-foreground hover:bg-accent hover:text-foreground',
                      )}
                    >
                      <Icon className={cn('h-4 w-4 shrink-0', active ? 'text-primary-foreground' : '')} />
                      <span className="flex-1">{label}</span>
                      {active && (
                        <ChevronRight className="h-3 w-3 opacity-60" />
                      )}
                    </Link>
                  );
                })}
              </div>
            </div>
          );
        })}
      </nav>

      {/* User card */}
      {user && (
        <div className="border-t p-3">
          <div className="flex items-center gap-3 rounded-lg px-2 py-2.5">
            {/* Avatar */}
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-semibold text-primary">
              {getInitials(user.name)}
            </div>

            <div className="min-w-0 flex-1">
              <p className="truncate text-xs font-semibold text-foreground">{user.name}</p>
              <span className={cn(
                'mt-0.5 inline-block rounded-full border px-1.5 py-px text-[9px] font-semibold uppercase tracking-wider',
                ROLE_COLORS[role],
              )}>
                {role}
              </span>
            </div>

            <button
              onClick={logout}
              title="Sign out"
              className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive"
            >
              <LogOut className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
      )}
    </aside>
  );
}
