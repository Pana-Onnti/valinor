'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';

interface NavItem {
  href: string;
  label: string;
  icon: string;
}

const NAV_ITEMS: NavItem[] = [
  { href: '/dashboard',     label: 'Dashboard',      icon: '📊' },
  { href: '/clients',       label: 'Clients',         icon: '🏢' },
  { href: '/new-analysis',  label: 'New Analysis',    icon: '🔍' },
  { href: '/onboarding',    label: 'Onboarding',      icon: '🚀' },
  { href: '/docs',          label: 'Docs',            icon: '📖' },
];

export default function Sidebar() {
  const pathname = usePathname();

  const isActive = (href: string) =>
    pathname === href || (href !== '/' && pathname.startsWith(href));

  return (
    <aside className="flex flex-col bg-gray-900 text-gray-100 h-screen sticky top-0 w-14 md:w-64 shrink-0 transition-all duration-200">
      {/* Brand */}
      <div className="flex items-center gap-3 px-3 md:px-5 py-5 border-b border-gray-700">
        <span className="text-2xl leading-none shrink-0">📈</span>
        <span className="hidden md:block text-lg font-bold tracking-tight text-white">
          Valinor
        </span>
      </div>

      {/* Navigation */}
      <nav className="flex-1 px-2 md:px-3 py-4 space-y-1 overflow-y-auto">
        {NAV_ITEMS.map(({ href, label, icon }) => {
          const active = isActive(href);
          return (
            <Link
              key={href}
              href={href}
              title={label}
              className={`
                flex items-center gap-3 rounded-lg px-2 md:px-3 py-2.5 text-sm font-medium
                transition-colors duration-150
                ${active
                  ? 'bg-violet-600 text-white'
                  : 'text-gray-400 hover:bg-gray-800 hover:text-white'
                }
              `}
            >
              <span className="text-base leading-none shrink-0">{icon}</span>
              <span className="hidden md:block">{label}</span>
            </Link>
          );
        })}
      </nav>

      {/* Footer */}
      <div className="px-3 md:px-5 py-4 border-t border-gray-700">
        <p className="hidden md:block text-xs text-gray-500 leading-snug">
          <span className="block font-medium text-gray-400">Delta 4C</span>
          v2.0.0
        </p>
        <p className="md:hidden text-xs text-gray-600 text-center">v2</p>
      </div>
    </aside>
  );
}
