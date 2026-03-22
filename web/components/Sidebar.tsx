'use client';

import { useState, useCallback } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { T } from '@/components/d4c/tokens';

interface NavItem {
  href: string;
  label: string;
  icon: string;   // unicode symbol -- no emojis
}

const NAV_ITEMS: NavItem[] = [
  { href: '/dashboard',    label: 'Dashboard',     icon: '\u229E' },
  { href: '/clients',      label: 'Clients',       icon: '\u25EB' },
  { href: '/new-analysis', label: 'New Analysis',  icon: '\u2295' },
  { href: '/onboarding',   label: 'Onboarding',    icon: '\u25C7' },
  { href: '/docs',         label: 'Docs',          icon: '\u2630' },
];

const SIDEBAR_WIDTH_COLLAPSED = 56;
const SIDEBAR_WIDTH_EXPANDED = 200;
const TRANSITION = 'width 200ms cubic-bezier(0.4, 0, 0.2, 1)';

export default function Sidebar() {
  const pathname = usePathname();
  const [expanded, setExpanded] = useState(false);

  const toggle = useCallback(() => setExpanded((v) => !v), []);

  const isActive = (href: string) =>
    pathname === href || (href !== '/' && pathname.startsWith(href));

  const width = expanded ? SIDEBAR_WIDTH_EXPANDED : SIDEBAR_WIDTH_COLLAPSED;

  return (
    <aside
      style={{
        display: 'flex',
        flexDirection: 'column',
        backgroundColor: T.bg.card,
        borderRight: T.border.card,
        height: '100vh',
        position: 'sticky',
        top: 0,
        width,
        flexShrink: 0,
        transition: TRANSITION,
        overflow: 'hidden',
      }}
    >
      {/* Brand + toggle */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: T.space.sm,
          padding: `${T.space.lg} ${T.space.md}`,
          borderBottom: T.border.card,
          cursor: 'pointer',
          minHeight: 56,
        }}
        onClick={toggle}
        title={expanded ? 'Collapse sidebar' : 'Expand sidebar'}
      >
        <span
          style={{
            fontFamily: T.font.mono,
            fontSize: 16,
            fontWeight: 700,
            color: T.accent.teal,
            flexShrink: 0,
            letterSpacing: '-0.02em',
            width: 24,
            textAlign: 'center',
          }}
        >
          D4
        </span>
        {expanded && (
          <span
            style={{
              fontFamily: T.font.display,
              fontSize: 13,
              fontWeight: 600,
              color: T.text.secondary,
              whiteSpace: 'nowrap',
              overflow: 'hidden',
            }}
          >
            Valinor
          </span>
        )}
      </div>

      {/* Navigation */}
      <nav
        style={{
          flex: 1,
          padding: `${T.space.sm} ${T.space.xs}`,
          overflowY: 'auto',
          display: 'flex',
          flexDirection: 'column',
          gap: '2px',
        }}
      >
        {NAV_ITEMS.map(({ href, label, icon }) => {
          const active = isActive(href);
          return (
            <Link
              key={href}
              href={href}
              title={label}
              className={`d4c-nav-link${active ? ' active' : ''}`}
              style={{
                justifyContent: expanded ? 'flex-start' : 'center',
                padding: expanded ? '8px 12px' : '8px 0',
              }}
            >
              <span
                style={{
                  fontSize: 16,
                  lineHeight: 1,
                  flexShrink: 0,
                  width: 20,
                  textAlign: 'center',
                }}
              >
                {icon}
              </span>
              {expanded && (
                <span
                  style={{
                    fontSize: 13,
                    fontWeight: 500,
                    whiteSpace: 'nowrap',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                  }}
                >
                  {label}
                </span>
              )}
            </Link>
          );
        })}
      </nav>

      {/* Footer */}
      <div
        style={{
          padding: `${T.space.md} ${T.space.md}`,
          borderTop: T.border.card,
        }}
      >
        <p
          style={{
            fontFamily: T.font.mono,
            fontSize: 9,
            color: T.text.tertiary,
            margin: 0,
            textAlign: 'center',
            letterSpacing: '0.05em',
          }}
        >
          v2
        </p>
      </div>
    </aside>
  );
}
