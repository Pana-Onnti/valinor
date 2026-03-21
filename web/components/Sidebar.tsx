'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { T } from '@/components/d4c/tokens';

interface NavItem {
  href: string;
  label: string;
  icon: string;   // unicode symbol — no emojis
}

const NAV_ITEMS: NavItem[] = [
  { href: '/dashboard',    label: 'Dashboard',     icon: '⊡' },
  { href: '/clients',      label: 'Clients',        icon: '◫' },
  { href: '/new-analysis', label: 'New Analysis',   icon: '⊕' },
  { href: '/onboarding',   label: 'Onboarding',     icon: '◇' },
  { href: '/docs',         label: 'Docs',           icon: '☰' },
];

const sidebarStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  backgroundColor: T.bg.card,
  borderRight: T.border.card,
  height: '100vh',
  position: 'sticky',
  top: 0,
  width: '64px',
  flexShrink: 0,
};

const brandStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: T.space.sm,
  padding: `${T.space.lg} ${T.space.md}`,
  borderBottom: T.border.card,
};

const navStyle: React.CSSProperties = {
  flex: 1,
  padding: `${T.space.sm} ${T.space.sm}`,
  overflowY: 'auto',
  display: 'flex',
  flexDirection: 'column',
  gap: '2px',
};

const footerStyle: React.CSSProperties = {
  padding: `${T.space.md} ${T.space.md}`,
  borderTop: T.border.card,
};

export default function Sidebar() {
  const pathname = usePathname();

  const isActive = (href: string) =>
    pathname === href || (href !== '/' && pathname.startsWith(href));

  return (
    <aside style={sidebarStyle}>
      {/* Brand */}
      <div style={brandStyle}>
        <span style={{
          fontFamily: T.font.mono,
          fontSize: 16,
          fontWeight: 700,
          color: T.accent.teal,
          flexShrink: 0,
          letterSpacing: '-0.02em',
        }}>
          D4
        </span>
      </div>

      {/* Navigation */}
      <nav style={navStyle}>
        {NAV_ITEMS.map(({ href, label, icon }) => {
          const active = isActive(href);
          return (
            <Link
              key={href}
              href={href}
              title={label}
              className={`d4c-nav-link${active ? ' active' : ''}`}
            >
              <span style={{ fontSize: 16, lineHeight: 1, flexShrink: 0, width: 20, textAlign: 'center' }}>
                {icon}
              </span>
            </Link>
          );
        })}
      </nav>

      {/* Footer */}
      <div style={footerStyle}>
        <p style={{
          fontFamily: T.font.mono,
          fontSize: 9,
          color: T.text.tertiary,
          margin: 0,
          textAlign: 'center',
          letterSpacing: '0.05em',
        }}>
          v2
        </p>
      </div>
    </aside>
  );
}
