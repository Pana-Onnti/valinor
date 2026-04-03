'use client';

import { useState, useCallback, useEffect } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { Menu, X } from 'lucide-react';
import { T } from '@/components/d4c/tokens';
import { ThemeToggle } from '@/components/ui/ThemeToggle';

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
const MOBILE_BREAKPOINT = 1024;

export default function Sidebar() {
  const pathname = usePathname();
  const [expanded, setExpanded] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [isMobile, setIsMobile] = useState(false);

  // Track viewport width
  useEffect(() => {
    const check = () => setIsMobile(window.innerWidth < MOBILE_BREAKPOINT);
    check();
    window.addEventListener('resize', check);
    return () => window.removeEventListener('resize', check);
  }, []);

  // Close mobile sidebar on route change
  useEffect(() => {
    setMobileOpen(false);
  }, [pathname]);

  // Prevent body scroll when mobile sidebar is open
  useEffect(() => {
    if (mobileOpen) {
      document.body.style.overflow = 'hidden';
    } else {
      document.body.style.overflow = '';
    }
    return () => { document.body.style.overflow = ''; };
  }, [mobileOpen]);

  const toggle = useCallback(() => setExpanded((v) => !v), []);
  const toggleMobile = useCallback(() => setMobileOpen((v) => !v), []);

  const isActive = (href: string) =>
    pathname === href || (href !== '/' && pathname.startsWith(href));

  const width = expanded ? SIDEBAR_WIDTH_EXPANDED : SIDEBAR_WIDTH_COLLAPSED;

  // Hide sidebar on public demo pages
  if (pathname.startsWith('/demo')) return null;

  const sidebarContent = (
    <aside
      className="d4c-sidebar"
      style={{
        display: 'flex',
        flexDirection: 'column',
        backgroundColor: T.bg.card,
        borderRight: isMobile ? 'none' : T.border.card,
        height: '100vh',
        position: isMobile ? 'fixed' : 'sticky',
        top: 0,
        left: 0,
        width: isMobile ? SIDEBAR_WIDTH_EXPANDED : width,
        flexShrink: 0,
        transition: isMobile ? 'transform 250ms cubic-bezier(0.4, 0, 0.2, 1)' : TRANSITION,
        overflow: 'hidden',
        zIndex: isMobile ? 1001 : 'auto',
        transform: isMobile ? (mobileOpen ? 'translateX(0)' : `translateX(-100%)`) : 'none',
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
        onClick={isMobile ? toggleMobile : toggle}
        title={isMobile ? 'Close menu' : (expanded ? 'Collapse sidebar' : 'Expand sidebar')}
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
        {(expanded || isMobile) && (
          <span
            style={{
              fontFamily: T.font.display,
              fontSize: 13,
              fontWeight: 600,
              color: T.text.secondary,
              whiteSpace: 'nowrap',
              overflow: 'hidden',
              flex: 1,
            }}
          >
            Valinor
          </span>
        )}
        {isMobile && (
          <X size={20} style={{ color: T.text.secondary, flexShrink: 0 }} />
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
          const showLabel = expanded || isMobile;
          return (
            <Link
              key={href}
              href={href}
              title={label}
              className={`d4c-nav-link${active ? ' active' : ''}`}
              style={{
                justifyContent: showLabel ? 'flex-start' : 'center',
                padding: showLabel ? '8px 12px' : '8px 0',
                minHeight: 44,
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
              {showLabel && (
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

      {/* Theme toggle + Footer */}
      <div
        style={{
          padding: `${T.space.sm} ${T.space.md}`,
          borderTop: T.border.card,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          gap: T.space.sm,
        }}
      >
        <ThemeToggle />
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

  return (
    <>
      {/* Mobile hamburger button */}
      {isMobile && !mobileOpen && (
        <button
          onClick={toggleMobile}
          aria-label="Open menu"
          className="d4c-hamburger"
          style={{
            position: 'fixed',
            top: 12,
            left: 12,
            zIndex: 1000,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            width: 44,
            height: 44,
            borderRadius: 8,
            border: `1px solid ${T.border.card.split(' ').pop()}`,
            backgroundColor: T.bg.card,
            color: T.text.secondary,
            cursor: 'pointer',
            padding: 0,
          }}
        >
          <Menu size={20} />
        </button>
      )}

      {/* Overlay backdrop */}
      {isMobile && mobileOpen && (
        <div
          className="d4c-sidebar-overlay"
          onClick={toggleMobile}
          style={{
            position: 'fixed',
            inset: 0,
            backgroundColor: 'rgba(0, 0, 0, 0.6)',
            zIndex: 1000,
          }}
        />
      )}

      {sidebarContent}
    </>
  );
}
